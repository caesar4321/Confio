"""A payment from the chat (engine.prepare_payment).

A code that carries its own amount, pasted alone or with "paga esto", becomes
a card at once. Everything else (an @usuario, a key, an account, a saved Pago
Móvil name, an open code, a code talked about in any other words) is asked
first, by code, and prepared only on their yes (confirm.py). Who and how much are still the person's own words
(payment_intents.request_from_words); the question adds that they see both,
in dollars, before any card exists.
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
    if any(unicodedata.category(ch) in ('So', 'Sk') for ch in around):
        return False
    return confirm.plain(around) in _PAY_THIS


def _has_amount(code):
    from payment_accounts import local_money
    from payment_accounts.payment_intents import IntentRefused
    from payment_accounts.services import PaymentAccountError
    try:
        return bool(local_money.fixed_pix_charge(local_money.METHODS['br_qr'], code))
    except PaymentAccountError as exc:
        raise IntentRefused('no_code', str(exc)) from exc


def _reais(code):
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
    return f"{Decimal(found['amount']):.2f}".replace('.', ',')


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


def question(request, lang, named=''):
    from .trades import money
    who = _who(request, named)
    if request.get('amount_usd') in (None, ''):
        reais = _reais(request.get('code'))
        if reais:
            return {'es': f'¿Quieres pagar el código {who} por R${reais} (reales)?',
                    'pt': f'Você quer pagar o código {who} de R${reais}?',
                    'en': f'Do you want to pay code {who} for R${reais} (Brazilian reais)?'}[lang]
        return {'es': f'¿Quieres pagar el código {who} por el monto que trae?',
                'pt': f'Você quer pagar o código {who} pelo valor que ele traz?',
                'en': f'Do you want to pay code {who} for the amount it carries?'}[lang]
    amount = money(request['amount_usd'], lang)
    if request.get('code'):
        return {'es': f'¿Quieres pagar {amount} (dólares) con el código {who}?',
                'pt': f'Você quer pagar {amount} (dólares) com o código {who}?',
                'en': f'Do you want to pay {amount} (US dollars) with code {who}?'}[lang]
    return {'es': f'¿Quieres enviar {amount} (dólares) a {who}?',
            'pt': f'Você quer enviar {amount} (dólares) para {who}?',
            'en': f'Do you want to send {amount} (US dollars) to {who}?'}[lang]


def propose(belt, rail, recipient, amount_usd):
    """A PaymentIntent (a code sent to be paid, with its own amount) or the
    question that was asked. Raises IntentRefused with the reason for the person."""
    from payment_accounts import payment_intents as intents

    owner, user, meta = belt.viewer.account, belt.viewer.user, belt.viewer.request_meta
    named = ''
    if not rail:
        if recipient:
            # Named someone and no rail: an older code is never paid in their place.
            raise intents.IntentRefused('not_said', intents.MESSAGES['not_said'])
        latest = belt.payment_texts[0]
        texts = confirm.recent_texts(belt, until_card=True)
        code = intents.code_in_words(*texts)
        fixed = _has_amount(code)
        if fixed and _pay_at_once(latest, code):
            # The code's own amount, whatever the model passed.
            return intents.prepare_from_request(owner, user, [latest], meta=meta)
        if code not in latest and confirm.is_no(latest):
            raise intents.IntentRefused('not_asked', 'La persona dijo que no: no preparo ese código.')
        if fixed:
            amount_usd = None       # only ever the code's own
        elif amount_usd in (None, ''):
            raise intents.IntentRefused('no_amount', 'Este código no trae un monto. Dime cuántos dólares quieres pagar.')
    else:
        texts = confirm.requests(confirm.recent_texts(belt))
        named = str(recipient or '')
    if confirm.busy(belt.result):
        raise intents.IntentRefused('not_asked', 'Ya hay algo por responder en esta respuesta: una cosa por respuesta.')
    request, source = intents.request_from_words(owner, user, texts, rail=rail, recipient=recipient,
                                                 amount_usd=amount_usd, around=confirm.all_said(belt))
    lang = confirm.language(texts)
    stored = {key: (str(value) if key == 'amount_usd' and value is not None else value)
              for key, value in request.items() if key != 'meta'}
    return confirm.ask(belt.result, 'payment', question(request, lang, named), {'request': stored, 'source': source},
                       lang)


def confirmed(belt, data, lang):
    """The card of exactly what was asked. Nothing moves: the person signs it."""
    from decimal import Decimal

    from payment_accounts import payment_intents as intents
    from payment_accounts.services import PaymentAccountError

    from .engine import PAYMENT_CHIP, PAYMENT_PREPARED_REPLY

    if not belt.payments_ready():
        return False, 'No puedo preparar pagos desde aquí ahora. Hazlo en Enviar o en Pagar.', {}
    amount = data['request'].get('amount_usd')
    request = {**data['request'], 'amount_usd': Decimal(amount) if amount not in (None, '') else None,
               'meta': belt.viewer.request_meta}
    try:
        intent = intents.prepare(belt.viewer.account, belt.viewer.user, created_by='assistant', source=data['source'],
                                 request=request, retire_earlier=False)
    except PaymentAccountError as exc:
        return False, str(exc), {}
    reply = {'es': PAYMENT_PREPARED_REPLY,
             'pt': 'Preparei o pagamento. Confira quem recebe, o valor e o total no cartão abaixo; só é pago quando '
                   'você confirmar com Confío Face.',
             'en': 'I prepared the payment. Check who receives it, the amount and the total on the card below; it is '
                   'paid only when you confirm with Confío Face.'}[lang]
    return True, reply, {'actions': [dict(PAYMENT_CHIP)], 'payment_intent': {'id': str(intent.internal_id)}}
