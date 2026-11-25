"""One product search across stores, for a request that names no store ("busca audífonos Sony baratos").

One Google Shopping search (Serper) in the person's country, and the best few offers across stores, each
with the store's own address and whether Confío can pay that store. Picking one starts the ordinary
purchase (service.start) at THAT store, opening that product's own page first when its address is known.

What a search returns is the web's text: it is shown to the person on a card and never handed to the model.
The store an offer goes to is never a google.com address: it is read off the offer's link when that is the
store's own, else off the store's name as Google writes it (a known store, or a name that is an address).
An offer whose store cannot be told is not shown. The key lives in Parameter Store (conf.serper_api_key)
and is never logged.
"""
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

import requests
from django.core.cache import cache
from django.utils import timezone

from . import conf, countries, guard, sites, stores

logger = logging.getLogger(__name__)

SHOPPING_URL = 'https://google.serper.dev/shopping'
SEARCH_URL = 'https://google.serper.dev/search'
TAG = 'agent_offers'
ACTION = {'type': 'offers', 'label': 'Ver opciones'}

# Store names Google writes that are not an address and not a known store (sites.KNOWN): only domains that are
# surely that store's. Anything else is refused, never guessed.
_SOURCES = {
    'coppel': 'coppel.com', 'sanborns': 'sanborns.com.mx', 'sears mexico': 'sears.com.mx',
    'el palacio de hierro': 'elpalaciodehierro.com', 'bodega aurrera': 'bodegaaurrera.com.mx',
    'claro shop': 'claroshop.com', 'soriana': 'soriana.com', 'casas bahia': 'casasbahia.com.br',
    'pichau': 'pichau.com.br', 'carrefour': 'carrefour.com.br', 'aliexpress': 'aliexpress.com',
    'temu': 'temu.com', 'shein': 'shein.com',
}
# Stores on that list whose address does not say their country (".com"): found in a search in that country, they
# count as that country for the pay label and the purchase's rail (decided 2026-11-25). Any other ".com" does not.
LOCAL_COM = {'coppel.com': 'MX', 'elpalaciodehierro.com': 'MX', 'claroshop.com': 'MX', 'soriana.com': 'MX'}


def country_of(site, searched=''):
    """A store's country: its own address, or the search's country for a listed ".com" store of that country."""
    found = countries.country_of(site)
    if not found and searched and LOCAL_COM.get(site) == searched:
        return searched
    return found


_DOMAIN_WORD = re.compile(r'(?<![\w.-])([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+)(?![\w-])')
# Google's own wrappers around a store's address.
_REDIRECT_PARAMS = ('url', 'adurl', 'q', 'u')
_CHEAP = re.compile(r'\b(barat[oa]s?|economic[oa]s?|mas barat[oa]|menor precio|mejor precio|mais barat[oa]|'
                    r'menor preco|melhor preco|en oferta|em promocao)\b')
_TRAILING = re.compile(r'\s*\b(ahora|agora|now)\b\s*$', re.I)
# A page that puts something in a cart or pays is never the first page opened.
_NOT_A_PRODUCT = re.compile(r'/(cart|carrito|carrinho|checkout|bag|basket|add|login|account)(/|$)', re.I)


def _product_address(url, site):
    return bool(url) and not guard.address_refusal(url, site) and not _NOT_A_PRODUCT.search(urlsplit(url).path) \
        and urlsplit(url).path not in ('', '/')


class OffersRefused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def available():
    return bool(conf.get('AGENT_OFFERS_ENABLED') and conf.serper_api_key())


def language(country):
    return 'pt-br' if country == 'BR' else 'es'


def cheap(text):
    return bool(_CHEAP.search(guard.fold(text)))


# ── Which store an offer is at ──

def _unwrapped(link):
    """The store's own address inside one of Google's redirects, or the link itself."""
    link = str(link or '').strip()
    host = sites.host_of(link)
    if not host:
        return ''
    if not re.search(r'(^|\.)google\.[a-z.]+$', host):
        return link
    for name, value in parse_qsl(urlsplit(link).query):
        if name in _REDIRECT_PARAMS and value.startswith('https://'):
            inner = sites.host_of(value)
            if inner and not re.search(r'(^|\.)google\.[a-z.]+$', inner):
                return value
    return ''


def _named_store(source, country):
    """The store Google's name for the seller is, in the search's country, or None."""
    # "eBay - a seller", "Amazon.com.br - Seller": the store is what comes before the seller.
    source = str(source or '').split(' - ')[0]
    folded = guard.fold(source)
    found = stores.named([source])
    if len(found) > 1:
        found = {site for site in found if countries.country_of(site) == country}
    if len(found) == 1:
        return found.pop()
    for word in _DOMAIN_WORD.findall(folded):
        site = sites.store(word)
        if site and not stores.imitates(site):
            return site
    plain = re.sub(r'[^a-z0-9 ]', ' ', folded)
    plain = ' '.join(plain.split())
    for name, site in _SOURCES.items():
        if re.search(rf'(?<!\w){re.escape(name)}(?!\w)', plain):
            return site
    return None


def store_of(item, country):
    """(store, the product's own page or '') for one result, or (None, '') when its store cannot be told."""
    page = _unwrapped(item.get('productLink')) or _unwrapped(item.get('link'))
    if page:
        site = sites.store(page)
        if site and not stores.imitates(site):
            return site, page if _product_address(page, site) else ''
    site = _named_store(str(item.get('source') or ''), country)
    return (site, '') if site else (None, '')


# ── How it would be paid ──

def pay_label(site, meta=None, searched=''):
    """(code, words): whether Confío can pay this store, by its country's rail (countries.rail)."""
    rail = countries.rail(country_of(site, searched))
    if rail is None:
        return 'none', 'Confío aún no paga esta tienda'
    if rail.country == 'VE':
        return 'reference', 'Confío la paga por Pago Móvil si la tienda solo pide la referencia'
    if rail.kind == 'manual':
        return 'manual', 'La pagas tú desde tu banco con los datos de la tienda'
    if rail.country == 'BO':
        try:
            if rail.manual(meta):
                return 'manual', 'La pagas tú con el QR de la tienda'
        except Exception:  # noqa: BLE001 - unknown is the person paying it
            return 'manual', 'La pagas tú con el QR de la tienda'
    return 'confio', 'Confío la paga'


# ── Ranking ──

def _price(text, country):
    from .operate import unit_price
    return unit_price(_TRAILING.sub('', str(text or '')), country)


def rank(items, country, *, cheapest=False, meta=None, limit=None):
    """The best few offers, one per store: Google's order, or the cheapest first when the person asked so."""
    limit = limit or conf.get('AGENT_OFFERS_MAX')
    found, seen = [], {}
    for position, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        title = guard.clean(item.get('title'), 140)
        price = _TRAILING.sub('', guard.clean(item.get('price'), 40))
        if not title or not price:
            continue
        site, page = store_of(item, country)
        if site is None:
            continue
        value = _price(price, country)
        offer = {'title': title, 'price': price, 'site': site, 'href': page,
                 'store': guard.clean(item.get('source'), 60) or site,
                 'image': str(item.get('imageUrl') or '') if str(item.get('imageUrl') or '').startswith('https://')
                 else '',
                 'rating': guard.clean(item.get('rating'), 6) if item.get('rating') not in (None, '') else '',
                 'reviews': guard.clean(item.get('ratingCount'), 12) if item.get('ratingCount') not in (None, '')
                 else '',
                 '_order': (value is None, value or 0, position) if cheapest else (position,)}
        earlier = seen.get(site)
        if earlier is not None:
            if offer['_order'] < earlier['_order']:
                found[found.index(earlier)] = offer
                seen[site] = offer
            continue
        seen[site] = offer
        found.append(offer)
    found.sort(key=lambda one: one['_order'])
    picked = found[:limit]
    for offer in picked:
        offer.pop('_order')
        offer['pay'], offer['pay_text'] = pay_label(offer['site'], meta, country)
    return picked


# ── Calling Serper: cached, counted, and a few per person per hour ──

def _post(url, body, kind):
    key = conf.serper_api_key()
    if not key:
        raise OffersRefused('unavailable', 'La búsqueda en tiendas no está disponible ahora.')
    _count(kind)
    try:
        response = requests.post(url, headers={'X-API-KEY': key, 'Content-Type': 'application/json'}, json=body,
                                 timeout=conf.get('AGENT_OFFERS_TIMEOUT_SECONDS'))
    except requests.RequestException as exc:
        logger.warning('agent offers: Serper %s failed: %s', kind, type(exc).__name__)
        raise OffersRefused('unavailable', 'No pude buscar en tiendas ahora.') from None
    if response.status_code >= 400:
        logger.warning('agent offers: Serper %s answered %s', kind, response.status_code)
        raise OffersRefused('unavailable', 'No pude buscar en tiendas ahora.')
    try:
        data = response.json()
    except ValueError:
        raise OffersRefused('unavailable', 'No pude buscar en tiendas ahora.') from None
    return data if isinstance(data, dict) else {}


def _count(kind):
    """For ops: every paid call, counted per day and logged."""
    key = f'{TAG}:calls:{timezone.now():%Y-%m-%d}'
    try:
        cache.add(key, 0, 2 * 86400)
        total = cache.incr(key)
    except Exception:  # noqa: BLE001 - a counter never stops a search
        total = None
    logger.info('agent offers: Serper %s call (%s today)', kind, total)


def _allow(user):
    """At most AGENT_OFFERS_PER_HOUR searches per person in the current hour."""
    key = f'{TAG}:hour:{user.pk}:{timezone.now():%Y%m%d%H}'
    try:
        cache.add(key, 0, 3600)
        return cache.incr(key) <= conf.get('AGENT_OFFERS_PER_HOUR')
    except Exception:  # noqa: BLE001 - an unreadable counter is no search: never an unguarded one
        return False


def _query_key(query, country):
    digest = hashlib.sha256(f'{country}|{guard.fold(query)}'.encode()).hexdigest()[:32]
    return f'{TAG}:q:{digest}'


def search(user, query, country, *, meta=None):
    """The best offers across stores for `query` in `country`, or OffersRefused."""
    from assistant.market import clean_web_query
    query = clean_web_query(query)
    country = str(country or '').upper()
    if not query:
        raise OffersRefused('query', 'Pídele que diga en pocas palabras qué producto busca.')
    if not re.fullmatch(r'[A-Z]{2}', country):
        raise OffersRefused('country', 'Pregúntale en qué país quiere comprarlo.')
    key = _query_key(query, country)
    items = cache.get(key)
    if items is None:
        if not _allow(user):
            raise OffersRefused('limit', 'Ya busqué en tiendas varias veces en esta hora. Pídele que espere un '
                                         'poco o que diga en qué tienda lo busco.')
        data = _post(SHOPPING_URL, {'q': query, 'gl': country.lower(), 'hl': language(country), 'num': 20},
                     'shopping')
        items = [item for item in (data.get('shopping') or []) if isinstance(item, dict)][:40]
        cache.set(key, items, conf.get('AGENT_OFFERS_CACHE_SECONDS'))
    return rank(items, country, cheapest=cheap(query), meta=meta)


def _words(text):
    return {word for word in re.sub(r'[^a-z0-9 ]', ' ', guard.fold(text)).split() if len(word) >= 3}


def product_page(offer, country):
    """The product's own page at its store, found by one site search, or '' (then the agent searches the
    store for it). Only the store's own address, and only a result whose title is mostly the offer's."""
    site = offer.get('site') or ''
    title = offer.get('title') or ''
    if not site or not title:
        return ''
    try:
        data = _post(SEARCH_URL, {'q': f'site:{site} {title}'[:200], 'gl': country.lower(),
                                  'hl': language(country), 'num': 5}, 'search')
    except OffersRefused:
        return ''
    mine = _words(title)
    for result in (data.get('organic') or [])[:5]:
        if not isinstance(result, dict):
            continue
        link = str(result.get('link') or '')
        if not sites.within(link, site) or not _product_address(link, site):
            continue
        theirs = _words(result.get('title'))
        if mine and len(mine & theirs) * 5 >= len(mine) * 3:
            return link
    return ''


# ── The card in the chat ──

def body_of(offers):
    """The note's words: what an app without the card still shows."""
    lines = ['Encontré esto en varias tiendas. Elige una con «Comprar aquí» y la compro ahí:']
    for number, offer in enumerate(offers, 1):
        lines.append(f"{number}. {guard.clean(offer['title'], 70)}: {offer['price']} en {offer['store']} "
                     f"({offer['pay_text']}).")
    return '\n'.join(lines)


def post(user, query, country, offers):
    """The offers as a system note in the person's chat. Returns its id, or None."""
    from assistant.service import post_system_note
    from inbox.models import SupportMessage
    offers_id = str(uuid.uuid4())
    message, created = post_system_note(user, body_of(offers), f'{TAG}:{offers_id}',
                                        actions=[{**ACTION, 'target': offers_id}])
    if message is None:
        return None
    SupportMessage.objects.filter(pk=message.pk).update(metadata={
        **(message.metadata or {}),
        TAG: {'query': query, 'country': country, 'offers': offers, 'picked': None,
              'at': timezone.now().isoformat()}})
    return offers_id


def _message(user, offers_id):
    from inbox.models import SupportMessage
    try:
        offers_id = str(uuid.UUID(str(offers_id)))
    except ValueError:
        return None
    return SupportMessage.objects.filter(conversation__user=user, metadata__notice=f'{TAG}:{offers_id}').first()


def load(user, offers_id):
    """The search a card shows ({query, country, offers, picked}), or None."""
    message = _message(user, offers_id)
    found = (message.metadata or {}).get(TAG) if message is not None else None
    return found if isinstance(found, dict) else None


KEEP = timedelta(days=7)


def buy(account, user, offers_id, index, meta=None):
    """The person tapped "Comprar aquí": the ordinary purchase starts at that offer's store."""
    from . import service
    message = _message(user, offers_id)
    found = (message.metadata or {}).get(TAG) if message is not None else None
    if not isinstance(found, dict):
        raise service.TaskRefused('not_found')
    try:
        if found.get('at') and timezone.now() - datetime.fromisoformat(found['at']) > KEEP:
            raise service.TaskRefused('not_open')
    except (TypeError, ValueError):
        raise service.TaskRefused('not_open') from None
    offers = found.get('offers') or []
    try:
        index = int(index)
        offer = offers[index] if index >= 0 else None
    except (IndexError, TypeError, ValueError):
        offer = None
    if not isinstance(offer, dict) or not offer.get('site') or not offer.get('title'):
        raise service.TaskRefused('not_found')
    from inbox.models import SupportMessage
    page = offer.get('href') or ''
    if not page and not offer.get('searched'):
        # Looked up once: the product's own page, or the store's search when none is found.
        page = product_page(offer, found.get('country') or '')
        offer = {**offer, 'href': page, 'searched': True}
        found = {**found, 'offers': [offer if number == index else one for number, one in enumerate(offers)]}
        SupportMessage.objects.filter(pk=message.pk).update(metadata={**message.metadata, TAG: found})
    task = service.start(account, user, goal=offer['title'], site=offer['site'], meta=meta, first_page=page,
                         chosen=offer['title'], country=country_of(offer['site'], found.get('country') or ''))
    SupportMessage.objects.filter(pk=message.pk).update(metadata={**message.metadata, TAG: {**found, 'picked': index}})
    return task
