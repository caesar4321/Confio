"""A stock or ETF bought or sold from a card in the chat.

The assistant only leaves the card: `{'type': 'trade', 'ticker': ...,
'target': 'buy:20.00' | 'sell:20.00' | 'sell:all', 'label': ...}`. The phone
shows the price and the fee, and the person approves there; the trade then
runs through the same code as the stock screens (a binding quote, the
wallet's own signature, the sponsored batch), with every server gate those
have.

What the card may carry is read from the person's own typed words, never
from the model: the asset they named next to what they asked, the dollars
they wrote as dollars (or that they sell all of it), and the verb. Anything
unclear is refused and the assistant asks.

A card is one trade. The phone does not invent the request it signs: it
asks for it here (`claim`), and while one request of a card is out, or one
of its batches is on record, no other is handed out. A card lasts a day.
"""
import logging
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings

from . import market
from .prompts import conversation_home

logger = logging.getLogger(__name__)

TOOL = 'propose_stock_trade'
MIN_BUY_USD = Decimal('1.01')    # as BuyStockScreen: above Ondo's minimum after the fee
MIN_SELL_USD = Decimal('1')
CARD_HOURS = 24
# Longer than the 10 minutes a signed request stays valid (sponsored7702):
# after it, a request that left no batch on record can no longer execute.
CLAIM_SECONDS = 11 * 60
# Beside a trade card the reply may never say the trade happened.
DONE_CLAIM = re.compile(
    r'\b(ya\s+(se\s+|lo\s+|la\s+|las\s+|está\s+|quedó\s+|fue\s+)?(compr|vend)'
    r'|(compra|venta)\s+(fue\s+|está\s+|quedó\s+)?(realizad|hech|completad|exitos|confirmad|list)'
    r'|he\s+(comprado|vendido)|compré|vendí|se\s+(compró|vendió))', re.IGNORECASE)
PREPARED_REPLY = 'Te dejé la tarjeta: revisa el precio y la comisión y toca Aprobar ahí. Todavía no se hizo nada.'

_BUY_VERBS = ('compr', 'inviert', 'invert', 'invier', 'adquir')
_BUY = _BUY_VERBS + ('quiero', 'quisiera')
_SELL = ('vend', 'liquid')
_DOLLARS = {'dolar', 'dolares', 'usd', 'us$', 'dolaritos', 'verdes'}
# "5 acciones" is a count of shares: the card trades a dollar amount.
_SHARE_WORDS = {'accion', 'acciones', 'titulo', 'titulos', 'unidad', 'unidades', 'token', 'tokens', 'papeles'}
# Tickers that are everyday words: they name the asset only as the person
# typed them in capitals ("compra 20 de DE").
_WORD_TICKERS = {'de', 'so', 'on', 'be', 'now', 'uso', 'app', 'net', 'low', 'open', 'cost', 'cat', 'coin', 'shop',
                 'spot', 'snap', 'meta', 'all', 'key', 'well', 'fast', 'mas', 'dia', 'sol', 'mar', 'luz', 'eso', 'esa'}
_EDGE = '.,;:!?¡¿()"\''
# "vende todo", "vender todas mis acciones de Apple", "liquida todo lo que tengo".
_SELL_ALL = re.compile(r'\b(?:vend\w*|liquid\w*)\b[^.!·\n]{0,40}?\b(tod[oa]s?|complet[oa]|enter[oa])\b')
_NOT_ALL = re.compile(r'\b(no|ni|menos|excepto|salvo|sin)\s+(\w+\s+)?tod[oa]s?\b'
                      r'|\b(sobre|por|ante|con|eso es|es)\s+todo\b|\btodo\s+(bien|ok|listo|claro)\b')

SPEC = {
    'type': 'function',
    'name': TOOL,
    'description': ('Deja en la conversación una tarjeta para comprar o vender una acción o ETF aquí mismo: la '
                    'persona ve ahí el precio y la comisión y aprueba en la tarjeta. Úsalo cuando ella pidió en '
                    'su mensaje comprar o vender, y escribió qué acción y cuántos dólares (o que vende todo lo '
                    'que tiene de esa acción). Nunca elijas tú la acción ni el monto, y si falta uno de los dos, '
                    'pregúntalo. Se opera por monto en dólares, no por número de acciones. La compra sale de su '
                    'Confío Dollar+ y la venta vuelve a su Confío Dollar+.'),
    'parameters': {
        'type': 'object',
        'properties': {
            'side': {'type': 'string', 'enum': ['buy', 'sell']},
            'asset': {'type': 'string', 'description': 'El ticker o el nombre que la persona escribió.'},
            'amount_usd': {'type': ['number', 'null'], 'description': 'Dólares, como los escribió. null si vende todo.'},
            'sell_all': {'type': 'boolean', 'description': 'Solo en una venta: vende todo lo que tiene de esa acción.'},
        },
        'required': ['side', 'asset', 'amount_usd', 'sell_all'],
        'additionalProperties': False,
    },
    'strict': True,
}


def request_prefix(message_id) -> str:
    """How every request id of one card begins."""
    return f'chat-trade-{int(message_id):010d}'


def offered(belt) -> bool:
    """The card can be drawn and used: the chat is Inicio on a build that
    knows it, the person's own personal account, stocks open to them, and
    trading wired on this server."""
    viewer = belt.viewer
    if not conversation_home(viewer.request_meta) or not belt.payments_ready():
        return False
    try:
        from cusd_plus.schema import _stock_execution_ready

        from .engine import _ondo_allowed
        return _ondo_allowed(viewer) is True and _stock_execution_ready()
    except Exception:  # noqa: BLE001 - no tool is always safe
        logger.warning('Confio Assistant: stock trading check failed', exc_info=True)
        return False


def _refuse(why):
    return {'ok': False, '_denied': True, 'motivo': why}


def _fold(text):
    from payment_accounts.payment_intents import _fold as fold
    return fold(text)


def _requests(texts):
    """The messages that can ask for a trade: short ones the person typed
    as a request. Never a question ("¿cuánto serían 100 de Apple?"), never
    a long pasted text."""
    from payment_accounts.payment_intents import MAX_REQUEST_CHARS

    return [text for text in texts
            if '?' not in text and '¿' not in text and len(' '.join(text.split())) <= MAX_REQUEST_CHARS]


def _tokens(text):
    """(folded word, the word as typed) for each word of a message."""
    return [(_fold(raw).strip(_EDGE), raw.strip(_EDGE)) for raw in text.split()]


def _is_number(word):
    number = word.removeprefix('us$').removeprefix('usd').removeprefix('$').removesuffix('usd').removesuffix('$')
    return bool(number) and number[0].isdigit() and all(ch.isdigit() or ch in '.,' for ch in number)


def _probes(ticker, name):
    """The words that name this asset: its ticker, the brand it is known by,
    and the first word of its name when no other listed asset starts with
    it ("Apple" names one; "iShares" names many)."""
    words = {_fold(ticker)}
    words |= {brand for brand, brand_ticker in market.BRAND_TICKERS.items() if brand_ticker == ticker}
    first = re.findall(r'[a-z0-9&]+', _fold(name or ''))
    if first and len(first[0]) >= 4:
        try:
            from cusd_plus import gm_api
            from cusd_plus.schema import _gm_listing
            listings = [listing for listing in map(_gm_listing, gm_api.all_market()) if listing]
            sharing = sum(1 for _symbol, _ticker, other in listings
                          if (re.findall(r'[a-z0-9&]+', _fold(other or '')) or [''])[0] == first[0])
        except Exception:  # noqa: BLE001 - unknown: the name alone does not count
            logger.warning('Confio Assistant: listings unavailable for a trade card', exc_info=True)
            sharing = 2
        if sharing <= 1:
            words.add(first[0])
    return words


def _asset_at(tokens, ticker, probes):
    """Where in this message the person named the asset, as part of what
    they asked: right after the verb, the amount, "acciones" or "de"/"en"
    following one of those. A word that happens to be a ticker elsewhere in
    the sentence ("mi meta es ahorrar") is not it. -1 = not named."""
    folded_ticker = _fold(ticker)
    for index, (word, typed) in enumerate(tokens):
        if word not in probes:
            continue
        before = [w for w, _typed in tokens[max(0, index - 4):index]]

        def cue(w):
            return w.startswith(_BUY_VERBS + _SELL) or _is_number(w) or w in _SHARE_WORDS or w in _DOLLARS

        if word == folded_ticker and typed != ticker and (len(word) <= 2 or word in _WORD_TICKERS):
            # An everyday word ("de", "meta", "app"). One or two letters: only
            # in the ticker's own capitals. Longer: only right where an asset
            # goes ("compra meta", "20 de meta"), never "compra 20 para mi meta".
            direct = before[-1:] and before[-1].startswith(_BUY_VERBS + _SELL)
            tied = before[-1:] and before[-1] in ('de', 'en') and before[-2:-1] and cue(before[-2])
            if len(word) <= 2 or not (direct or tied):
                continue
            return index
        if any(cue(w) for w in before):
            return index
    return -1


def _dollars_at(tokens, amount, asset_index):
    """The person wrote this amount as dollars to trade: with the dollar
    word or sign ("20 dólares", "US$20"), or bare and tied to the asset
    ("20 de Apple", "50 en Tesla"). Not a price level, a percentage, an
    age, another currency, a count of shares, or a number they denied."""
    from payment_accounts.payment_intents import _amount_values

    for index, (word, _typed) in enumerate(tokens):
        if not _is_number(word):
            continue
        signed = word.startswith(('us$', 'usd', '$')) or word.endswith(('usd', '$'))
        number = word.removeprefix('us$').removeprefix('usd').removeprefix('$').removesuffix('usd').removesuffix('$')
        try:
            values = set(_amount_values(number))
            if '.' in number and ',' in number:
                # Both marks: the last one is the decimal ("1.500,50").
                mark = max(number.rfind('.'), number.rfind(','))
                values = {Decimal(number[:mark].replace('.', '').replace(',', '') + '.' + number[mark + 1:])}
        except ArithmeticError:
            continue
        if amount not in values:
            continue
        before = [w for w, _t in tokens[max(0, index - 3):index]]
        after = [w for w, _t in tokens[index + 1:index + 3]]
        if set(before) & {'no', 'ni', 'nunca', 'sin'} or before[-2:] == ['vez', 'de']:
            continue
        if after[:1] and after[0] in _SHARE_WORDS:
            continue
        if signed or (after[:1] and after[0] in _DOLLARS):
            return True
        # Bare: "<amount> de|en <asset>".
        if after[:1] and after[0] in ('de', 'en') and asset_index in (index + 2, index + 3):
            return True
    return False


def _counts_shares(tokens, amount):
    """They wrote this number as a count of shares ("5 acciones", "1.000 acciones")."""
    from payment_accounts.payment_intents import _amount_values

    for index, (word, _typed) in enumerate(tokens[:-1]):
        if not _is_number(word) or tokens[index + 1][0] not in _SHARE_WORDS:
            continue
        try:
            if amount in _amount_values(word):
                return True
        except ArithmeticError:
            continue
    return False


def _short(ticker, name):
    return name if name and len(name) <= 18 else ticker


def _money(amount):
    """US$20 or US$20,50: as the app writes dollars in Spanish."""
    text = f'{amount:.2f}'.replace('.', ',')
    return 'US$' + (text[:-3] if text.endswith(',00') else text)


def propose(belt, side, asset, amount_usd=None, sell_all=False):
    result, viewer = belt.result, belt.viewer
    if any(action.get('type') == 'trade' for action in result.actions):
        return _refuse('Una tarjeta de compra o venta por respuesta.')
    if result.payment_intent is not None or result.rule_proposal is not None:
        return _refuse('Ya hay una propuesta en esta respuesta.')
    if not belt.payment_texts:
        # A call or a tapped suggestion: nothing the person typed to read from.
        return _refuse('Para comprar o vender desde el chat, la persona debe escribir en un mensaje qué acción y '
                       'cuántos dólares.')
    if belt.saw_web:
        return _refuse('No preparo una compra o venta en el mismo mensaje en que busqué en internet: que lo pida en '
                       'un mensaje aparte.')
    if side not in ('buy', 'sell'):
        return _refuse('Operación desconocida.')
    texts = _requests(belt.payment_texts)
    if not texts:
        return _refuse('Eso fue una pregunta, no un pedido: respóndela. Si quiere comprar o vender, que lo pida '
                       'escribiendo qué acción y cuántos dólares.')
    found = market.listed_asset(asset)
    if found is None:
        return _refuse('No encontré esa acción o ETF entre las que muestra Confío.')
    ticker, name = found
    probes = _probes(ticker, name)
    # One message must hold the whole request: the asset, and the amount tied to it.
    named = [(tokens, at) for tokens in map(_tokens, texts) for at in [_asset_at(tokens, ticker, probes)] if at >= 0]
    if not named:
        return _refuse(f'La persona no nombró {name or ticker} en lo que pidió: pregúntale cuál quiere, no la '
                       'elijas tú.')
    said = ' · '.join(_fold(text) for text in texts)
    stems = set(re.findall(r'[a-z]+', said))
    sells = any(word.startswith(_SELL) for word in stems)
    buys = any(word.startswith(_BUY) for word in stems)
    if side == 'sell' and not sells:
        return _refuse('La persona no escribió que quiere vender: pregúntale qué quiere hacer.')
    if side == 'buy' and sells and not any(word.startswith(_BUY_VERBS) for word in stems):
        return _refuse('La persona habló de vender, no de comprar: pregúntale qué quiere hacer.')
    if side == 'buy' and not buys:
        return _refuse('La persona no escribió que quiere comprar: pregúntale qué quiere hacer.')
    if side == 'buy':
        from cusd_plus.eligibility import check_stock_buy_eligibility
        if not check_stock_buy_eligibility(viewer.user, viewer.request_meta):
            return _refuse('Esta persona no puede comprar acciones desde su país o su cuenta.')
        sell_all = False

    held = None
    if side == 'sell':
        address = getattr(viewer.account, 'bsc_address', '') or ''
        try:
            from .engine import _holdings
            rows = _holdings(address, limit=None) if address else []
        except Exception:  # noqa: BLE001 - unknown: the phone checks the real balance
            logger.warning('Confio Assistant: holdings unavailable for a trade card', exc_info=True)
            rows = 'desconocido'
        if isinstance(rows, list):
            held = next((row for row in rows if row['ticker'] == ticker), None)
            if held is None:
                return _refuse(f'No tiene {name or ticker}: no hay nada que vender.')

    short = _short(ticker, name)
    if sell_all:
        # In the same message that names the asset, tied to the verb, and not denied.
        whole = [' '.join(word for word, _typed in tokens) for tokens, _at in named]
        if not any(_SELL_ALL.search(text) and not _NOT_ALL.search(text) for text in whole):
            return _refuse('La persona no escribió claramente que vende todo: pregúntale si vende todo o cuántos '
                           'dólares.')
        if any(_is_number(word) for tokens, _at in named for word, _typed in tokens):
            # "vende 10 de Apple, eso es todo": an amount and "todo" together.
            return _refuse('Escribió un número y también "todo": pregúntale si vende todo o ese monto.')
        target, label = 'sell:all', f'Vender todo {short}'
    else:
        try:
            amount = Decimal(str(amount_usd)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            return _refuse('Falta el monto en dólares: pregúntaselo.')
        if any(_counts_shares(tokens, amount) for tokens, _at in named):
            return _refuse('Escribió un número de acciones, no dólares. Aquí se compra y se vende por monto en '
                           'dólares: pregúntale cuántos dólares.')
        if not any(_dollars_at(tokens, amount, at) for tokens, at in named):
            return _refuse('Ese monto no está escrito como dólares junto a la acción en su mensaje: pregúntale '
                           'cuántos dólares, no lo calcules ni lo supongas tú.')
        floor = MIN_BUY_USD if side == 'buy' else MIN_SELL_USD
        if amount < floor:
            return _refuse(f'El mínimo es {_money(floor)}.')
        if amount > Decimal(str(getattr(settings, 'CUSD_PLUS_GM_MAX_TRADE_USD', 100_000))):
            return _refuse('Ese monto supera el máximo por operación.')
        target = f'{side}:{amount:.2f}'
        label = f'{"Comprar" if side == "buy" else "Vender"} {_money(amount)} de {short}'
    result.actions.append({'type': 'trade', 'ticker': ticker, 'target': target, 'label': label})
    out = {'ok': True, 'tarjeta': label, 'activo': f'{name} ({ticker})',
           'nota': ('Todavía no se compró ni se vendió nada: quedó una tarjeta bajo tu respuesta con el precio y la '
                    'comisión. Dile en una línea que la revise y toque Aprobar ahí. No digas que ya está hecho ni '
                    'des tú el precio final: el de la tarjeta es el que vale. Si el mercado está cerrado, la '
                    'tarjeta lo dice.')}
    if held is not None:
        out['tiene'] = held.get('valor_usd')
    return out


# ── the card's one trade ────────────────────────────────────────────────────

def _card(user, message_id):
    """The assistant's own message of this person that carries a trade card, or None."""
    from inbox.models import SupportMessage

    try:
        message = SupportMessage.objects.filter(pk=int(message_id), conversation__user=user).first()
    except (TypeError, ValueError):
        return None
    if message is None or message.sender_type == 'USER':
        return None
    actions = (message.metadata or {}).get('actions') or []
    return message if any(isinstance(a, dict) and a.get('type') == 'trade' for a in actions) else None


def _claim_key(user, prefix):
    return f'assistant:trade-claim:{user.pk}:{prefix}'


def status(user, message_id):
    """Where the card of this message stands: (state, tx hash).
    'none' = it can be approved; 'pending' = a request is out or a batch is
    on its way; 'done'; 'failed' = it reached the chain and did not execute;
    'expired' = the card is more than a day old; 'gone' = no such card."""
    from blockchain.models import SponsoredBatch
    from django.core.cache import cache
    from django.utils import timezone

    message = _card(user, message_id)
    if message is None:
        return 'gone', ''
    prefix = request_prefix(message.pk)
    batches = list(SponsoredBatch.objects.filter(
        user=user, client_request_id__startswith=prefix + '-', kind__in=('stock_buy', 'stock_sell'),
    ).order_by('-id')[:10])
    # One that executed, or may still execute, outranks a later failed try.
    for wanted, said in (('confirmed', 'done'), ('signed', 'pending'), ('sent', 'pending')):
        hit = next((b for b in batches if b.status == wanted), None)
        if hit is not None:
            return said, hit.tx_hash or ''
    if cache.get(_claim_key(user, prefix)):
        return 'pending', ''
    if batches:
        return 'failed', batches[0].tx_hash or ''
    if timezone.now() - message.created_at > timedelta(hours=CARD_HOURS):
        return 'expired', ''
    return 'none', ''


def claim(user, message_id):
    """The one request this card may sign now: (request id, state). No id
    while another is out, once a batch is on record, or after it expired."""
    from django.core.cache import cache

    state, _tx = status(user, message_id)
    if state != 'none':
        return '', state
    prefix = request_prefix(message_id)
    request_id = f'{prefix}-{secrets.token_hex(6)}'
    # Atomic: of two phones (or two open copies of the chat) one gets it.
    if not cache.add(_claim_key(user, prefix), request_id, CLAIM_SECONDS):
        return '', 'pending'
    return request_id, 'none'


def release(user, message_id, request_id):
    """The phone says the request it was given sent nothing: the card can
    be approved again. Kept if a batch of that request is on record."""
    from blockchain.models import SponsoredBatch
    from django.core.cache import cache

    try:
        prefix = request_prefix(message_id)
    except (TypeError, ValueError):
        return status(user, message_id)[0]
    key = _claim_key(user, prefix)
    if (request_id and cache.get(key) == request_id
            and not SponsoredBatch.objects.filter(user=user, client_request_id__startswith=request_id).exists()):
        cache.delete(key)
    return status(user, message_id)[0]
