"""The server asks, and a "sí" answers only that (a stock trade, a payment).

The model proposes; code writes the question from what it will do (in US
dollars, with the asset's ticker or the recipient spelled out) and keeps
exactly that, with the message that asked. The person's next message uses it
up, whatever it says. Only an exact yes, typed, to that very message and from
the same person and account makes the card, in code and without the model;
the card is still approved and signed on the phone. (One exception keeps it:
a number that can't be taken is answered by code asking the same again.)

Same pattern as a categorization's and an alert's confirmation (service.py,
is_save_yes here): "sí, mañana", "ok lo pienso" and "¿sí?" are none.

How many dollars is never read out of what the person wrote (the founder's
call, 2026-11-22: every reading had a gap). When a payment, a trade, a buy rule, a
target split or an alert's prepared buy needs an amount, code asks "¿Cuántos
dólares …? Escribe solo el número", and the number typed alone as the answer
is both the amount and the consent: then the card, or the proposal to sign.
A sale of a whole position and a Pix code with its own amount keep the yes/no.
"""
import logging
import re
import unicodedata
from datetime import timedelta

from django.core.cache import cache

logger = logging.getLogger(__name__)

SECONDS = 15 * 60
WINDOW = timedelta(seconds=SECONDS)
MAX_TEXTS = 8

_YES = frozenset((
    'si', 'sii', 'sip', 'si si', 'si por favor', 'por favor si', 'si porfa', 'si porfavor', 'si gracias', 'si dale',
    'si confirmo', 'si lo confirmo', 'si quiero', 'si correcto', 'si exacto', 'si claro', 'si hazlo', 'si adelante',
    'si de acuerdo', 'si asi es', 'si eso', 'si ok', 'ok si', 'dale', 'dale si', 'dale por favor', 'ok', 'okay', 'okey',
    'ok dale', 'ok gracias si', 'confirmo', 'confirmado', 'lo confirmo', 'exacto', 'exactamente', 'correcto',
    'es correcto', 'asi es', 'claro', 'claro que si', 'hazlo', 'adelante', 'de acuerdo', 'vale',
    'yes', 'yes please', 'yep', 'yeah', 'yes confirm', 'confirm', 'sure', 'yes do it', 'do it',
    'sim', 'sim por favor', 'sim obrigado', 'sim obrigada', 'sim confirmo', 'sim pode', 'pode', 'isso', 'sim isso',
))
# The verb of what was asked is a yes to it, and to nothing else.
_YES_TO = {
    'sell': frozenset(('vendela', 'vendelas', 'vendelo', 'vende', 'si vende', 'si vendela', 'si vendelas', 'si vendelo',
                       'si vender', 'si quiero vender', 'yes sell', 'yes sell it', 'sell it', 'sim vender')),
    'buy': frozenset(('compralo', 'comprala', 'compra', 'si compra', 'si compralo', 'si comprala', 'si comprar',
                      'si quiero comprar', 'yes buy', 'yes buy it', 'buy it', 'sim comprar')),
    'send': frozenset(('envialo', 'envia', 'enviale', 'mandalo', 'mandale', 'si envia', 'si envialo', 'si enviale',
                       'si mandalo', 'si mandale', 'si pagalo', 'pagalo', 'si paga', 'yes send', 'yes send it',
                       'send it', 'sim enviar', 'sim envie', 'sim pode enviar', 'sim pode pagar')),
}
# The answer "toda" to "¿quieres vender toda tu posición?".
_YES_ALL = frozenset(('toda', 'si toda', 'todo', 'si todo', 'todas', 'si todas', 'completa', 'si completa',
                      'all', 'yes all', 'all of it', 'yes all of it', 'tudo', 'sim tudo'))
_NO = frozenset((
    'no', 'no gracias', 'no cancela', 'no cancelalo', 'no cancelar', 'no por favor', 'no lo envies', 'no lo pagues',
    'no lo vendas', 'no lo compres', 'cancela por favor', 'dejalo', 'no dejalo', 'nop', 'nope', 'no no', 'mejor no', 'ya no', 'no quiero', 'cancela', 'cancelar', 'cancelalo',
    'cancelala', 'olvidalo', 'no confirmo', 'no thanks', 'no thank you', 'cancel', 'nao', 'nao obrigado', 'nao obrigada',
    'no olvidalo', 'olvidalo gracias', 'mejor no gracias', 'no lo hagas', 'no lo hagas por favor', 'no hagas nada',
    'dejalo asi', 'no gracias olvidalo', 'no no lo hagas', 'es estafa', 'es una estafa', 'no pagues', 'no lo pagues',
    'no lo pagues por favor', 'no es mio', 'nao faca isso', 'nao pague', 'nao quero', 'deixa pra la', 'esquece',
    'dont', 'don t', 'don t do it', 'dont do it', 'no don t', 'not now', 'nevermind', 'never mind', 'forget it',
))
# Words of one of the three languages only ("envíe", "compre" are Spanish too: not here).
_PORTUGUESE = frozenset("""quero gostaria minha minhas meu meus voce vc acoes acao sim tudo obrigado obrigada
uma pra ao esqueca esquece lembre lembra prefiro qual quanto quantos nao isso tambem esse essa ela ele dela
cair caia dinheiro invista investe deixe em""".split())
_ENGLISH = frozenset("""i want sell buy send my the yes please shares dollars to pay forget remember what how
much many thanks keep alert invest every monthly weekly daily month week day between drops drop rises rise falls in
fall if when goes below above of and it ready have make set split share stock""".split())
_SPANISH = frozenset("""quiero quisiera enviale envialo mandale mi mis el los las al unos vendela compralo cuanto cuantos
puedes hola gracias olvida recuerda tambien haz pon hazme ponme un y en con si""".split())
# The symbols a yes may carry. Any other ("sí ❌", "ok 🤔", "sí ❓") and it is not a yes.
_YES_SYMBOLS = frozenset('👍👌✅🙏' + '\U0001F3FB\U0001F3FC\U0001F3FD\U0001F3FE\U0001F3FF')
# A question that asks for it ("¿puedes enviarle 20 dólares a @ana?"), never "¿cuánto serían 20?".
_POLITE = re.compile(
    r'\b(?:puedes|podrias|podes|me ayudas(?: a)?|can you|could you|pode|poderia)(?: por favor| please| me| le)? '
    r'(?:envi\w*|mand\w*|transf\w*|pag\w*|pas(?:ar|arle)|compr\w*|vend\w*|send|pay|buy|sell)'
    r'|\b(?:me (?:compras|vendes|envias|mandas|pagas)|le (?:envias|mandas))\b')


def plain(text):
    """Folded, with no punctuation and no emoji; a question mark stays (a question is never a yes)."""
    from payment_accounts.payment_intents import _fold
    text = unicodedata.normalize('NFKC', str(text or ''))
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text)
    text = ''.join(' ' if unicodedata.category(ch) in ('So', 'Sk') or ch in '\ufe0f\u200d' else ch for ch in text)
    return ' '.join(re.sub(r'[.,!¡;:*_"\'«»()“”‘’–—-]', ' ', _fold(text)).split())


def is_yes(text, pending):
    said = plain(text)
    if not said or len(said) > 40:
        return False
    if any(unicodedata.category(ch) in ('So', 'Sk') and ch not in _YES_SYMBOLS for ch in str(text)):
        return False
    data = pending.get('data') or {}
    verb = 'send' if pending.get('kind') == 'payment' else data.get('side')
    return said in _YES or said in _YES_TO.get(verb, ()) or (bool(data.get('sell_all')) and said in _YES_ALL)


def is_no(text):
    return plain(text) in _NO


# Portuguese words whose marks folding takes away ("não" -> "nao"): read before folding. Only words, never
# a letter: a name ("João", "joão", "Conceição") says nothing about the language around it.
_PORTUGUESE_MARKED = frozenset("""não é você vocês ações ação então também mês três estão só pôr""".split())
# Words only Spanish or Portuguese sentences have: with any of them, English words are loans ("20 shares de
# Tesla", "un buy every month"), never the language of the request.
_ROMANCE = frozenset("""de del la el los las un una unos unas y en con para por que mi mis tu su al lo le les
da das dos uma em com pra pro meu minha seu sua na nos nas o""".split())


def _without_names(text):
    """The text without names: a capitalized word that does not start it ("envía a Uma", "paga a Isso")."""
    words = str(text or '').split()
    return ' '.join(word for at, word in enumerate(words)
                    if at == 0 or word.strip('¿?¡!.,;:"\'()@') == 'I'
                    or not word.strip('¿?¡!.,;:"\'()@')[:1].isupper())


def _portuguese_marked(text):
    return any(word.strip('¿?¡!.,;:"\'()').lower() in _PORTUGUESE_MARKED for word in _without_names(text).split())


def language(texts):
    """'es', 'pt' or 'en': the language of the question code writes. Spanish unless the words say otherwise."""
    words = {word for text in texts for word in plain(_without_names(text)).split()}
    scores = {'es': len(words & _SPANISH), 'pt': len(words & _PORTUGUESE), 'en': len(words & _ENGLISH)}
    scores['pt'] += 2 * sum(_portuguese_marked(text) for text in texts)
    # English needs two of its words and no Spanish or Portuguese function word around them.
    if scores['en'] < 2 or words & _ROMANCE:
        scores['en'] = 0
    best = max(('es', 'pt', 'en'), key=lambda key: scores[key])
    return best if scores[best] else 'es'


def requests(texts):
    """The texts with a polite request read as one: its question marks gone."""
    out = []
    for text in texts:
        said = plain(text)
        if ('?' in said or '¿' in said) and _POLITE.search(said):
            text = re.sub(r'[?¿？]', ' ', text).strip()
        out.append(text)
    return out


def all_said(belt, until_card=True, window=True, keep_tag=None):
    """Everything the person said, however they said it (a question, a voice
    note, a caption, a long paste), newest first, back to a card or a "no"
    (`until_card` as in recent_texts): where they may have said not to pay.
    `window`: only the last few minutes."""
    history = list(getattr(belt, 'turn_history', ()) or ())
    mine = [m for m in history if m.sender_type == 'USER' and (m.body or '').strip()]
    if not mine:
        return list(belt.payment_texts)
    latest, bodies = getattr(mine[-1], 'created_at', None), []
    for message in reversed(history):
        if message.sender_type != 'USER' or not (message.body or '').strip():
            if until_card and _ends(message, until_card, keep_tag):
                break
            continue
        sent = getattr(message, 'created_at', None)
        if window and latest and sent and latest - sent > WINDOW:
            break
        bodies.append(message.body)
    return bodies


def _served(message):
    """Code's reply that made a card or took a "no": what came before it was answered."""
    metadata = message.metadata or {}
    return message.sender_type == 'AGENT' and bool(
        metadata.get('payment_intent') or metadata.get('declined')
        or any(isinstance(action, dict) and action.get('type') == 'trade' for action in metadata.get('actions') or []))


def _ends(message, until_card, keep_tag=None):
    """Whether reading back stops at this message. Always at a "no" code took; with until_card=True at any card;
    with 'untagged' only at a payment card that does not say its code (a tagged one's code is left out by the
    caller, sends.propose)."""
    metadata = message.metadata or {}
    if metadata.get('declined') and message.sender_type in ('AGENT', 'SYSTEM'):
        return True          # code's "no" answer (a SYSTEM line: its withdrawal while the team had the thread)
    if message.sender_type != 'AGENT':
        return False
    if until_card is True:
        return _served(message)
    card = metadata.get('payment_intent')
    # 'untagged' with `keep_tag`: also a card of any other code (what was said before it was about that one).
    return until_card == 'untagged' and isinstance(card, dict) and (
        not card.get('code') or (keep_tag is not None and card.get('code') != keep_tag))


def last_minutes(history):
    """The thread's own messages of these last minutes (WINDOW), read from the database: the model's history
    holds only its last few messages, and a card or a warning a few quick exchanges back must not fall out of it.
    The history in hand when the thread can't be read."""
    mine = [m for m in history if getattr(m, 'sender_type', '') == 'USER']
    conversation = getattr(mine[-1], 'conversation', None) if mine else None
    latest = getattr(mine[-1], 'created_at', None) if mine else None
    if conversation is None or latest is None or not hasattr(conversation, 'messages'):
        return history
    try:
        return list(conversation.messages.filter(created_at__gte=latest - WINDOW, created_at__lte=latest)
                    .order_by('created_at', 'pk'))
    except Exception:  # noqa: BLE001 - not readable now: the history in hand
        logger.warning('Confio Assistant: recent messages unreadable', exc_info=True)
        return history


def served_codes(belt, open_only=False):
    """The tags of codes that got a card (sends.code_tag). `open_only`: only cards that can still be signed
    (None when that can't be read now)."""
    # The cards of these last minutes, from the thread itself (a quote lives five of them).
    carrying = [(m, (m.metadata or {}).get('payment_intent'))
                for m in last_minutes(list(getattr(belt, 'turn_history', ()) or ()))]
    carrying = [(m, card) for m, card in carrying if isinstance(card, dict) and card.get('code')]
    cards = {str(card.get('id')): str(card.get('code') or '') for _m, card in carrying}
    by_message = {m.pk: str(card.get('code') or '') for m, card in carrying if isinstance(getattr(m, 'pk', None), int)}
    if not open_only or not cards:
        return set(cards.values())
    from django.db.models import Q
    from django.utils import timezone

    from payment_accounts.models import PaymentIntent
    try:
        # By message too: a re-quote is a new card on the same message.
        rows = list(PaymentIntent.objects.filter(
            Q(internal_id__in=list(cards)) | Q(message_id__in=list(by_message)),
            state__in=('quoted', 'awaiting_signature'), expires_at__gt=timezone.now(),
        ).values_list('internal_id', 'message_id'))
    except Exception:  # noqa: BLE001 - not known: None, and the caller prepares nothing
        logger.exception('Confio Assistant: open cards unknown')
        return None
    return ({cards[str(i)] for i, _m in rows if str(i) in cards}
            | {by_message[m] for _i, m in rows if m in by_message})


def recent_texts(belt, until_card=True):
    """What the person typed in the last few minutes, newest first: where a
    proposal finds who and what (never how much: code asks that). Never a
    tapped suggestion, a voice note, a client-reported line or anyone else's
    words. `until_card`: True, a card or a "no" ends it; 'untagged', only a
    "no" or a card that does not say its code; False, only a "no"."""
    from .engine import is_tapped_text
    if not belt.payment_texts:
        return []  # the newest message is not typed: nothing is asked from it
    history = list(getattr(belt, 'turn_history', ()) or ())
    mine = [m for m in history if m.sender_type == 'USER' and (m.body or '').strip()]
    if not mine:
        return list(belt.payment_texts)
    latest, texts = getattr(mine[-1], 'created_at', None), []
    for message in reversed(history):
        metadata, sent = message.metadata or {}, getattr(message, 'created_at', None)
        if message.sender_type != 'USER' or not (message.body or '').strip():
            if _ends(message, until_card):
                break
            continue
        if message is not mine[-1] and not (latest and sent and timedelta(0) <= latest - sent <= WINDOW):
            break
        if (metadata.get('client_reported') or metadata.get('handoff_note')
                or str(metadata.get('modality') or 'TEXT').upper() != 'TEXT' or is_tapped_text(message.body)):
            continue
        texts.append(message.body.strip())
        if len(texts) >= MAX_TEXTS:
            break
    return texts


def busy(result, count_writes=True):
    """This reply already has the one thing to approve or answer (or a payment refused because they said not
    to pay it: that is its answer). With `count_writes`, also when something was already saved in it
    (result.writes): code's question replaces the reply, and would hide that."""
    return bool(result.pending_action or result.payment_intent or result.rule_proposal or result.declined
                or result.pending_categorization or result.pending_watch or (count_writes and result.writes)
                or getattr(result, 'store_task_started', False) or getattr(result, 'whatsapp_card', False)
                or any(action.get('type') in ('trade', 'form') for action in result.actions))


def amount_answer(text):
    """The number typed alone as the answer to code's "¿Cuántos dólares …? Escribe solo el número": a Decimal
    of cents, or None. "20", "20,50", "US$20", "20 dólares", "20 por favor". Never "1.500" (a thousand and a
    half, or one and a half?), never ".50" as 50, never "$20" (pesos to many), never a question."""
    from decimal import Decimal

    from payment_accounts.payment_intents import _fold, _normalized
    raw = str(text or '')
    if re.search(r'[?¿？]', raw) or any(unicodedata.category(ch) in ('So', 'Sk') for ch in raw) or _odd_digits(raw):
        return None
    # Only the end is tidied: ".50" is fifty cents to them, never 50.
    said = ' '.join(_fold(_normalized(raw)).split()).rstrip(' .!')
    # A bare "$" is pesos to many (Mexico, Colombia, Argentina): only "US$" or "USD" before it.
    found = re.fullmatch(r'(?:(?:us ?\$|usd|u\$[sd]) ?)?(?P<number>[0-9]{1,7}(?:[.,][0-9]{1,2})?|[.,][0-9]{1,2})'
                         r'(?: ?(?:dolares|dolar|dollars?|usd))?'
                         r'(?:,? (?:por favor|porfa|porfavor|gracias|please|thanks|obrigado|obrigada))*', said)
    if not found:
        return None
    value = Decimal('0' + found['number'].replace(',', '.')).quantize(Decimal('0.01'))
    return value if value > 0 else None


# The yes that saves an alert or a category: every word from these, at least one of them a yes.
_SAVE_YES = frozenset("""sii sip dale ok okay okey confirmo confirmado confirmalo confirmar confirm claro hazlo hagalo
adelante perfecto correcto exacto exactamente listo vale acuerdo yes yep yeah sure sim pode isso""".split())
_SAVE_VERBS = {
    'alert': frozenset("""guardala guardalo guardalas guardalos guardela guardelo guardamela guardar guardarla guarda
guarde crearla creala activala activa save salva salvar""".split()),
    'category': frozenset("""guardala guardalo guardalas guardalos guardar guarda guarde clasificalo clasificalos
clasificala clasificalas clasificar save salva salvar""".split()),
}
_SAVE_COURTESY = frozenset("""por favor porfa porfis gracias muchas de senor senora que asi es esta bien la alerta lo
quiero claro eso fa please thanks it go ahead do obrigado obrigada mesmo favor correcto supuesto""".split())
_SAVE_SYMBOLS = _YES_SYMBOLS | frozenset('😊🙂😀😁😄🥰❤♥💪🙌💯🤝')


def is_save_yes(text, kind):
    """A whole answer saying yes to saving that alert ('alert') or category ('category')."""
    if any(unicodedata.category(ch) in ('So', 'Sk') and ch not in _SAVE_SYMBOLS for ch in str(text or '')):
        return False
    if re.search(r'[?¿？]', str(text or '')):
        return False
    words = plain(text).split()
    if not words or len(' '.join(words)) > 60:
        return False
    verbs = _SAVE_VERBS.get(kind, frozenset())
    if not all(word in _SAVE_YES or word in verbs or word in _SAVE_COURTESY or re.fullmatch('si+', word)
               for word in words):
        return False
    joined = f" {' '.join(words)} "
    if any(f' {phrase} ' in joined for phrase in ('esta bien', 'asi es', 'es correcto', 'esta correcto',
                                                 'por supuesto', 'go ahead')):
        return True
    if re.fullmatch('si+', words[0]) and len(words) > 1 and words[1] in ('es', 'esta'):
        return False        # "si es así…" is "if"
    return any(word in _SAVE_YES or word in verbs or re.fullmatch('si+', word) for word in words)


def ask(result, kind, question, data, lang):
    """The reply becomes this question, and nothing else (service.py)."""
    answer = {'es': 'Escribe sí o no.', 'pt': 'Escreva sim ou não.', 'en': 'Type yes or no.'}[lang]
    result.pending_action = {'kind': kind, 'question': f'{question} {answer}', 'data': data, 'lang': lang}
    return {'ok': True, 'pregunta_enviada': question,
            'nota': ('Todavía no se preparó nada. El servidor le hace esa pregunta exacta en lugar de tu respuesta y, '
                     'si responde que sí, deja la tarjeta. No preguntes otra cosa ni llames otra herramienta.')}


def ask_amount(result, kind, question, data, lang, extra=''):
    """The reply becomes "how many dollars", and nothing else: the number typed alone answers it (answer())."""
    only = {'es': 'Escribe solo el número.', 'pt': 'Escreva só o número.', 'en': 'Type just the number.'}[lang]
    result.pending_action = {'kind': kind, 'step': 'amount', 'question': f'{question} {only}{extra}', 'data': data,
                             'lang': lang}
    return {'ok': True, 'pregunta_enviada': question,
            'nota': ('Todavía no se preparó nada. El servidor le pregunta cuántos dólares, en lugar de tu respuesta: '
                     'con el número que escriba deja la tarjeta o la propuesta. No preguntes tú el monto, no lo '
                     'repitas ni llames otra herramienta.')}


# ── what was asked, for exactly one message ────────────────────────────────

def _key(conversation):
    return f'assistant:pending-action:{conversation.id}'


def store(conversation, viewer, pending, reply):
    cache.set(_key(conversation), {**pending, 'user_id': viewer.user.pk, 'account_id': viewer.account.id,
                                   'reply_id': reply.id}, SECONDS)


def take(conversation):
    """Remove and return what was asked: every message of the person uses it up."""
    key = _key(conversation)
    pending = cache.get(key)
    if pending is not None:
        cache.delete(key)
    return pending


# Words around a number that still leave it a number answer (code says why it can't take it).
_AROUND_A_NUMBER = frozenset("""us usd dolares dolar dollars dollar bolivares bolivar bs bolos pesos peso reales reais
soles euros mil k unos unas como por favor porfa porfavor gracias please thanks obrigado obrigada usdt usdc
son es seria serian sao lucas luca nomas""".split())


def _odd_digits(raw):
    """A digit or number sign that is not 0-9 ("20²", "⑳", "½", full-width or other scripts' digits): never read as an amount, since
    normalizing it would change the number (² became 2). A letter's accent typed apart ("dólares" as o + ´) is
    composed first: only a mark left on a digit or alone counts."""
    raw = unicodedata.normalize('NFC', str(raw or ''))
    after_digit = False
    for ch in raw:
        if ch in _EMOJI_JOINERS:
            if after_digit:
                return True                # inside the number (2, a joiner, 0): invisible, never read away
            continue                       # part of an emoji ("❤️", "🤷‍♀️"): nothing about a number
        kind = unicodedata.category(ch)
        if '0' <= ch <= '9':
            after_digit = True
            continue
        if ch.isalpha():
            after_digit = False
            continue
        if unicodedata.numeric(ch, None) is not None or kind == 'Cf':
            return True                    # another script's digit, "²", "½"; an invisible or direction control
        if kind in ('Mn', 'Me', 'Mc'):
            if after_digit:
                return True                # a mark on a digit ("2̶0")
            continue
        after_digit = False
    return False


# The invisible parts of emoji (variation selectors, the zero-width joiner).
_EMOJI_JOINERS = frozenset('\ufe0e\ufe0f\u200d')


_BETWEEN_NUMBERS = frozenset('o u y e a or ou and to'.split())


# "No sé" to "¿cuántos dólares?" is a doubt, not a no: the model answers it.
_NOT_KNOWING = frozenset(('no se', 'no lo se', 'no sabria', 'no se cuanto', 'no estoy seguro', 'no estoy segura',
                          'nao sei', 'no idea', 'not sure'))


def _number_shaped(text):
    """A number typed as the answer, though not one code can take ("1.500", "$20", "20 bolívares"): never a
    question, a handle or a sentence that only has a number in it."""
    from payment_accounts.payment_intents import _fold
    raw = str(text or '')
    if re.search(r'[?¿？@]', raw):
        return False
    if _odd_digits(raw):
        return True
    # Currency signs before a number ("R$20", "S/ 20", "€20") and "¡…!" leave it a number.
    # Signs, brackets and emoji around it ("*20*", "(20)", "20 👍", "20 :)") leave it a number too.
    bare = re.sub(r'(?:\br\$|\bs/|\bu\$[sd]|\bus\$)', ' ', _fold(raw))
    bare = ''.join(' ' if unicodedata.category(ch)[0] in 'SP' and ch not in '.,' else ch for ch in bare)
    words = [word.strip('.,;:') for word in bare.split()]
    words = [word for word in words if word and word not in _AROUND_A_NUMBER]
    numbers = [word for word in words if re.fullmatch(r'[0-9][0-9.,]*(?:k|mil)?', word)]
    # One number, or two with "o"/"y" between them ("20 o 30"): still only an amount, just not one to take.
    if len(numbers) == 2 and len(words) == 3 and words[1] in _BETWEEN_NUMBERS:
        return True
    if len(numbers) == 2 and len(words) == 2:          # "1 500": a thousand and five hundred, or two numbers?
        return True
    return len(words) == 1 and len(numbers) == 1


def same_answer(text, answer, pending):
    """`text` says what `answer` said to that question (the same "sí", or the same number, sent twice)."""
    if pending.get('step') == 'amount':
        number = amount_answer(answer)
        return (number is not None and amount_answer(text) == number) or plain(text) == plain(answer)
    return is_yes(text, pending)


def previous_message(conversation, user_message):
    """The message right before theirs, whoever wrote it, but the server's own SYSTEM lines (nobody's words).
    A team message, a send_team_notice included, counts: it may ask its own question, and a "sí" or a number
    after it answers the team, never code's question above it. So does a SYSTEM line that carries a payment card
    (one scanned in the chat): "no lo pagues" under it is about that card, never code's question above it."""
    before = (conversation.messages.filter(created_at__lte=user_message.created_at).exclude(pk=user_message.pk)
              .order_by('-created_at', '-pk')[:20])
    for message in before:
        if message.sender_type == 'SYSTEM' and not isinstance((message.metadata or {}).get('payment_intent'), dict):
            continue
        return message.pk
    return None


def answer(conversation, viewer, text, pending, user_message, *, can_navigate=True):
    """The answer to that question: (done, reply, metadata), or None when this
    message is no such answer (then the model answers it, with nothing prepared)."""
    if (not pending or pending.get('user_id') != getattr(viewer.user, 'pk', None)
            or pending.get('account_id') != getattr(viewer.account, 'id', None)):
        return None
    metadata = user_message.metadata or {}
    if metadata.get('client_reported') or str(metadata.get('modality') or 'TEXT').upper() != 'TEXT':
        return None
    data, amount, everything = dict(pending.get('data') or {}), None, False
    if pending.get('step') == 'amount':
        amount = amount_answer(text)
        # "¿Cuántos dólares de Tesla quieres vender? … o «toda»": their whole position.
        everything = (amount is None and pending.get('kind') == 'trade' and data.get('side') == 'sell'
                      and plain(text) in _YES_ALL)
        yes = amount is not None or everything
    else:
        yes = is_yes(text, pending)
    from payment_accounts.payment_intents import find_pix_codes
    if find_pix_codes(str(text or '')):
        return None
    said = plain(text)
    # "no, 20 no", "cancela todo, 2": a no, whatever number is in it.
    refused = is_no(text) or (pending.get('step') == 'amount' and said.split()[:1] in (
        ['no'], ['nao'], ['cancela'], ['cancelar'], ['cancel']) and bool(re.search(r'[0-9]', said))
        and said not in _NOT_KNOWING)
    retry = pending.get('step') == 'amount' and not yes and not refused and _number_shaped(text)
    if not yes and not refused and not retry:
        return None
    if previous_message(conversation, user_message) != pending.get('reply_id'):
        return None
    lang = pending.get('lang') if pending.get('lang') in ('es', 'pt', 'en') else 'es'
    if retry:
        # A number, but not one that can be taken ("1.500", "$20", "20 bolívares"): code asks again, saying why.
        return False, {'es': 'No pude tomar ese monto.', 'pt': 'Não consegui usar esse valor.',
                       'en': "I couldn't take that amount."}[lang] + f" {pending.get('question', '')}", {'ask_again': True}
    if not yes and not retry:
        tag = ((pending.get('data') or {}).get('request') or {}).get('code_tag') if pending.get('kind') == 'payment' \
            else ''
        return False, {'es': 'Listo, no preparé nada.', 'pt': 'Certo, não preparei nada.',
                       'en': 'OK, I prepared nothing.'}[lang], {'declined': True,
                                                                **({'refused_code': tag} if tag else {})}
    from .engine import Toolbelt, TurnResult
    belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0, can_navigate=can_navigate)
    kind = pending.get('kind')
    try:
        if kind == 'trade':
            from . import trades
            if pending.get('step') == 'amount':
                data = {**data, 'sell_all': everything, 'amount': None if everything else f'{amount:.2f}'}
            return trades.confirmed(belt, data, lang)
        if kind == 'payment':
            from . import sends
            if pending.get('step') == 'amount':
                data = {**data, 'request': {**data['request'], 'amount_usd': f'{amount:.2f}'}}
            return sends.confirmed(belt, data, lang)
        if kind in ('rule', 'allocation', 'watch') and amount is not None:
            from . import asked
            return getattr(asked, kind)(belt, data, amount, lang)
    except Exception:  # noqa: BLE001 - a yes never becomes anything but that card or this line
        logger.exception('Confio Assistant: a confirmed action could not be prepared')
        return False, {'es': 'No pude prepararlo ahora. Inténtalo de nuevo.',
                       'pt': 'Não consegui preparar agora. Tente de novo.',
                       'en': "I couldn't prepare it now. Please try again."}[lang], {}
    return None
