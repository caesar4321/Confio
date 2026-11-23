"""Where a task may go. No per-store code: only a store's boundary.

A task works inside one store. That boundary is what contains a page that
tries to steer the agent: it cannot carry what it read to another site, and
it cannot reach another store's signed-in profile.

A well-known store is its registered name with everything under it. Any other
store is exactly the host the person wrote (and what is under it), so this
needs no public-suffix list and one shop never contains its neighbour.
"""
import ipaddress
import re
from urllib.parse import unquote, urlsplit

# A thin list of names, not of scripts.
KNOWN = {
    'mercadolivre.com.br': ('mercado livre', 'mercado libre', 'mercadolivre', 'mercadolibre', 'meli'),
    'amazon.com.br': ('amazon',),
    'magazineluiza.com.br': ('magalu', 'magazine luiza'),
    'americanas.com.br': ('americanas',),
    'shopee.com.br': ('shopee',),
    'kabum.com.br': ('kabum',),
    'netshoes.com.br': ('netshoes',),
    'centauro.com.br': ('centauro',),
    'decathlon.com.br': ('decathlon',),
    'lojasrenner.com.br': ('renner',),
    'clickbus.com.br': ('clickbus',),
    'buser.com.br': ('buser',),
    'ifood.com.br': ('ifood',),
    # Mexico (SPEI). The same name in two countries is settled by the person's country (stores.choose).
    'mercadolibre.com.mx': ('mercado libre', 'mercadolibre', 'meli'),
    'amazon.com.mx': ('amazon',),
    'walmart.com.mx': ('walmart',),
    'liverpool.com.mx': ('liverpool',),
}
# Other names of a known store.
ALSO = {'mercadolivre.com.br': ('mercadolivre.com', 'mercadolibre.com'), 'magazineluiza.com.br': ('magalu.com',),
        # Mercado Libre signs in on its .com host in every country.
        'mercadolibre.com.mx': ('mercadolibre.com',)}
# A store's payment house: its checkout pages only, never the wallet.
CHECKOUT_HOUSE = {'mercadolivre.com.br': (
    frozenset({'www.mercadopago.com.br', 'mercadopago.com.br', 'www.mercadopago.com'}),
    re.compile(r'/(checkout|payments/\d+/ticket)(/|$)', re.I))}

_HOST = re.compile(r'(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
_CATEGORY = frozenset(('com net org gov gob edu co mil jus leg art blog ind inf log srv tur eco app dev ac ne or go '
                       'emp ong tec adv sampa').split())
# Many owners under one name: only the full host is a store.
_SHARED = ('myshopify.com', 'lojaintegrada.com.br', 'nuvemshop.com.br', 'lojavirtualnuvem.com.br', 'wixsite.com',
           'vercel.app', 'netlify.app', 'github.io', 'pages.dev', 'workers.dev', 'web.app', 'firebaseapp.com',
           'herokuapp.com', 'blogspot.com', 'myvtex.com', 'vtexcommercestable.com.br', 'wordpress.com', 'tray.com.br', 'yampi.io', 'r2.dev', 'glitch.me', 'cartpanda.com', 'shop.app', 'mercadoshops.com.br', 'onrender.com', 'amazonaws.com', 'cloudfront.net')
# Never driven by an assistant: money accounts, the state, mailboxes, Confío, anything internal.
_NEVER = re.compile(
    r'(^|[.-])(confio|banco|bank|banking|internetbanking|itau|bradesco|santander|nubank|bancointer'
    r'|c6bank|sicredi|sicoob|xpi|btg|btgpactual|binance|bitso|coinbase|paypal|picpay|pagbank|mercadopago'
    r'|bbva|banamex|citibanamex|banorte|hsbc|scotiabank|banregio|bancoppel|bancoazteca|inbursa|banbajio|afirme'
    r'|bancosol|bancounion|bancomercantil|bancofie|bancoganadero|bancobisa|bancoeconomico'
    r'|bancodobrasil|bancosantander|banrisul|revolut|kraken|okx|foxbit|metamask|pagseguro|stripe|google|gmail|googlemail|outlook|hotmail|microsoft|microsoftonline|icloud|yahoo|proton|protonmail)([.-]|$)'
    # Ordinary words too (caixa-de-som, neon-led): only as a whole label.
    r'|(^|\.)(caixa|bb|inter|c6|xp|wise|safra|stone|neon)\.'
    r'|\.(gov|gob|jus|mil|leg)(\.[a-z]{2})?$'
    r'|\.(internal|local|localhost|lan|home|corp|arpa|test|invalid|onion)$'
    r'|(^|\.)(nip\.io|sslip\.io|xip\.io|localtest\.me|lvh\.me|live\.com)$')
_WALLET_PATH = re.compile(
    r'/(money-out|money-transfer|withdraw|transfer|transferir|transferencias?|send-money|saque|emprestimos?|credits?'
    r'|banking)(/|$|\?)', re.I)


def host_of(url):
    """The host of an https URL on the default port, or ''."""
    try:
        text = str(url or '').strip()
        parts = urlsplit(text)
        if parts.scheme.lower() != 'https' or parts.username or parts.password or parts.port not in (None, 443):
            return ''
        if not parts.netloc.isascii() or '\\' in parts.netloc:
            return ''
    except ValueError:
        return ''
    host = (parts.hostname or '').rstrip('.')
    return host if _HOST.fullmatch(host) and 'xn--' not in host else ''


def _under(host, name):
    return host == name or host.endswith('.' + name)


def store(value):
    """The store named by a domain or URL, or None when no task may run there."""
    value = str(value or '').strip()
    if not value or not value.isascii() or any(ch.isspace() for ch in value):
        return None
    value = value.lower()
    host = host_of(value if '://' in value else f'https://{value}')
    if not host:
        return None
    for known in KNOWN:
        if any(_under(host, name) for name in (known, *ALSO.get(known, ()))):
            return known
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if _NEVER.search(host) or re.match(r'(mail|webmail|accounts)\.', host):
        return None
    host = host.removeprefix('www.')
    labels = host.split('.')
    if host in _SHARED or len(labels) < 2:
        return None
    if len(labels) == 2 and (labels[1] == 'br' or (len(labels[1]) == 2 and labels[0] in _CATEGORY)):
        return None  # "com.br", "emp.br": everybody's, not a store
    return host


def within(url, site, house=False):
    """`url` is inside the task's store. `house`: also the checkout pages of
    its payment house, which only the person goes to: the agent never does."""
    host = host_of(url)
    if not host:
        return False
    path = urlsplit(str(url).strip()).path
    for _ in range(4):
        path = unquote(path)
    path = re.sub(r';[^/]*', '', path)  # "/money-out;x" is /money-out
    if '\\' in path:
        return False  # a browser reads "..\\home" as "../home"
    if '/../' in f'{path}/' or _WALLET_PATH.search(path):
        return False
    if site in KNOWN:
        if any(_under(host, name) for name in (site, *ALSO.get(site, ()))):
            return True
        pay = CHECKOUT_HOUSE.get(site) if house else None
        return bool(pay and host in pay[0] and pay[1].match(path))
    if _NEVER.search(host):
        return False
    if any(_under(site, shared) for shared in _SHARED):
        return host == site
    return _under(host, site)
