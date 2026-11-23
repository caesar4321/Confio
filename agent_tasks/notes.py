"""What a task says in the assistant thread. Written by code, never by a model."""
import logging

logger = logging.getLogger(__name__)

STARTED = 'Voy a buscarlo en {site}. La compra la confirmas tú en la tienda y el pago lo apruebas tú aquí.'
# {pay}, {qr}, {paste} and {vouches} are the country's rail (countries.py).
CARRY_ON = (' Desde ahí sigue tú con la compra: elige {pay}, confirma el pedido y, con {qr} en pantalla, '
            'toca "Ya terminé".')
NEEDS_PERSON = {
    'login': 'Necesito que inicies sesión en {site}. La contraseña la escribes tú: no la veo ni la guardo. '
             'Solo inicia sesión: la compra la confirmas después.',
    'captcha': '{site} pide comprobar que eres una persona. Eso lo haces tú.',
    'details': '{site} pide datos que solo escribes tú.' + CARRY_ON,
    'choice': 'Hay algo que debes elegir tú en {site}.' + CARRY_ON,
    'consent': '{site} pide aceptar condiciones. Eso lo decides tú.' + CARRY_ON,
    'checkout': ('Te toca en {site}: revisa el producto, la cantidad y la dirección, elige {pay} y confirma el pedido. '
                 'Con {qr} a la vista, toca "Ya terminé": lo leo de la pantalla y te preparo el pago.'),
    'code': ('No vi {qr} completo en la pantalla. Muévela hasta que se vea todo y toca "Ya terminé". Si no '
             'aparece, {paste}.'),
    'several': ('Veo más de un dato de pago posible en la pantalla (dos QR, un QR distinto del código escrito al '
                'lado, uno pequeño como una foto de producto, o dos cuentas o montos), y no elijo por ti. Deja a la '
                'vista solo {qr} de tu pedido y toca "Ya terminé".'),
    'unsigned': ('A quien cobra ese QR no lo respalda una institución de pago conocida, así que no lo leo de la '
                 'pantalla. Si es el de tu pedido, {paste}: lo reviso contigo.'),
    'screen': ('No pude ver bien la pantalla. Vuelve a abrirla, cierra cualquier mensaje de {site} encima y, con el QR '
               'quieto y entero, toca "Ya terminé".'),
    'offsite': ('Esa pantalla no es de {site} (una página de pago la puede crear cualquiera), así que no leo su QR. '
                'Vuelve al pedido en la tienda y toca "Ya terminé", o {paste}.'),
    'retry': 'No pude preparar el pago ahora. Deja el QR en pantalla y toca "Ya terminé" en un momento.',
    'code_refused': ('No pude prepararte el pago con el código de {site}. Puedes intentarlo otra vez con "Ya terminé" '
                     'o {paste}.'),
}
MAYBE_NOT_ADDED = ' Puede que no se haya agregado al carrito: si no está, agrégalo tú.'
PAYMENT_READY = ('Preparé el pago con {qr} que se veía en {site}. {vouches} Antes de pagar revisa que el monto y el '
                 'cobro sean los de tu pedido.')
STOPPED = {
    'blocked': '{site} no me dejó continuar. No insistí. Puedes comprar tú y, para pagarlo, {paste}.',
    'not_found': 'No encontré lo que pediste en {site}.',
    'no_payment': '{site} no parece aceptar {pay}, así que no seguí.',
    'out_of_stock': 'Lo que pediste no está disponible en {site}.',
    'cannot_do': 'No pude completarlo en {site}. Puedes comprar tú y, para pagarlo, {paste}.',
    'cannot_pay': 'Ahora no puedo pagar una compra así desde tu cuenta, así que no te pedí que la confirmaras.',
    'too_long': 'Me estaba tomando demasiado y lo detuve. Puedes comprar tú y, para pagarlo, {paste}.',
    'person_timeout': 'Se acabó el tiempo para continuar en {site}. Pídemelo otra vez cuando quieras.',
    'session_expired': 'Se cerró la sesión del navegador antes de terminar.',
    'busy': 'Ahora no puedo abrir el navegador. Inténtalo más tarde.',
    'error': 'Algo falló y lo detuve. Puedes pedírmelo otra vez.',
    'cancelled': 'Listo, lo cancelé.',
    'replaced': 'Dejé la compra en {site} para empezar la nueva.',
    'unavailable': 'Ahora no puedo abrir el navegador para comprar por ti. Pídemelo más tarde.',
}
# After the hand-over, nothing may suggest there is no order.
AFTER_CHECKOUT = (' Si ya confirmaste el pedido, sigue en tus compras de {site}: para pagarlo, {paste}.')
TASK_ACTION = {'type': 'task', 'label': 'Abrir la tienda'}
PUSH = {'person': 'Te toca a ti', 'payment': 'Revisa tu pago', 'check': 'Revisa tu compra'}


def balance_line(task):
    """' Tienes US$… en dólares para pagarlo.' at the checkout, or '' when unknown."""
    from payment_accounts.shortfall import dollars_held, usd
    held = dollars_held(task.account)
    if held is None:
        return ''
    return (f' Tienes {usd(held, down=True)} en dólares. El pago se cobra en dólares con su comisión: si no '
            'te alcanza, te lo diré antes de pagar.')


def shortfall_line(task, intent):
    """' Te faltan US$…: recarga…' when the dollars held do not cover the card,
    or ''. Advisory: the card stays, the order stays open at the store."""
    from payment_accounts.shortfall import shortfall, usd
    total = getattr(intent, 'total_usd', None)
    missing = shortfall(task.account, total) if total is not None else None
    if missing is None:
        return ''
    return (f' Tu saldo en dólares no alcanza: te faltan {usd(missing)}. Recarga y vuelve a «Revisar y pagar» '
            'antes de que venza el pago en la tienda.')


def stopped_text(task, reason):
    text = STOPPED.get(reason, STOPPED['error'])
    # Also when they only took the screen to sign in: they may have bought then.
    if task.checkout_at or any(entry.get('did') == 'the person took the screen' for entry in task.history or []):
        text += AFTER_CHECKOUT
    return say(text, task)


def say(text, task):
    """A note's words for this task's store and its country's rail."""
    from . import countries
    rail = countries.rail(task.country)
    return text.format(site=task.site, pay=rail.name if rail else 'el pago',
                       qr=rail.qr if rail else 'el QR de pago',
                       paste=rail.paste if rail else 'abre el pedido en tu celular y págalo desde Confío',
                       vouches=rail.vouches if rail else '')


def post(task, body, tag, *, intent=None, push=None, push_body=None):
    """A system line that carries the task (or the payment card). Returns the
    message id, or None: a note never breaks a task. `push_body` is what the
    lock screen may show when it must say less than the chat (a balance)."""
    try:
        from assistant.service import post_system_note
        if intent is not None:
            from assistant.engine import PAYMENT_CHIP
            actions = [dict(PAYMENT_CHIP)]
        else:
            actions = [{**TASK_ACTION, 'target': str(task.internal_id)}]
        message, created = post_system_note(
            task.user, body, f'agent_task:{task.internal_id}:{tag}'[:120], actions=actions,
            payment_intent={'id': str(intent.internal_id)} if intent is not None else None)
        if created and push:
            _push(task, push_body if push_body is not None else body, push)
        return message.pk if message is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.error('agent task note was not posted: %s', type(exc).__name__)
        return None


def _push(task, body, kind):
    """A system note sends no push of its own, and these waits last minutes."""
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        create_notification(
            user=task.user, account=task.account, notification_type=NotificationType.SYSTEM, title=PUSH[kind],
            message=body, data={'type': 'agent_task', 'task_id': str(task.internal_id), 'screen': 'AssistantThread'})
    except Exception as exc:  # noqa: BLE001
        logger.warning('agent task push was not sent: %s', type(exc).__name__)
