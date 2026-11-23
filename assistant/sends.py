"""A payment from the chat (engine.prepare_payment).

A code that carries its own amount, pasted alone in its own message or with
"paga esto", becomes a card at once, whatever came before it (unless a "don't
pay" was said these last minutes). Such a code said any other way is asked
with a yes or no. Anything else (an @usuario, a
key, an account, a saved Pago Móvil name, a code with no amount) is asked
"¿Cuántos dólares …? Escribe solo el número", and the number they type is
the amount (confirm.py): how much is never read out of their words. Who is
still their own words (payment_intents.request_from_words), shown in the
question. A code said not to be paid is refused; a code whose card is still
open is not asked about again.
"""
import logging
import re
import unicodedata

from . import confirm

logger = logging.getLogger(__name__)

# A code and, at most, these words in that same message: a card at once (its amount is the code's own).
# Anything else about a code is asked: "¿quieres pagar el código ••ABCD?".
_PAY_THIS = frozenset((
    '', 'paga', 'paga por favor', 'pagalo', 'pagalo por favor', 'pagar', 'pagame', 'paga esto', 'paga esto por favor',
    'paga este', 'paga este codigo', 'paga ese codigo', 'paga el codigo', 'paga este pix', 'paga ese pix', 'paga el pix',
    'pagame este pix', 'pagame este pix por favor', 'pagame esto', 'quiero pagar', 'quiero pagar esto',
    'quiero pagar este pix', 'paga o pix', 'paga esse pix', 'pague', 'pague o pix', 'pague esse pix', 'pague este pix',
    'pague isso', 'quero pagar', 'quero pagar este pix', 'pay', 'pay this', 'pay it', 'pay this please',
))


def _pay_at_once(text, code):
    if code not in text:
        return False
    around = text.replace(code, ' ')
    if _said_not_to_pay(around):
        return False
    if any(unicodedata.category(ch) in ('So', 'Sk') for ch in around):
        return False
    return confirm.plain(around) in _PAY_THIS


def code_tag(code):
    """What a card made from this code keeps of it, to know it was served."""
    import hashlib
    return hashlib.sha256(str(code or '').encode()).hexdigest()[:16]


# Said around a code: it is not to be paid. It only refuses; the refusal ends what is read, so the code pasted again
# alone gets its card. A plain "don't pay / don't send it", in any of its forms (tú, usted, Portuguese, English):
_DONT = (r'(?:no|nunca|ni) (?:(?:me |te |se )?(?:lo|la|le|les|los|las) )?(?:pagues|paguen|pague|envies|envien|envie|'
         r'mandes|manden|mande|transfieras|transfieran|transfiera)\w*|'
         r'no (?:(?:me |se )?(?:lo|la|le) )?vayas a (?:pagar|enviar|mandar)\w*|no pagar|'
         r'no (?:quiero|queremos) que (?:(?:me |se )?(?:lo|la|le) )?(?:pagues|envies|mandes|transfieras)\w*|'
         r'ni se te ocurra (?:pagar|enviar|mandar|transferir)\w*|no se paga|'
         r'nao (?:o |a |lhe )?(?:pague|envie|mande|transfira|pagar|enviar|mandar|paga)\w*|'
         r'nao (?:quero|vou|vamos) (?:pagar|enviar|mandar)\w*|nem (?:o |a )?(?:pague|envie|mande)\w*|'
         r'dont (?:pay|send)|don t (?:want to )?(?:pay|send)|do not (?:want to )?(?:pay|send)|'
         r'won t (?:pay|send)|will not (?:pay|send)|'
         r'anul\w*|no (?:lo |la )?hagas|no hagas (?:ese|el|este) (?:pago|envio)|'
         r'(?:yo |mejor )?no (?:lo |la )?(?:pago|envio|mando)|no (?:lo |la )?(?:pienso|quiero|voy a|vamos a|hay que|'
         r'tengo que) (?:pagar|enviar|mandar|transferir)\w*|(?:ya )?no (?:lo |la )?quiero|cancel it')
_SCAM = r'estaf\w*|scam\w*|golpe|golpista\w*|fraud\w*'
_DECLINED = re.compile(r'\b(' + _SCAM + r'|' + _DONT + r'|no es mio|nao e meu|'
                       r'ya (?:lo |la )?(?:pague|pagamos|pagaron|pagaste)|ya (?:esta|estaba|fue) pagad[oa]|'
                       r'ya se pago|ya esta pago|ja paguei|ja foi pago|ja esta pago|already paid|paid (?:it )?already|'
                       r'no (?:lo |la )?(?:quiero|voy a|vamos a|hay que|tengo que) pagar\w*)\b')


def _said_not_to_pay(text, code=''):
    """They said not to pay it (or that it was paid). Withdrawing is the safe direction: an exception to it is
    read only where it is unmistakable."""
    raw = unicodedata.normalize('NFC', str(text or '').replace(code, ' ') if code else str(text or ''))
    paid_already = bool(re.search(r'(?<!\w)pagué(?!\w)', raw, re.IGNORECASE))
    # "pagué" (I paid) is kept apart from "pague" (pay / don't pay, usted): marked before accents are folded away.
    marked = re.sub(r'(?<!\w)pagué(?!\w)', ' pagado_yo ', raw, flags=re.IGNORECASE)
    # Folded but with its punctuation: "no es estafa" is a denial, "No, es estafa" never is.
    kept = ' '.join(_fold_keeping_marks(marked).split())
    kept = re.sub(r'\bde (?:un )?golpe\b', ' ', kept)                       # "págalo de (un) golpe": at once
    if not re.search(r'[?¿？]', raw):                                        # "¿no es estafa?" is a doubt
        kept = _NOT_A_SCAM.sub(' ', kept)
    said = confirm.plain(kept)
    declined = bool(_DECLINED.search(said)) or paid_already
    # "ya pagué la luz, ahora págalo", "no lo pagué ayer, págalo": told to pay it, unless told plainly not to.
    if declined and _PAY_IT.search(said) and not _DO_NOT_PAY.search(said):
        return False
    return declined


def _fold_keeping_marks(text):
    """Lowercase without accents, punctuation kept."""
    text = unicodedata.normalize('NFKD', str(text or '').lower())
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


_PAY_IT = re.compile(r'\b(?:pagalo|pagala|pagamelo|paga(?:lo|la)? (?:ya|ahora|igual)|ahora paga\w*|dale|hazlo|'
                     r'pode pagar|pague(?:-o)? sim|pay it|go ahead)\b')
_DO_NOT_PAY = re.compile(r'\b(?:' + _DONT + r'|' + _SCAM + r')\b')

# A denial said in one breath ("no es estafa", "não é golpe", "it's not a scam"): no comma or stop inside it.
_NOT_A_SCAM = re.compile(r"\b(?:no creo que (?:sea|es)|nao acho que (?:seja|e)|i don'?t think it'?s|no|nao|not|isn'?t|"
                         r"is not|it'?s not) (?:es |era |parece |hay |e |a |an )?"
                         r"(?:una? |um |ninguna? |nenhuma? |nenhum |any )?(?:estafa|scam|golpe|fraude|fraud)\b")


_LINES = {
    'served': {'es': 'Ese código ya tiene su tarjeta arriba: revísala y confírmala ahí.',
               'pt': 'Esse código já tem o cartão acima: confira e confirme lá.',
               'en': 'That code already has its card above: check it and confirm it there.'},
    'unknown': {'es': 'No pude revisar ese código ahora. Inténtalo de nuevo en un momento.',
                'pt': 'Não consegui verificar esse código agora. Tente de novo em um momento.',
                'en': "I couldn't check that code right now. Try again in a moment."},
    'no': {'es': 'Listo, no preparo ese pago.', 'pt': 'Certo, não preparo esse pagamento.',
           'en': "OK, I won't prepare that payment."},
    'how_many_pay': {'es': '¿Cuántos dólares quieres pagar con el código {who}?',
                     'pt': 'Quantos dólares você quer pagar com o código {who}?',
                     'en': 'How many dollars do you want to pay with code {who}?'},
    'how_many_send': {'es': '¿Cuántos dólares quieres enviar a {who}?',
                      'pt': 'Quantos dólares você quer enviar para {who}?',
                      'en': 'How many dollars do you want to send to {who}?'},
    'busy': {'es': 'Una cosa a la vez: cuando terminemos con esto, pídemelo de nuevo.',
             'pt': 'Uma coisa de cada vez: quando terminarmos isto, me peça de novo.',
             'en': 'One thing at a time: when we finish this, ask me again.'},
}


def _around(belt, code):
    """What they said with the code, after it, and in the same breath before it (no reply in between: before a
    reply, they were talking about something else), however they said it, these last minutes."""
    history = list(getattr(belt, 'turn_history', ()) or ())
    mine = [m for m in history if m.sender_type == 'USER' and (m.body or '').strip()]
    if not mine:
        return list(belt.payment_texts)
    latest, out, with_code = getattr(mine[-1], 'created_at', None), [], False
    for message in reversed(history):
        if message.sender_type != 'USER' or not (message.body or '').strip():
            if confirm._ends(message, 'untagged', code_tag(code)) or (with_code and message.sender_type == 'AGENT'):
                break
            continue
        sent = getattr(message, 'created_at', None)
        if latest and sent and latest - sent > confirm.WINDOW:
            break
        out.append(message.body)
        with_code = with_code or code in message.body
    return out


# Rows in these states have no order and no journey yet: withdrawing closes them for good.
_CLOSABLE = ('quoted', 'awaiting_signature', 'expired')


def withdraw_cards(account, message_ids, intent_ids):
    """Withdraw the cards on these chat messages: each message is marked withdrawn (payment_intents.prepare
    refuses a new card on it, so no re-quote of any of its ids revives it), and every row that has no order or
    journey yet is cancelled. What the person is told comes back:
    'withdrawn' (nothing of it can be paid any more), 'signing' (an order or journey exists and still waits for
    their signature: they must not sign it), 'paid' (money may have moved, or it can't be told), 'none' (no card
    of theirs is there)."""
    from django.db import transaction
    from django.db.models import Q
    from django.utils import timezone

    from inbox.models import SupportMessage
    from payment_accounts import payment_intents
    from payment_accounts.models import PaymentIntent
    message_ids = [pk for pk in message_ids if isinstance(pk, int)]
    with transaction.atomic():
        # The same row lock prepare takes before a card on this message: a re-quote either finished before this
        # (its row is cancelled below) or sees the mark and is refused.
        for message in SupportMessage.objects.select_for_update().filter(pk__in=message_ids):
            message.metadata = {**(message.metadata or {}), 'withdrawn': True}
            message.save(update_fields=['metadata'])
        # Locked, as a confirmation locks them (journey_guard): one that lands meanwhile is seen here, never
        # overwritten, and what is said comes from these locked rows.
        rows = list(PaymentIntent.objects.select_for_update().filter(
            Q(internal_id__in=[str(i) for i in intent_ids if i]) | Q(message_id__in=message_ids),
            confio_account=account).order_by('pk'))
        PaymentIntent.objects.filter(pk__in=[r.pk for r in rows if r.state in _CLOSABLE],
                                     state__in=_CLOSABLE).update(
            state='cancelled', state_reason='declined_in_chat', updated_at=timezone.now())
    # Withdrawn now = a live card closed: open or awaiting its signature, or expired on a card that went no further
    # (an old quote beside a re-quote that was paid is not "that card").
    went_further = {r.message_id for r in rows if r.state == 'submitted'}
    cancelled_now = any(r.state in ('quoted', 'awaiting_signature')
                        or (r.state == 'expired' and r.message_id not in went_further) for r in rows)
    if not rows:
        return Withdrawal('none')
    signing = paid = False
    for row in rows:
        if row.state in _CLOSABLE or row.state == 'cancelled':
            continue
        try:
            shown, _journey = payment_intents.status(row)
        except Exception:  # noqa: BLE001 - not known: said as possibly paid
            logger.warning('Confio Assistant: a withdrawn card\'s status is unknown', exc_info=True)
            shown = 'unknown'
        if shown == 'awaiting_signature':
            signing = True               # its order or journey waits for their signature: they must not sign
        elif shown not in ('quoted', 'expired', 'cancelled'):
            paid = True
    # What was withdrawn now leads; what else was found among the same cards is said beside it.
    first = 'withdrawn' if cancelled_now or not (signing or paid) else 'signing' if signing else 'paid'
    return Withdrawal(first, signing=signing and first != 'signing', paid=paid and first != 'paid')


class Withdrawal(str):
    """withdraw_cards' outcome ('withdrawn', 'signing', 'paid', 'none'), with what else was found beside it."""

    def __new__(cls, outcome, signing=False, paid=False):
        made = super().__new__(cls, outcome)
        made.signing, made.paid = signing, paid
        return made


def _retire_open_cards(belt, code):
    """Said not to pay it: the cards of this code are withdrawn."""
    tag = code_tag(code)
    # The cards of these last minutes, from the thread itself: one a few quick exchanges back is still open.
    carrying = [m for m in confirm.last_minutes(list(getattr(belt, 'turn_history', ()) or ()))
                if isinstance((m.metadata or {}).get('payment_intent'), dict)
                and m.metadata['payment_intent'].get('code') == tag]
    if carrying:
        return withdraw_cards(belt.viewer.account, [getattr(m, 'pk', None) for m in carrying],
                              [m.metadata['payment_intent'].get('id') for m in carrying])
    return 'none'


def withdraw_declined(conversation, viewer, text, user_message):
    """"No lo pagues", "es estafa" right under a code's card: code withdraws that card, whatever the model would
    do. The answer for confirm-style replies (service._answer_to_question), or None."""
    metadata = user_message.metadata or {}
    # A voice note or a caption saying "no lo pagues" withdraws too: withdrawing is the safe direction.
    if metadata.get('client_reported'):
        return None
    codes = intents_codes(text)
    if not _said_not_to_pay(_without(text, codes)):
        return None
    return _withdraw(conversation, viewer, text, user_message, codes, named=True)


def withdraw_on_request(conversation, viewer, user_message):
    """The model's own reading that the person does not want the card right above paid (any wording): the same
    withdrawal, with the same answer. Withdrawing is the safe direction. None when no card is right above."""
    text = str(getattr(user_message, 'body', '') or '')
    return _withdraw(conversation, viewer, text, user_message, intents_codes(text), named=False)


def _withdraw(conversation, viewer, text, user_message, codes, named):
    """Every card the "no" is about, withdrawn together, and one answer: the card right above, and (`named`, the
    words' own path) the open cards of a code written in the "no" from the thread's last minutes, wherever they
    are (a card scanned under it must not hide the code's own card)."""
    messages, ids, tags = [], [], []
    above = _card_above(conversation, text, user_message, codes)
    if above is not None:
        previous, card = above
        messages.append(previous.pk)
        ids.append(card.get('id'))
        tags.append(card.get('code') or '')
    if named and codes:
        wanted = {code_tag(code) for code in codes}
        found = [m for m in confirm.last_minutes([user_message])
                 if m.pk != user_message.pk and m.pk not in messages and m.sender_type in ('AGENT', 'SYSTEM')
                 and isinstance((m.metadata or {}).get('payment_intent'), dict)
                 and m.metadata['payment_intent'].get('code') in wanted]
        # The card right above, when it is this code's, counts among the code's cards: an open one there keeps
        # an older card already paid out.
        mine = [previous] if above is not None and card.get('code') in wanted else []
        open_ones = _with_open_rows(viewer.account, mine + found)
        if open_ones:
            # An older card of the code already paid is left out; one paid after an open card is said beside it.
            since = min(m.created_at for m in open_ones)
            chosen = [m for m in found if m in open_ones or m.created_at > since]
        else:
            chosen = found
        for message in chosen:
            card = message.metadata['payment_intent']
            messages.append(message.pk)
            ids.append(card.get('id'))
            tags.append(card.get('code'))
    if not messages:
        return None
    outcome = withdraw_cards(viewer.account, messages, ids)
    tag = next((t for t in reversed(tags) if t), '')
    return _withdrawal_answer(outcome, bool(tag), text, confirm.language([text]), refused_code=tag)


def _with_open_rows(account, messages):
    """Those of these card messages that still have a row that can be signed or re-quoted (never an older card
    of the same code already paid)."""
    if not messages:
        return []
    from django.db.models import Q

    from payment_accounts import payment_intents
    from payment_accounts.models import PaymentIntent
    try:
        rows = list(PaymentIntent.objects.filter(
            Q(message_id__in=[m.pk for m in messages])
            | Q(internal_id__in=[str(m.metadata['payment_intent'].get('id')) for m in messages
                                 if m.metadata['payment_intent'].get('id')]),
            confio_account=account))
        went_further = {r.message_id for r in rows if r.state == 'submitted'}

        def still_open(row):
            if row.state in ('quoted', 'awaiting_signature'):
                return True
            if row.state == 'expired':
                return row.message_id not in went_further     # a re-quote of it went on: that card was paid
            if row.state == 'submitted' and not row.outcome:
                try:
                    return payment_intents.status(row)[0] == 'awaiting_signature'     # waits for their signature
                except Exception:  # noqa: BLE001 - not known: open (withdrawing is the safe direction)
                    return True
            return False

        live = [r for r in rows if still_open(r)]
        open_messages = {r.message_id for r in live}
        open_ids = {str(r.internal_id) for r in live}
    except Exception:  # noqa: BLE001 - not known: every one of them (withdrawing is the safe direction)
        logger.warning('Confio Assistant: open cards unknown', exc_info=True)
        return list(messages)
    return [m for m in messages if m.pk in open_messages or str(m.metadata['payment_intent'].get('id')) in open_ids]


def _card_above(conversation, text, user_message, codes):
    """(message, card) of the payment card right above the "no", or None."""
    codes = list(codes)
    # The card right above "no lo pagues": a card scanned in the chat (a SYSTEM line with its card) counts; any
    # other server line is passed over.
    # Their own lines right before it ("espera", then "no lo pagues") are passed over too: the card is the
    # newest one above, as long as nothing but their own words came after it.
    previous, own = None, 0
    for message in (conversation.messages.filter(created_at__lte=user_message.created_at).exclude(pk=user_message.pk)
                    .order_by('-created_at', '-pk')[:20]):
        carries = isinstance((message.metadata or {}).get('payment_intent'), dict)
        if message.sender_type == 'SYSTEM' and not carries:
            continue
        if message.sender_type == 'AGENT' and (message.metadata or {}).get('limit'):
            continue                     # the day's-limit notice is code's, never a reply about anything
        if message.sender_type == 'USER' and own < 3:
            codes += [c for c in intents_codes(message.body) if c not in codes]
            own += 1
            continue
        previous = message
        break
    card = (previous.metadata or {}).get('payment_intent') if previous is not None else None
    # Any card right above: the assistant's (from a pasted code or from a typed amount) or one scanned in the chat.
    if previous is None or previous.sender_type not in ('AGENT', 'SYSTEM') or not isinstance(card, dict) or not (
            card.get('id') or card.get('code')):
        return None
    if card.get('code') and any(code_tag(code) != card.get('code') for code in codes):
        return None          # another code, newer than the card: "no, ese no lo pagues" is about that one
    # A card scanned in the chat or from a store carries no code tag: a code pasted with the "no" may be its own,
    # and withdrawing the card above is the safe reading.
    return previous, card


def _withdrawal_answer(outcome, from_code, text, lang, refused_code=''):
    """What code says after a withdrawal, following what was found: (True, text, extra)."""
    again = {'es': ' Si después quieres pagar ese código, pégalo de nuevo en un mensaje solo.',
             'pt': ' Se depois quiser pagar esse código, cole de novo numa mensagem só com ele.',
             'en': ' If you want to pay that code later, paste it again in a message of its own.'}[lang] if from_code \
        else {'es': ' Si después lo quieres, pídemelo de nuevo.', 'pt': ' Se depois quiser, me peça de novo.',
                      'en': ' If you want it later, ask me again.'}[lang]
    # "¿esto es estafa?": a doubt, not only a no. The card goes, and the doubt gets an answer too.
    doubt = {'es': ' Cuéntame tu duda sobre ese pago y te ayudo.',
             'pt': ' Me conte sua dúvida sobre esse pagamento e eu te ajudo.',
             'en': " Tell me what you'd like to know about that payment and I'll help."}[lang] if re.search(
        r'[?¿？]', str(text or '')) else ''
    beside = (_ALSO_SIGNING[lang] if getattr(outcome, 'signing', False) else '') + (
        _ALSO_PAID[lang] if getattr(outcome, 'paid', False) else '')
    if outcome == 'withdrawn':
        return True, {'es': 'Listo: retiré esa tarjeta, ya no se puede pagar desde ahí.',
                      'pt': 'Pronto: retirei esse cartão, ele não pode mais ser pago.',
                      'en': "Done: I withdrew that card, it can't be paid anymore."}[lang] + beside + again + doubt, {
            'declined': True, 'refused_code': refused_code}
    if outcome in ('signing', 'none'):
        return True, _STILL_YOURS[outcome][lang] + beside + doubt, {'declined': True}
    return True, {'es': 'Esa tarjeta ya no está pendiente: si ya la confirmaste, desde aquí no se puede deshacer. '
                        'Revisa el pago en tus movimientos.',
                  'pt': 'Esse cartão não está mais pendente: se você já confirmou, daqui não dá para desfazer. Confira '
                        'o pagamento nos seus movimentos.',
                  'en': "That card is no longer pending: if you already confirmed it, it can't be undone from here. "
                        'Check the payment in your activity.'}[lang] + doubt, {'declined': True}


_ALSO_SIGNING = {'es': ' Ojo: otro pago de ese código ya está esperando tu firma: no lo firmes.',
                 'pt': ' Atenção: outro pagamento desse código já espera sua assinatura: não assine.',
                 'en': ' Note: another payment of that code is already waiting for your signature: do not sign it.'}
_ALSO_PAID = {'es': ' Otro pago de ese código ya se había hecho o está en curso: revísalo en tus movimientos.',
              'pt': ' Outro pagamento desse código já foi feito ou está em andamento: confira nos seus movimentos.',
              'en': ' Another payment of that code was already made or is under way: check it in your activity.'}


def _warned(belt, code):
    """A "don't pay" or scam word said these last minutes, past other cards and "no"s, back to code's own answer
    about this very code (its refusal, or its card withdrawn: "paste it again alone")."""
    tag = code_tag(code)
    history = _last_minutes(list(getattr(belt, 'turn_history', ()) or ()))
    mine = [m for m in history if m.sender_type == 'USER' and (m.body or '').strip()]
    latest = getattr(mine[-1], 'created_at', None) if mine else None
    for message in reversed(history):
        if message.sender_type != 'USER':
            metadata = message.metadata or {}
            if metadata.get('refused_code') == tag:
                return False
            sent = getattr(message, 'created_at', None)
            # The team's own "no lo pagues, es estafa" (a reply or a notice, never the assistant's words).
            if (message.sender_type == 'AGENT' and not metadata.get('ai') and not (latest and sent
                                                                                    and latest - sent > confirm.WINDOW)
                    and _said_not_to_pay(message.body or '', code)):
                return True
            continue
        sent = getattr(message, 'created_at', None)
        if latest and sent and latest - sent > confirm.WINDOW:
            break
        if _said_not_to_pay(message.body or '', code):
            return True
    return False


_last_minutes = confirm.last_minutes


def _without(text, codes):
    text = str(text or '')
    for code in codes:
        text = text.replace(code, ' ')
    return text


def intents_codes(text):
    from payment_accounts.payment_intents import find_pix_codes
    return find_pix_codes(str(text or ''))


_STILL_YOURS = {
    'signing': {
        'es': 'Ese pago ya está esperando tu firma: no lo firmes. Si no lo firmas, no sale nada y se cierra solo. '
              'Si ya lo firmaste, desde aquí no se puede deshacer: revisa tus movimientos.',
        'pt': 'Esse pagamento já está esperando sua assinatura: não assine. Se você não assinar, nada sai e ele se '
              'fecha sozinho. Se já assinou, daqui não dá para desfazer: confira seus movimentos.',
        'en': "That payment is already waiting for your signature: don't sign it. If you don't, nothing leaves "
              "and it closes on its own. If you already signed it, it can't be undone from here: check your "
              'activity.'},
    'none': {
        'es': 'No encontré esa tarjeta en esta cuenta para retirarla. No la pagues; si quieres, cuéntame qué pasó.',
        'pt': 'Não encontrei esse cartão nesta conta para retirá-lo. Não pague; se quiser, me conte o que houve.',
        'en': "I couldn't find that card in this account to withdraw it. Don't pay it; tell me what happened if "
              'you like.'},
}
_EARLIER = {'es': ' Ojo: un pago anterior de ese código ya estaba esperando tu firma o en curso: no lo firmes y '
                  'revisa tus movimientos.',
            'pt': ' Atenção: um pagamento anterior desse código já esperava sua assinatura ou estava em andamento: '
                  'não assine e confira seus movimentos.',
            'en': ' Note: an earlier payment of that code was already waiting for your signature or under way: '
                  "don't sign it and check your activity."}


_WITHDREW_EARLIER = {'es': ' También retiré la tarjeta anterior de ese código.',
                     'pt': ' Também retirei o cartão anterior desse código.',
                     'en': ' I also withdrew the earlier card of that code.'}


def _declined_reply(lang):
    return {'es': 'No preparé el pago de ese código: en lo que escribiste aparece algo como «no lo pagues», «ya lo '
                  'pagué» o «estafa». Si quieres pagarlo, pégalo de nuevo en un mensaje solo.',
            'pt': 'Não preparei o pagamento desse código: no que você escreveu aparece algo como «não pague», «já '
                  'paguei» ou «golpe». Se quiser pagá-lo, cole de novo numa mensagem só com ele.',
            'en': "I didn't prepare that code's payment: what you wrote says something like \"don't pay\", "
                  '"already paid" or "scam". If you want to pay it, paste it again in a message of its own.'}[lang]


def _has_amount(code):
    from payment_accounts import local_money
    from payment_accounts.payment_intents import IntentRefused
    from payment_accounts.services import PaymentAccountError
    try:
        return bool(local_money.fixed_pix_charge(local_money.METHODS['br_qr'], code))
    except PaymentAccountError as exc:
        raise IntentRefused('no_code', str(exc)) from exc


def _reais(code, lang='es'):
    """The amount a static code states, as "550,00"; '' when only the Pix network knows it."""
    from decimal import Decimal

    from payment_accounts import local_money
    from payment_accounts.services import PaymentAccountError
    try:
        found = local_money.pix_code(str(code or ''))
    except PaymentAccountError:
        return ''
    if found['dynamic'] or not found['amount']:
        return ''
    text = f"{Decimal(found['amount']):,.2f}"
    return text if lang == 'en' else text.replace(',', '_').replace('.', ',').replace('_', '.')


def _who(request, named=''):
    from payment_accounts import intent_rails
    method = request.get('method_id')
    if method == intent_rails.CONFIO_SEND:
        return f"@{str(request['recipient']).lstrip('@')}"
    if method == intent_rails.VE_PAGOMOVIL:
        phone = re.sub(r'[^0-9]', '', str(request.get('phone') or ''))
        # Their own saved account has no holder: the name they saved it by (checked against their Agenda).
        holder = ' '.join(str(request.get('holder_name') or named or '').split())[:60]
        return f'{holder} (Pago Móvil ••{phone[-4:]})'
    if method:
        label = {'br_pix': 'Pix', 'ar_cvu': 'CVU/CBU', 'co_breb': 'Bre-B', 'mx_clabe': 'CLABE'}.get(method, method)
        value = str(request.get('value') or '')
        value = value if len(value) <= 100 else f'{value[:60]}…{value[-30:]}'
        return f'{label} {value}'
    return f"•••{str(request.get('code') or '')[-4:]}"


def question(request, lang):
    """The yes/no for a code that carries its own amount."""
    who = _who(request)
    reais = _reais(request.get('code'), lang)
    if reais:
        return {'es': f'¿Quieres pagar el código {who} por R${reais} (reales)? La tarjeta te muestra cuánto es en '
                      'dólares.',
                'pt': f'Você quer pagar o código {who} de R${reais}? O cartão mostra quanto é em dólares.',
                'en': f'Do you want to pay code {who} for R${reais} (Brazilian reais)? The card shows it in US '
                      'dollars.'}[lang]
    return {'es': f'¿Quieres pagar el código {who} por el monto que trae? La tarjeta te lo muestra en dólares.',
            'pt': f'Você quer pagar o código {who} pelo valor que ele traz? O cartão mostra em dólares.',
            'en': f'Do you want to pay code {who} for the amount it carries? The card shows it in US dollars.'}[lang]


def propose(belt, rail, recipient):
    """A PaymentIntent (a code with its own amount, pasted alone) or the question that was asked. Raises
    IntentRefused with the reason for the person. How many dollars is never an argument: code asks."""
    from payment_accounts import payment_intents as intents

    owner, user, meta = belt.viewer.account, belt.viewer.user, belt.viewer.request_meta
    named = ''
    if not rail:
        if recipient:
            # Named someone and no rail: an older code is never paid in their place.
            raise intents.IntentRefused('not_said', intents.MESSAGES['not_said'])
        latest = belt.payment_texts[0]
        lang = confirm.language(confirm.all_said(belt) or [latest])
        # A code that already got a card is never read from an older message (its card answered it).
        served = confirm.served_codes(belt)
        texts = [text for at, text in enumerate(confirm.recent_texts(belt, until_card='untagged'))
                 if at == 0 or not any(code_tag(found) in served for found in intents.find_pix_codes(text))]
        code = intents.code_in_words(*texts)
        # Said not to pay it, in the message with it, after it, or just before it (however said, these last
        # few minutes since the last card or "no"): refused, and that ends what is read.
        if any(_said_not_to_pay(text, code) for text in _around(belt, code)):
            belt.result.refused_code = code_tag(code)
            earlier = _retire_open_cards(belt, code)
            raise intents.IntentRefused('declined', _declined_reply(lang) + (
                _WITHDREW_EARLIER[lang] if earlier == 'withdrawn' else '') + (
                _EARLIER[lang] if earlier in ('signing', 'paid') or getattr(earlier, 'signing', False)
                or getattr(earlier, 'paid', False) else ''))
        if code not in latest and confirm.is_no(latest):
            belt.result.refused_code = code_tag(code)
            raise intents.IntentRefused('declined', _LINES['no'][lang])
        # A code whose card can still be signed is not asked about again; pasted again, it says so.
        open_tags = confirm.served_codes(belt, open_only=True)
        if open_tags is None:
            raise intents.IntentRefused('not_asked', _LINES['unknown'][lang])
        if code_tag(code) in open_tags:
            raise intents.IntentRefused('not_asked', _LINES['served'][lang])
        if confirm.busy(belt.result):
            raise intents.IntentRefused('not_asked', _LINES['busy'][lang])
        fixed = _has_amount(code)
        # Pasted alone in its own message (or with "paga esto"), whatever came before it (founder, 2026-11-23): the
        # code's own amount, and the card is signed on the phone. A "don't pay" said these last minutes, even
        # before a reply, still means code asks first.
        warned = _warned(belt, code)
        if fixed and not warned and _pay_at_once(latest, code):
            intent = intents.prepare_from_request(owner, user, [latest], meta=meta)
            intent.code_tag = code_tag(code)
            return intent
        request, source = intents.request_from_words(owner, user, [text for text in texts if code in text],
                                                     meta=meta)
        stored = _stored(request)
        if fixed:
            return confirm.ask(belt.result, 'payment', question(request, lang), {'request': stored, 'source': source},
                               lang)
        return confirm.ask_amount(belt.result, 'payment', _LINES['how_many_pay'][lang].format(who=_who(request)),
                                  {'request': stored, 'source': source}, lang)
    texts = confirm.requests(confirm.recent_texts(belt))
    named = str(recipient or '')
    lang = confirm.language(texts)
    if confirm.busy(belt.result):
        raise intents.IntentRefused('not_asked', _LINES['busy'][lang])
    request, source = intents.request_from_words(owner, user, texts, rail=rail, recipient=recipient, meta=meta)
    return confirm.ask_amount(belt.result, 'payment', _LINES['how_many_send'][lang].format(who=_who(request, named)),
                              {'request': _stored(request), 'source': source}, lang)


def _stored(request):
    stored = {key: (str(value) if key == 'amount_usd' and value is not None else value)
              for key, value in request.items() if key != 'meta'}
    if request.get('code'):
        stored['code_tag'] = code_tag(request['code'])
    return stored


def _failed(lang):
    return {'es': 'No pude prepararlo ahora. Inténtalo de nuevo.', 'pt': 'Não consegui preparar agora. Tente de novo.',
            'en': "I couldn't prepare it now. Please try again."}[lang]


def confirmed(belt, data, lang):
    """The card of exactly what was asked. Nothing moves: the person signs it."""
    from decimal import Decimal

    from payment_accounts import payment_intents as intents
    from payment_accounts.services import PaymentAccountError

    from .engine import PAYMENT_CHIP, PAYMENT_PREPARED_REPLY

    if not belt.payments_ready():
        return False, {'es': 'No puedo preparar pagos desde aquí ahora. Hazlo en Enviar o en Pagar.',
                       'pt': 'Não consigo preparar pagamentos daqui agora. Faça em Enviar ou em Pagar.',
                       'en': "I can't prepare payments from here right now. Use Enviar or Pagar."}[lang], {}
    amount = data['request'].get('amount_usd')
    code = data['request'].get('code')
    if amount in (None, '') and not (code and _has_amount(code)):
        return False, _failed(lang), {}     # never a card without the number they typed (or the code's own)
    request = {**{key: value for key, value in data['request'].items() if key != 'code_tag'},
               'amount_usd': Decimal(amount) if amount not in (None, '') else None, 'meta': belt.viewer.request_meta}
    try:
        intent = intents.prepare(belt.viewer.account, belt.viewer.user, created_by='assistant', source=data['source'],
                                 request=request, retire_earlier=False)
    except PaymentAccountError as exc:
        # Too few dollars: the top-up form under the refusal where they top up from the chat.
        from payment_accounts.shortfall import is_short_of_dollars, missing_of, usd
        actions = []
        if is_short_of_dollars(exc):
            form = _topup_form(belt, actions)
            missing = missing_of(exc)
            if lang != 'es':
                # The rail's words are Spanish: what is missing, said in theirs.
                short = {'pt': 'Seu saldo em dólares não é suficiente para este pagamento' + (
                             f': faltam {usd(missing)}.' if missing is not None else '.') + (
                             ' Recarregue com o formulário abaixo e me peça de novo.' if form else
                             ' Recarregue e me peça de novo.'),
                         'en': 'Your dollar balance is not enough for this payment' + (
                             f': {usd(missing)} is missing.' if missing is not None else '.') + (
                             ' Top up with the form below and ask me again.' if form else
                             ' Top up and ask me again.')}[lang]
                return False, short, ({'actions': actions} if actions else {})
        return False, (str(exc) if lang == 'es' else {
            'pt': 'Não consegui preparar agora. Tente de novo ou use Pagar.',
            'en': "I couldn't prepare it right now. Try again or use Pagar."}[lang]), (
        {'actions': actions} if actions else {})
    send = not request.get('code')
    reply = {'es': (PAYMENT_PREPARED_REPLY if not send else
                    'Preparé el envío. Revisa a quién le envías, el monto y el total en la tarjeta de abajo; se envía '
                    'solo cuando lo confirmas con Confío Face.'),
             'pt': ('Preparei o envio. Confira quem recebe, o valor e o total no cartão abaixo; só é enviado quando '
                    'você confirmar com Confío Face.' if send else
                    'Preparei o pagamento. Confira quem recebe, o valor e o total no cartão abaixo; só é pago quando '
                    'você confirmar com Confío Face.'),
             'en': ('I prepared the transfer. Check who receives it, the amount and the total on the card below; it '
                    'is sent only when you confirm with Confío Face.' if send else
                    'I prepared the payment. Check who receives it, the amount and the total on the card below; it '
                    'is paid only when you confirm with Confío Face.')}[lang]
    card = {'id': str(intent.internal_id)}
    if data['request'].get('code_tag'):
        card['code'] = data['request']['code_tag']
    actions = [dict(PAYMENT_CHIP)]
    return True, reply + _short_note(belt, intent, lang, actions), {'actions': actions, 'payment_intent': card}


def _topup_form(belt, actions):
    """Add the top-up form where this person tops up from the chat. True if added."""
    try:
        from . import here, topup_limits
        from .engine import SHORT_TOPUP_FORM
        if topup_limits.offered(belt) and 'topup' in here.forms_for(belt.viewer, belt):
            actions.append(dict(SHORT_TOPUP_FORM, label=here.FORMS['topup'][0]))
            return True
    except Exception:  # noqa: BLE001 - the words stand without the form
        logger.warning('Confio Assistant: top-up form for a short payment failed', exc_info=True)
    return False


def _short_note(belt, intent, lang, actions):
    """' Te faltan US$…' when the dollars held do not cover the card, with the
    top-up form beside it where this person tops up from the chat. Advisory."""
    from payment_accounts.shortfall import shortfall, usd
    total = getattr(intent, 'total_usd', None)
    missing = shortfall(getattr(belt.viewer, 'account', None), total) if total is not None else None
    if missing is None:
        return ''
    form = _topup_form(belt, actions)
    amount = usd(missing)
    return {
        'es': f' Tu saldo en dólares no alcanza: te faltan {amount}.' + (
            ' Recarga con el formulario de abajo y después confirma.' if form else ' Recarga antes de confirmar.'),
        'pt': f' Seu saldo em dólares não é suficiente: faltam {amount}.' + (
            ' Recarregue com o formulário abaixo e depois confirme.' if form else ' Recarregue antes de confirmar.'),
        'en': f' Your dollar balance is not enough: {amount} is missing.' + (
            ' Top up with the form below, then confirm.' if form else ' Top up before you confirm.'),
    }[lang]
