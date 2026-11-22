"""A stock or ETF bought or sold from a card in the chat.

The assistant only proposes. Code asks "¿Quieres vender toda tu posición en
Tesla (TSLA)?" or "¿Quieres comprar US$20 (dólares) de Apple (AAPL)?", and
the exact yes to that message (confirm.py) leaves the card:
`{'type': 'trade', 'ticker': ..., 'target': 'buy:20.00' | 'sell:20.00' |
'sell:all', 'label': ...}`. The phone shows the price and the fee, and the
person approves there; the trade then runs through the same code as the stock
screens (a binding quote, the wallet's own signature, the sponsored batch),
with every server gate those have.

Consent is never read out of a sentence: a word list took "la mitad", "no"
and "¿es todo?" for "sell all" (2026-11-22). The proposal is only kept
honest: the asset is one the person named, and an amount one they wrote as
dollars (payment_accounts/dollars.py). What was asked is checked again when
they say yes.

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

SPEC = {
    'type': 'function',
    'name': TOOL,
    'description': ('Para comprar o vender una acción o ETF aquí mismo. Llámala en cuanto sepas las tres cosas por '
                    'lo que dijo la persona, aunque sea en varios mensajes: comprar o vender, qué acción y cuántos '
                    'dólares (o que vende todo lo que tiene de esa acción). El servidor le hace la pregunta exacta '
                    'y, si responde que sí, deja la tarjeta con el precio para aprobar: no preguntes tú si confirma, '
                    'llama la herramienta. Nunca elijas tú la acción ni el monto, ni conviertas de otra moneda; si '
                    'falta uno, pregunta solo eso. Busca en la lista de Confío, que incluye acciones tokenizadas de '
                    'empresas privadas (Anthropic, SpaceX…): con los tres datos úsala en vez de `navigate`. Se opera '
                    'por monto en dólares, no por número de acciones. La compra sale de su Confío Dollar+ y la venta '
                    'vuelve a su Confío Dollar+.'),
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
    return {'ok': False, '_denied': True, 'motivo': why,
            'como_decirlo': ('No menciones herramientas ni esta nota, y no le pidas que copie una frase. Pregúntale '
                             'solo lo que falta; cuando lo diga, vuelve a llamar la herramienta.')}


def _fold(text):
    from payment_accounts.payment_intents import _fold as fold
    return fold(text)


def _requests(texts):
    """The messages that can ask for something: short ones the person typed
    as a request. Never a question, never a long pasted text. (topup_limits)"""
    from payment_accounts.payment_intents import MAX_REQUEST_CHARS

    return [text for text in texts
            if '?' not in text and '¿' not in text and len(' '.join(text.split())) <= MAX_REQUEST_CHARS]


# Words many listed names share: alone they name no asset.
_GENERIC = frozenset("""ishares vanguard invesco proshares spdr direxion trust fund shares class index holdings group
corp corporation company incorporated limited global united states american capital energy financial technologies
technology international industries systems select sector market total short ultra bond treasury first national
general digital resources partners series innovator equity income growth value dividend core""".split())


# What people call a few of them.
_CALLED = {'SPY': ('s&p', 's&p 500', 'sp500', 'sp 500'), 'QQQ': ('nasdaq',), 'GLD': ('oro', 'gold'),
           'IAU': ('oro', 'gold'), 'MMM': ('3m',), 'MCD': ('mcdonalds', "mcdonald's"), 'KO': ('cocacola', 'coca cola'),
           'TSM': ('tsmc',), 'JNJ': ('j&j',)}


def _named(texts, ticker, name):
    """The person named this asset: its ticker, its brand, or a word of its
    name that is its own. A question is asked before any card, so this only
    keeps the assistant from choosing the asset for them."""
    folded = _fold(ticker)
    brands = {brand for brand, brand_ticker in market.BRAND_TICKERS.items() if brand_ticker == ticker}
    brands |= set(_CALLED.get(ticker, ()))
    full = re.findall(r'[a-z0-9&]+', _fold(name or ''))
    if len(full) >= 2 and not (full[0] in _GENERIC and full[1] in _GENERIC and len(full) > 2):
        brands.add(' '.join(full[:2]))      # "Capital One", "General Electric"
    own = {word for word in re.findall(r'[a-z0-9&]+', _fold(name or '')) if len(word) >= 4 and word not in _GENERIC}
    for text in texts:
        said = _fold(text)
        words = set(re.findall(r'[a-z0-9&]+', said))
        if any(re.search(rf'(?<![\w]){re.escape(brand)}(?![\w])', said) for brand in brands if brand) or words & own:
            return True
        if (folded in words or (not folded.isalnum() and re.search(rf'(?<![\w]){re.escape(folded)}(?![\w])', said))
                ) and (len(folded) > 2 or re.search(rf'(?<![\w]){re.escape(ticker)}(?![\w])', text)):
            return True                 # one or two letters: only as the ticker's own capitals
    return False


def money(amount, lang='es'):
    """US$20 or US$20,50 (US$20.50 in English)."""
    text = f'{Decimal(amount):.2f}'
    text = text[:-3] if text.endswith('.00') else text
    return 'US$' + (text if lang == 'en' else text.replace('.', ','))


def question(side, ticker, name, amount, sell_all, lang):
    """The question code writes: the ticker and the dollars are always in it."""
    asset = f'{name} ({ticker})' if name and name != ticker else ticker
    if sell_all:
        return {'es': f'¿Quieres vender toda tu posición en {asset}?',
                'pt': f'Você quer vender toda a sua posição em {asset}?',
                'en': f'Do you want to sell your whole position in {asset}?'}[lang]
    verbs = {'es': ('comprar', 'vender'), 'pt': ('comprar', 'vender'), 'en': ('buy', 'sell')}[lang]
    verb, dollars = verbs[side == 'sell'], money(amount, lang)
    return {'es': f'¿Quieres {verb} {dollars} (dólares) de {asset}?',
            'pt': f'Você quer {verb} {dollars} (dólares) de {asset}?',
            'en': f'Do you want to {verb} {dollars} (US dollars) of {asset}?'}[lang]


def _held(viewer):
    """What they hold, or 'desconocido' when it can't be read."""
    address = getattr(viewer.account, 'bsc_address', '') or ''
    try:
        from .engine import _holdings
        rows = _holdings(address, limit=None) if address else []
    except Exception:  # noqa: BLE001 - unknown: the phone checks the real balance
        logger.warning('Confio Assistant: holdings unavailable for a trade card', exc_info=True)
        return 'desconocido'
    return rows if isinstance(rows, list) else 'desconocido'


def _cannot(belt, side, ticker, name, amount, sell_all, rows):
    """Why this trade can't be offered; '' when it can. Run when asked and again on the yes."""
    if side == 'buy':
        from cusd_plus.eligibility import check_stock_buy_eligibility
        if not check_stock_buy_eligibility(belt.viewer.user, belt.viewer.request_meta):
            return 'Esta persona no puede comprar acciones desde su país o su cuenta.'
    elif isinstance(rows, list) and not any(row['ticker'] == ticker for row in rows):
        return f'No tiene {name or ticker}: no hay nada que vender.'
    if sell_all:
        return ''
    floor = MIN_BUY_USD if side == 'buy' else MIN_SELL_USD
    if amount < floor:
        return f'El mínimo es {money(floor)}.'
    if amount > Decimal(str(getattr(settings, 'CUSD_PLUS_GM_MAX_TRADE_USD', 100_000))):
        return 'Ese monto supera el máximo por operación.'
    return ''


def propose(belt, side, asset, amount_usd=None, sell_all=False):
    """Check the proposal and have code ask it. No card here: see confirmed()."""
    from . import confirm

    if confirm.busy(belt.result):
        return _refuse('Ya hay una pregunta o una propuesta en esta respuesta: una cosa por respuesta.')
    texts = confirm.recent_texts(belt)
    if not texts:
        # A call or a tapped suggestion: nothing the person typed to read from.
        return _refuse('Para comprar o vender desde el chat, la persona debe escribir en un mensaje qué acción y '
                       'cuántos dólares.')
    if belt.saw_web:
        return _refuse('No preparo una compra o venta en el mismo mensaje en que busqué en internet: que lo pida en '
                       'un mensaje aparte.')
    from payment_accounts.payment_intents import MAX_REQUEST_CHARS
    if len(' '.join(texts[0].split())) > MAX_REQUEST_CHARS:
        return _refuse('Eso es un texto largo, no un pedido: respóndelo. Si quiere comprar o vender, que lo diga en '
                       'una frase.')
    texts = [text for text in texts if len(' '.join(text.split())) <= MAX_REQUEST_CHARS]
    if side not in ('buy', 'sell'):
        return _refuse('Operación desconocida.')
    found = market.listed_asset(asset)
    if found is None:
        # "S&P 500" is SPY: only a name that one of them goes by ("oro" is two funds: ask).
        tickers = [ticker for ticker, names in _CALLED.items() if _fold(str(asset or '')).strip() in names]
        found = market.listed_asset(tickers[0]) if len(tickers) == 1 else None
    if found is None:
        return _refuse('No encontré esa acción o ETF entre las que muestra Confío.')
    ticker, name = found
    sell_all = bool(sell_all) and side == 'sell'

    rows = _held(belt.viewer) if side == 'sell' else None
    only_one = isinstance(rows, list) and len(rows) == 1 and rows[0]['ticker'] == ticker
    if not only_one and not _named(texts, ticker, name):
        return _refuse(f'La persona no nombró {name or ticker}: pregúntale cuál quiere, no la elijas tú.')

    amount = None
    if not sell_all:
        if amount_usd is None:
            return _refuse('Falta el monto en dólares: pregúntaselo.')
        try:
            amount = Decimal(str(amount_usd)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            return _refuse('Falta el monto en dólares: pregúntaselo.')
        from payment_accounts.dollars import said_dollars
        # A question may name the asset; how much is never read out of one ("¿cuánto serían 100 de Apple?").
        if not said_dollars(_requests(confirm.requests(texts)), amount, around=confirm.all_said(belt)):
            return _refuse('Ese monto no está escrito como dólares (puede ser otra moneda o un número de acciones): '
                           'pregúntale cuántos dólares, por ejemplo "20 dólares". No lo calcules ni lo conviertas.')
    why = _cannot(belt, side, ticker, name, amount, sell_all, rows)
    if why:
        return _refuse(why)
    lang = confirm.language(texts)
    return confirm.ask(belt.result, 'trade', question(side, ticker, name, amount, sell_all, lang),
                       {'side': side, 'ticker': ticker, 'sell_all': sell_all,
                        'amount': f'{amount:.2f}' if amount is not None else None}, lang)


def confirmed(belt, data, lang='es'):
    """The yes to propose()'s question: every gate again, then the card of exactly that."""
    side, ticker, sell_all = data.get('side'), data.get('ticker'), bool(data.get('sell_all'))
    found = market.listed_asset(ticker)
    if side not in ('buy', 'sell') or found is None or found[0] != ticker or not offered(belt):
        return False, 'No puedo dejarte esa tarjeta ahora. Puedes hacerlo en Invertir.', {}
    name = found[1]
    amount = None if sell_all else Decimal(data['amount'])
    why = _cannot(belt, side, ticker, name, amount, sell_all, _held(belt.viewer) if side == 'sell' else None)
    if why:
        return False, why.replace('Esta persona no puede', 'No puedes').replace(
            'desde su país o su cuenta', 'desde tu país o tu cuenta').replace('No tiene ', 'No tienes '), {}
    short = name if name and len(name) <= 18 else ticker
    if sell_all:
        target, label = 'sell:all', f'Vender todo {short}'
    else:
        target = f'{side}:{amount:.2f}'
        label = f'{"Comprar" if side == "buy" else "Vender"} {money(amount)} de {short}'
    reply = {'es': PREPARED_REPLY,
             'pt': 'Deixei o cartão: confira o preço e a taxa e toque em Aprobar. Ainda não foi feito nada.',
             'en': 'I left the card: check the price and the fee and tap Aprobar there. Nothing has been done yet.'}[lang]
    return True, reply, {'actions': [{'type': 'trade', 'ticker': ticker, 'target': target, 'label': label}]}


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
