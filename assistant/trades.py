"""A stock or ETF bought or sold from a card in the chat.

The assistant only leaves the card: `{'type': 'trade', 'ticker': ...,
'target': 'buy:20.00' | 'sell:20.00' | 'sell:all', 'label': ...}`. The phone
shows the price and the fee, and the person approves there; the trade then
runs through the same code as the stock screens (a binding quote, the
wallet's own signature, the sponsored batch), with every server gate those
have.

What the card may carry is read from the person's own typed words, never
from the model: the asset, the dollars (or that they sell all of it) and
the verb. People say it across messages, so two shapes count:

- the last two typed messages together ("¿cómo compro acciones de
  Anthropic?", then "por 1.02 dólares"; "compra Apple", then "20"), where
  the newest message always wins and has to add to the request;
- a plain "sí" right after the assistant asked exactly this ("¿Quieres
  comprar US$1,02 de Anthropic?"), when the asset and the amount are also in
  the person's own earlier messages since the last card.

Anything unclear is refused and the assistant asks.

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
_EDGE = '.,;:!?¡¿()"\'«»“”*'
_SIGNS = ('us$', '$us', 'u$s', 'usd', '$')
# Words an answer to "¿cuántos dólares?" or "¿cuál?" may carry around it.
_FILLER = {'por', 'con', 'de', 'del', 'en', 'unos', 'unas', 'solo', 'mejor', 'que', 'sean', 'la', 'el', 'las', 'los',
           'acciones', 'accion', 'si', 'ok', 'dale', 'y'}
_CANCEL = re.compile(r'^(no|nop|cancel\w*|olvid\w*|espera)\b|\b(ya no|mejor no)\b')
# "vende todo", "vender todas mis acciones de Apple", "liquida todo lo que tengo".
_SELL_ALL = re.compile(r'\b(?:vend\w*|liquid\w*)\b[^.!·\n]{0,40}?\b(tod[oa]s?|complet[oa]|enter[oa])\b')
_NOT_ALL = re.compile(r'\b(no|ni|menos|excepto|salvo|sin)\s+(\w+\s+)?tod[oa]s?\b'
                      r'|\b(sobre|por|ante|con|eso es|es)\s+todo\b|\btodo\s+(bien|ok|listo|claro)\b')

SPEC = {
    'type': 'function',
    'name': TOOL,
    'description': ('Deja en la conversación una tarjeta para comprar o vender una acción o ETF aquí mismo: la '
                    'persona ve ahí el precio y la comisión y aprueba en la tarjeta. Úsalo en cuanto tengas las '
                    'tres cosas dichas por ella, aunque sea en mensajes distintos: comprar o vender, qué acción y '
                    'cuántos dólares (o que vende todo lo que tiene de esa acción); también cuando responde "sí" '
                    'a tu pregunta de si quiere justo eso. No pidas otra confirmación: la tarjeta es la '
                    'confirmación. Nunca elijas tú la acción ni el monto, y si falta uno de los dos, '
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
    return {'ok': False, '_denied': True, 'motivo': why,
            'como_decirlo': ('No menciones herramientas ni esta nota, y no le pidas que copie una frase. Pregúntale '
                             'solo lo que falta. Si ya dijo la acción y el monto, hazle una sola pregunta con las '
                             'tres cosas («¿Quieres comprar US$X de NOMBRE?») y, cuando responda que sí, vuelve a '
                             'dejar la tarjeta.')}


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


def _number(word):
    """(the number, whether a dollar sign is glued to it); ('', False) when the word is no number."""
    number, signed = word, False
    for sign in _SIGNS:
        if word.startswith(sign) or word.endswith(sign):
            number, signed = word.removeprefix(sign) if word.startswith(sign) else word.removesuffix(sign), True
            break
    if number[:1].isdigit() and all(ch.isdigit() or ch in '.,' for ch in number):
        return number, signed
    return '', False


def _is_number(word):
    return bool(_number(word)[0])


def _values(number):
    from payment_accounts.payment_intents import _amount_values

    try:
        return _amount_values(number)
    except ArithmeticError:
        return set()


def _in_dollars(tokens, index, signed):
    before = tokens[index - 1][0] if index else ''
    after = tokens[index + 1][0] if index + 1 < len(tokens) else ''
    return signed or before in _SIGNS or after in _DOLLARS or after in _SIGNS


def _name_words(ticker, name):
    return set(re.findall(r'[a-z0-9&]+', _fold(f'{ticker} {name or ""}')))


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


def _dollars_at(tokens, amount, asset_index, names=frozenset(), answering=False):
    """The person wrote this amount as dollars to trade: with the dollar
    word or sign ("20 dólares", "US$ 20"), or bare and tied to the request
    ("20 de Apple", "compra Apple por 20", or just "20" as the answer to
    what was missing). Not a price level, a percentage, an age, another
    currency, a count of shares, or a number they denied."""
    for index, (word, _typed) in enumerate(tokens):
        number, signed = _number(word)
        if not number or amount not in _values(number):
            continue
        before = [w for w, _t in tokens[max(0, index - 3):index]]
        after = [w for w, _t in tokens[index + 1:index + 3]]
        if set(before) & {'no', 'ni', 'nunca', 'sin'} or before[-2:] == ['vez', 'de']:
            continue
        if after[:1] and after[0] in _SHARE_WORDS:
            continue
        if _in_dollars(tokens, index, signed):
            return True
        # Bare: "<amount> de|en <asset>", "... por <amount>" at the end, or the whole answer.
        if after[:1] and after[0] in ('de', 'en') and asset_index in (index + 2, index + 3):
            return True
        if not after and before[-1:] in (['por'], ['con']):
            return True
        if answering and len(tokens) <= 6 and all(
                w in _FILLER | _DOLLARS | names for at, (w, _t) in enumerate(tokens) if at != index):
            return True
    return False


def _counts_shares(tokens, amount):
    """They wrote this number as a count of shares ("5 acciones", "1.000 acciones")."""
    for index, (word, _typed) in enumerate(tokens[:-1]):
        number, _signed = _number(word)
        if number and tokens[index + 1][0] in _SHARE_WORDS and amount in _values(number):
            return True
    return False


def _asset_answer(tokens, ticker, name, probes):
    """The whole message is the asset's name: the answer to "¿cuál?"."""
    names = _name_words(ticker, name) | probes
    words = [(w, typed) for w, typed in tokens if w and w not in _FILLER]
    if not words or len(tokens) > 6 or not all(w in names for w, _typed in words):
        return False
    return any(w in probes and (len(w) > 2 or typed == ticker) for w, typed in words)


def _names_other(tokens, ticker, name):
    """The message names another listed asset ("mejor Tesla"): what was said
    before about this one no longer stands."""
    words = {w for w, _typed in tokens} - _name_words(ticker, name) - _FILLER - _DOLLARS - _SHARE_WORDS
    if any(market.BRAND_TICKERS.get(word, ticker) != ticker for word in words):
        return True
    try:
        from cusd_plus import gm_api
        from cusd_plus.schema import _gm_listing
        for listing in map(_gm_listing, gm_api.all_market()):
            if not listing or listing[1] == ticker:
                continue
            other = _fold(listing[1])
            if len(other) >= 3 and other not in _WORD_TICKERS and other in words:
                return True
            first = re.findall(r'[a-z0-9&]+', _fold(listing[2] or ''))[:1]
            if first and len(first[0]) >= 4 and first[0] in words:
                return True
    except Exception:  # noqa: BLE001 - unknown: ask, never carry the older asset over
        logger.warning('Confio Assistant: listings unavailable for a trade card', exc_info=True)
        return True
    return False


def _carded(message):
    metadata = getattr(message, 'metadata', None) or {}
    return bool(metadata.get('payment_intent')) or any(
        isinstance(a, dict) and a.get('type') == 'trade' for a in metadata.get('actions') or [])


def _confirmed(history, ticker, name, probes, side, amount, sell_all):
    """A plain "sí" to the assistant's question of exactly this trade, whose
    asset and amount the person had written themselves since the last card.
    The question alone is never enough: the model wrote it."""
    from payment_accounts.payment_intents import MAX_REQUEST_CHARS

    from .engine import PAYMENT_CODE_WINDOW, is_tapped_text
    from .service import is_affirmative

    history = list(history or ())
    if len(history) < 2:
        return False
    answer, asked = history[-1], history[-2]
    body = (answer.body or '').strip()
    if answer.sender_type != 'USER' or not is_affirmative(body) or any(ch.isdigit() for ch in body):
        return False
    if asked.sender_type != 'AGENT' or not (asked.metadata or {}).get('ai') or _carded(asked):
        return False
    if (asked.metadata or {}).get('recalled'):
        return False        # written with stored data (assistant/context.py): never a question a "sí" confirms
    if not timedelta(0) <= answer.created_at - asked.created_at <= PAYMENT_CODE_WINDOW:
        return False

    questions = re.findall(r'¿[^¿?]*\?', asked.body or '')
    if questions:
        question = questions[-1]
    else:
        found = re.search(r'\bconf[ií]rm.*', asked.body or '', re.IGNORECASE | re.DOTALL)
        if not found:
            return False
        question = found.group(0)
    tokens = _tokens(question)
    words = [word for word, _typed in tokens]
    if 'o' in words or words[:1] == ['no'] or not any(word in probes for word in words):
        return False        # a choice between two things, or not about this asset
    wanted, other = (_BUY_VERBS, _SELL) if side == 'buy' else (_SELL, _BUY_VERBS)
    if not any(w.startswith(wanted) for w in words) or any(w.startswith(other) for w in words):
        return False
    money = [number for index, word in enumerate(words) for number, signed in [_number(word)]
             if number and _in_dollars(tokens, index, signed)]
    if sell_all:
        if money or not _SELL_ALL.search(' '.join(words)):
            return False
    elif not money or any(amount not in _values(number) for number in money):
        return False

    # The person's own messages since the last card.
    since = max((index for index, message in enumerate(history) if _carded(message)), default=-1)
    mine = []
    for message in history[since + 1:-1]:
        metadata, text = message.metadata or {}, (message.body or '').strip()
        if (message.sender_type == 'USER' and text and not metadata.get('client_reported')
                and not metadata.get('handoff_note') and str(metadata.get('modality') or 'TEXT').upper() == 'TEXT'
                and len(' '.join(text.split())) <= MAX_REQUEST_CHARS and not is_tapped_text(text)):
            mine.append(_tokens(text))
    folded = _fold(ticker)
    everyday = len(folded) <= 2 or folded in _WORD_TICKERS
    if not any(_asset_at(said, ticker, probes) >= 0 or any(
            word in probes and (word != folded or not everyday or typed == ticker) for word, typed in said)
               for said in mine):
        return False
    if sell_all:
        texts = [' '.join(word for word, _typed in said) for said in mine]
        return any(_SELL_ALL.search(text) and not _NOT_ALL.search(text) for text in texts)
    if any(_counts_shares(said, amount) for said in mine):
        return False
    return any(amount in _values(_number(word)[0]) for said in mine for word, _typed in said if _is_number(word))


def _short(ticker, name):
    return name if name and len(name) <= 18 else ticker


def _money(amount):
    """US$20 or US$20,50: as the app writes dollars in Spanish."""
    text = f'{amount:.2f}'.replace('.', ',')
    return 'US$' + (text[:-3] if text.endswith(',00') else text)


def _not_said(typed, ticker, name, probes, side, amount, sell_all):
    """Why the last two typed messages (newest first) don't ask for this
    trade; '' when they do."""
    latest = typed[0]
    if not _requests([latest]):
        return ('Eso fue una pregunta o un texto largo, no un pedido: respóndelo. Si quiere comprar o vender, que '
                'diga qué acción y cuántos dólares.')
    tokens = _tokens(latest)
    names = _name_words(ticker, name)
    numbers = [word for word, _typed in tokens if _is_number(word) and word not in names]
    if not numbers and _CANCEL.search(' '.join(word for word, _typed in tokens)):
        return 'La persona dijo que no: no dejes ninguna tarjeta.'

    from payment_accounts.payment_intents import MAX_REQUEST_CHARS
    # An earlier question may say which asset and the verb ("¿cómo compro
    # Apple?"), never how much ("¿cuánto serían 100 de Apple?").
    earlier = [text for text in typed[1:] if len(' '.join(text.split())) <= MAX_REQUEST_CHARS]
    at = _asset_at(tokens, ticker, probes)
    latest_names = at >= 0 or (bool(earlier) and _asset_answer(tokens, ticker, name, probes))
    if not latest_names and (
            not any(_asset_at(_tokens(text), ticker, probes) >= 0 or _asset_answer(_tokens(text), ticker, name, probes)
                    for text in earlier)
            or _names_other(tokens, ticker, name)):
        return f'La persona no nombró {name or ticker} en lo que pidió: pregúntale cuál quiere, no la elijas tú.'

    if earlier and not latest_names and not numbers:
        # "gracias", "ok, lo pienso": nothing that asks for it now.
        from .service import is_affirmative
        verb = any(word.startswith(_BUY_VERBS + _SELL) for word, _typed in tokens)
        if not is_affirmative(latest) and not (verb and (len(tokens) <= 2 or sell_all)):
            return 'Su último mensaje no lo pide: pregúntale si quiere hacerlo.'

    # The newest message that has a verb says which side it is.
    for text in [latest, *earlier, '']:
        stems = set(re.findall(r'[a-z]+', _fold(text)))
        sells = any(word.startswith(_SELL) for word in stems)
        buys = any(word.startswith(_BUY) for word in stems)
        if sells or buys:
            break
    if side == 'sell' and not sells:
        return 'La persona no escribió que quiere vender: pregúntale qué quiere hacer.'
    if side == 'buy' and sells and not any(word.startswith(_BUY_VERBS) for word in stems):
        return 'La persona habló de vender, no de comprar: pregúntale qué quiere hacer.'
    if side == 'buy' and not buys:
        return 'La persona no escribió que quiere comprar: pregúntale qué quiere hacer.'

    asked = [_tokens(text) for text in [latest, *_requests(earlier)]]
    if sell_all:
        whole = [' '.join(word for word, _typed in said) for said in asked]
        if not any(_SELL_ALL.search(text) and not _NOT_ALL.search(text) for text in whole):
            return 'La persona no escribió claramente que vende todo: pregúntale si vende todo o cuántos dólares.'
        if any(_is_number(word) and word not in names for said in asked for word, _typed in said):
            # "vende 10 de Apple, eso es todo": an amount and "todo" together.
            return 'Escribió un número y también "todo": pregúntale si vende todo o ese monto.'
        return ''
    if amount is None:
        return 'Falta el monto en dólares: pregúntaselo.'
    if any(_counts_shares(said, amount) for said in asked):
        return ('Escribió un número de acciones, no dólares. Aquí se compra y se vende por monto en dólares: '
                'pregúntale cuántos dólares.')
    # A number in the newest message replaces whatever was said before it.
    where = asked[:1] if numbers else asked
    for said in where:
        if _dollars_at(said, amount, _asset_at(said, ticker, probes), names, answering=bool(earlier)):
            return ''
    return ('Ese monto no está escrito como dólares en lo que pidió: pregúntale cuántos dólares, no lo calcules '
            'ni lo supongas tú.')


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
    found = market.listed_asset(asset)
    if found is None:
        return _refuse('No encontré esa acción o ETF entre las que muestra Confío.')
    ticker, name = found
    sell_all = bool(sell_all) and side == 'sell'
    amount = None
    if not sell_all and amount_usd is not None:
        try:
            amount = Decimal(str(amount_usd)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            amount = None
    probes = _probes(ticker, name)
    confirmed = (sell_all or amount is not None) and _confirmed(
        getattr(belt, 'turn_history', ()), ticker, name, probes, side, amount, sell_all)
    if not confirmed:
        why = _not_said(belt.payment_texts, ticker, name, probes, side, amount, sell_all)
        if why:
            return _refuse(why)
    if side == 'buy':
        from cusd_plus.eligibility import check_stock_buy_eligibility
        if not check_stock_buy_eligibility(viewer.user, viewer.request_meta):
            return _refuse('Esta persona no puede comprar acciones desde su país o su cuenta.')

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
        target, label = 'sell:all', f'Vender todo {short}'
    else:
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
