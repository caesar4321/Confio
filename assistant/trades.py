"""A stock or ETF bought or sold from a card in the chat.

The assistant only proposes. Code asks "¿Quieres vender toda tu posición en
Tesla (TSLA)?" (a yes or no) or "¿Cuántos dólares de Apple Inc. (AAPL) quieres
comprar? Escribe solo el número", and the exact answer to that message
(confirm.py: the yes, or the number typed alone) leaves the card:
`{'type': 'trade', 'ticker': ..., 'target': 'buy:20.00' | 'sell:20.00' |
'sell:all', 'label': ...}`. The phone shows the price and the fee, and the
person approves there; the trade then runs through the same code as the stock
screens (a binding quote, the wallet's own signature, the sponsored batch),
with every server gate those have.

Consent is never read out of a sentence: a word list took "la mitad", "no"
and "¿es todo?" for "sell all" (2026-11-22), and how many dollars is never
read from their words either. The proposal is only kept honest: the asset is
one the person named. What was asked is checked again on the answer.

A card is one trade. The phone does not invent the request it signs: it
asks for it here (`claim`), and while one request of a card is out, or one
of its batches is on record, no other is handed out. A card lasts a day.
"""
import logging
import re
import secrets
from datetime import timedelta
from decimal import Decimal

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

PREPARED_REPLY = 'Te dejé la tarjeta: revisa el precio y la comisión y toca Aprobar ahí. Todavía no se hizo nada.'

SPEC = {
    'type': 'function',
    'name': TOOL,
    'description': ('Para comprar o vender una acción o ETF aquí mismo. Llámala en cuanto sepas por lo que dijo la '
                    'persona, aunque sea en varios mensajes, si compra o vende y qué acción. amount_usd siempre '
                    'null: el servidor le pregunta cuántos dólares (o, en una venta, si vende todo) y con el número '
                    'que escriba deja la tarjeta con el precio para aprobar. No preguntes tú el monto ni si confirma: '
                    'llama la herramienta. sell_all solo si dijo que vende todo lo que tiene de esa acción. Nunca '
                    'elijas tú la acción; si falta, pregunta solo eso. Busca en la lista de Confío, que incluye acciones tokenizadas de '
                    'empresas privadas (Anthropic, SpaceX…): con esos datos úsala en vez de `navigate`. Se opera '
                    'por monto en dólares, no por número de acciones. La compra sale de su Confío Dollar+ y la venta '
                    'vuelve a su Confío Dollar+.'),
    'parameters': {
        'type': 'object',
        'properties': {
            'side': {'type': 'string', 'enum': ['buy', 'sell']},
            'asset': {'type': 'string', 'description': 'El ticker o el nombre que la persona escribió.'},
            'amount_usd': {'type': ['number', 'null'], 'description': 'Siempre null: el servidor pregunta el monto.'},
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
_CALLED = {'SPY': ('s&p', 's&p 500', 's&p500', 'sp500', 'sp 500'), 'QQQ': ('nasdaq', 'nasdaq 100'),
           'GLD': ('oro', 'gold'), 'IAU': ('oro', 'gold'), 'MMM': ('3m',), 'MCD': ('mcdonalds', "mcdonald's"),
           'KO': ('cocacola', 'coca cola', 'coca-cola'), 'TSM': ('tsmc',), 'JNJ': ('j&j',),
           'MSTR': ('microstrategy', 'micro strategy'), 'MELI': ('mercado libre', 'mercadolibre'),
           'JPM': ('jp morgan', 'jpmorgan')}


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
    joined = ({brand.replace(' ', '') for brand in brands if ' ' in brand}
              | ({''.join(full[:2])} if len(full) >= 2 else set()))
    for text in texts:
        said = _fold(text)
        words = set(re.findall(r'[a-z0-9&]+', said))
        if any(re.search(rf'(?<![\w]){re.escape(brand)}(?![\w])', said) for brand in brands if brand) or words & own:
            return True
        if words & joined:
            return True                 # "mercadolibre" (no typo or plural is guessed: "moderno" is not Moderna)
        if (folded in words or (not folded.isalnum() and re.search(rf'(?<![\w]){re.escape(folded)}(?![\w])', said))
                ) and (len(folded) > 2 or re.search(rf'(?<![\w]){re.escape(ticker)}(?![\w])', text)):
            return True                 # one or two letters: only as the ticker's own capitals
    return False


def money(amount, lang='es'):
    """US$20, US$20,50, US$1500 (US$20.50 in English). No thousands mark: "1.500" is a decimal point in Mexico."""
    text = f'{Decimal(amount):.2f}'
    text = text[:-3] if text.endswith('.00') else text
    return 'US$' + (text if lang == 'en' else text.replace('.', ','))


_OR_ALL = {'es': ' O escribe "toda" para vender toda tu posición.', 'pt': ' Ou escreva "tudo" para vender tudo.',
           'en': ' Or type "all" to sell your whole position.'}


def how_many(side, ticker, name, lang):
    """Code's "how many dollars": the ticker is always in it."""
    asset = f'{name} ({ticker})' if name and name != ticker else ticker
    verb = {'es': ('comprar', 'vender'), 'pt': ('comprar', 'vender'), 'en': ('buy', 'sell')}[lang][side == 'sell']
    return {'es': f'¿Cuántos dólares de {asset} quieres {verb}?',
            'pt': f'Quantos dólares de {asset} você quer {verb}?',
            'en': f'How many dollars of {asset} do you want to {verb}?'}[lang]


def sell_all_question(ticker, name, lang):
    """The yes/no for selling a whole position: the ticker is always in it."""
    asset = f'{name} ({ticker})' if name and name != ticker else ticker
    return {'es': f'¿Quieres vender toda tu posición en {asset}?',
            'pt': f'Você quer vender toda a sua posição em {asset}?',
            'en': f'Do you want to sell your whole position in {asset}?'}[lang]


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
    if sell_all or amount is None:
        return ''          # the amount is checked when they type it
    floor = MIN_BUY_USD if side == 'buy' else MIN_SELL_USD
    if amount < floor:
        return f'El mínimo es {money(floor)}.'
    if amount > Decimal(str(getattr(settings, 'CUSD_PLUS_GM_MAX_TRADE_USD', 100_000))):
        return 'Ese monto supera el máximo por operación.'
    return ''


def propose(belt, side, asset, amount_usd=None, sell_all=False):
    """Check the proposal and have code ask it. No card here: see confirmed(). `amount_usd` is never used: code
    asks how many dollars."""
    from . import confirm

    if confirm.busy(belt.result):
        return _refuse('Ya hay una pregunta o una propuesta en esta respuesta: una cosa por respuesta.')
    texts = confirm.recent_texts(belt)
    if not texts:
        # A call or a tapped suggestion: nothing the person typed to read from.
        return _refuse('Para comprar o vender desde el chat, la persona debe escribir en un mensaje qué acción.')
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
    # What people call it comes first: "nasdaq" is QQQ, not Nasdaq, Inc.; "oro" is two funds: ask which.
    called = [ticker for ticker, names in _CALLED.items() if _fold(str(asset or '')).strip() in names]
    if len(called) > 1:
        return _refuse('Hay más de una opción para eso en Confío (' + ', '.join(called) + '): pregúntale cuál quiere.')
    found = market.listed_asset(called[0]) if called else market.listed_asset(asset)
    if found is None:
        return _refuse('No encontré esa acción o ETF entre las que muestra Confío.')
    ticker, name = found
    sell_all = bool(sell_all) and side == 'sell'

    rows = _held(belt.viewer) if side == 'sell' else None
    # The one thing they hold needs no name, for a sale they asked for in these words.
    only_one = (isinstance(rows, list) and len(rows) == 1 and rows[0]['ticker'] == ticker
                and any(re.search(r'\b(vend|sell|liquid)', _fold(text)) for text in texts))
    if not only_one and not _named(texts, ticker, name):
        return _refuse(f'La persona no nombró {name or ticker}: pregúntale cuál quiere, no la elijas tú.')

    why = _cannot(belt, side, ticker, name, None, sell_all, rows)
    if why:
        return _refuse(why)
    lang = confirm.language(texts)
    data = {'side': side, 'ticker': ticker, 'sell_all': sell_all, 'amount': None}
    if sell_all:
        return confirm.ask(belt.result, 'trade', sell_all_question(ticker, name, lang), data, lang)
    # How many dollars is never the model's nor read from their words: code asks, and the number is it.
    return confirm.ask_amount(belt.result, 'trade', how_many(side, ticker, name, lang), data, lang,
                              extra=_OR_ALL[lang] if side == 'sell' else '')


def _to_them(why, lang, name):
    """_cannot's reason, said to the person in their language."""
    if why.startswith('Esta persona no puede'):
        return {'es': 'No puedes comprar acciones desde tu país o tu cuenta.',
                'pt': 'Você não pode comprar ações do seu país ou da sua conta.',
                'en': "You can't buy stocks from your country or account."}[lang]
    if why.startswith('No tiene '):
        return {'es': f'No tienes {name}: no hay nada que vender.', 'pt': f'Você não tem {name}: não há nada para vender.',
                'en': f"You don't hold {name}: there is nothing to sell."}[lang]
    if lang == 'es':
        return why
    return {'pt': 'Esse valor está fora do mínimo ou do máximo por operação.',
            'en': 'That amount is outside the minimum or maximum per trade.'}[lang]


def confirmed(belt, data, lang='es'):
    """The yes to propose()'s question: every gate again, then the card of exactly that."""
    side, ticker, sell_all = data.get('side'), data.get('ticker'), bool(data.get('sell_all'))
    found = market.listed_asset(ticker)
    if side not in ('buy', 'sell') or found is None or found[0] != ticker or not offered(belt):
        return False, {'es': 'No puedo dejarte esa tarjeta ahora. Puedes hacerlo en Invertir.',
                       'pt': 'Não consigo deixar esse cartão agora. Você pode fazer isso em Invertir.',
                       'en': "I can't leave that card right now. You can do it in Invertir."}[lang], {}
    name = found[1]
    amount = None if sell_all else Decimal(data['amount'])
    why = _cannot(belt, side, ticker, name, amount, sell_all, _held(belt.viewer) if side == 'sell' else None)
    if why:
        return False, _to_them(why, lang, name or ticker), {}
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
