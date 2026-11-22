"""The server asks, and a "sí" answers only that (a stock trade, a payment).

The model proposes; code writes the question from what it will do (in US
dollars, with the asset's ticker or the recipient spelled out) and keeps
exactly that, with the message that asked. The person's next message uses it
up, whatever it says. Only an exact yes, typed, to that very message and from
the same person and account makes the card, in code and without the model;
the card is still approved and signed on the phone.

Same pattern as a categorization's and an alert's confirmation (service.py),
with a stricter yes: "sí, mañana", "ok lo pienso" and "¿sí?" are none.
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
))
# Words of one of the three languages only.
_PORTUGUESE = frozenset("""quero queria gostaria minha minhas meu meus voce vc acoes acao envie mande compre venda sim
tudo obrigado obrigada uma pra ao pro pague invista nao""".split())
_ENGLISH = frozenset("""i want sell buy send my the yes please shares dollars to pay""".split())
_SPANISH = frozenset("""quiero quisiera envia enviale envialo mandale mi mis el la los las al unos vendela
compralo cuanto puedes""".split())
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
    text = ''.join(' ' if unicodedata.category(ch) in ('So', 'Sk') or ch in '️‍' else ch for ch in text)
    return ' '.join(re.sub(r'[.,!¡;:*_"\'«»()]', ' ', _fold(text)).split())


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


def language(texts):
    """'es', 'pt' or 'en': the language of the question code writes."""
    words = {word for text in texts for word in plain(text).split()}
    scores = {'es': len(words & _SPANISH), 'pt': len(words & _PORTUGUESE), 'en': len(words & _ENGLISH)}
    best = max(('es', 'pt', 'en'), key=lambda key: scores[key])
    return best if scores[best] else 'es'


def requests(texts):
    """The texts with a polite request read as one: its question marks gone."""
    out = []
    for text in texts:
        said = plain(text)
        if ('?' in said or '¿' in said) and _POLITE.search(said) and not re.search(r'\b(cuant|quant|how much)', said):
            text = re.sub(r'[?¿？]', ' ', text).strip()
        out.append(text)
    return out


def all_said(belt):
    """Everything the person said in the last few minutes, however they said it
    (a question, a voice note, a caption, a long paste). Never where an amount
    is read from: only where other money may have been named."""
    history = list(getattr(belt, 'turn_history', ()) or ())
    mine = [m for m in history if m.sender_type == 'USER' and (m.body or '').strip()]
    if not mine:
        return list(belt.payment_texts)
    latest, bodies = getattr(mine[-1], 'created_at', None), []
    for message in reversed(mine):
        sent = getattr(message, 'created_at', None)
        if latest and sent and latest - sent > WINDOW:
            break
        bodies.append(message.body)
    return bodies + [text for text in belt.payment_texts if text not in bodies]


def recent_texts(belt, until_card=False):
    """What the person typed in the last few minutes, newest first: where a
    proposal finds who, what and how much. Never a tapped suggestion, a voice
    note, a client-reported line or anyone else's words. `until_card`: nothing
    from before a payment card (that code was served)."""
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
            if until_card and metadata.get('payment_intent'):
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


def busy(result):
    """This reply already has the one thing to approve or answer."""
    return bool(result.pending_action or result.payment_intent or result.rule_proposal
                or result.pending_categorization or result.pending_watch
                or any(action.get('type') in ('trade', 'form') for action in result.actions))


def ask(result, kind, question, data, lang):
    """The reply becomes this question, and nothing else (service.py)."""
    answer = {'es': 'Responde sí o no.', 'pt': 'Responda sim ou não.', 'en': 'Reply yes or no.'}[lang]
    result.pending_action = {'kind': kind, 'question': f'{question} {answer}', 'data': data, 'lang': lang}
    return {'ok': True, 'pregunta_enviada': question,
            'nota': ('Todavía no se preparó nada. El servidor le hace esa pregunta exacta en lugar de tu respuesta y, '
                     'si responde que sí, deja la tarjeta. No preguntes otra cosa ni llames otra herramienta.')}


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


def answer(conversation, viewer, text, pending, user_message, *, can_navigate=True):
    """The answer to that question: (done, reply, metadata), or None when this
    message is no such answer (then the model answers it, with nothing prepared)."""
    if (not pending or pending.get('user_id') != getattr(viewer.user, 'pk', None)
            or pending.get('account_id') != getattr(viewer.account, 'id', None)):
        return None
    metadata = user_message.metadata or {}
    if metadata.get('client_reported') or str(metadata.get('modality') or 'TEXT').upper() != 'TEXT':
        return None
    yes = is_yes(text, pending)
    if not yes and not is_no(text):
        return None
    # The very message before theirs, whoever wrote it: nothing came in between.
    previous = (conversation.messages.filter(created_at__lte=user_message.created_at).exclude(pk=user_message.pk)
                .order_by('-created_at', '-pk').values_list('pk', flat=True).first())
    if previous != pending.get('reply_id'):
        return None
    lang = pending.get('lang') if pending.get('lang') in ('es', 'pt', 'en') else 'es'
    if not yes:
        return False, {'es': 'Listo, no preparé nada.', 'pt': 'Certo, não preparei nada.',
                       'en': 'OK, I prepared nothing.'}[lang], {}
    from .engine import Toolbelt, TurnResult
    belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0, can_navigate=can_navigate)
    try:
        if pending.get('kind') == 'trade':
            from . import trades
            return trades.confirmed(belt, pending['data'], lang)
        if pending.get('kind') == 'payment':
            from . import sends
            return sends.confirmed(belt, pending['data'], lang)
    except Exception:  # noqa: BLE001 - a yes never becomes anything but that card or this line
        logger.exception('Confio Assistant: a confirmed action could not be prepared')
        return False, {'es': 'No pude prepararlo ahora. Inténtalo de nuevo.',
                       'pt': 'Não consegui preparar agora. Tente de novo.',
                       'en': "I couldn't prepare it now. Please try again."}[lang], {}
    return None
