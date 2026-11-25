"""What a task says in the assistant thread. Written by code, never by a model."""
import logging
import re

logger = logging.getLogger(__name__)

STARTED = 'Voy a buscarlo en {site}.'
# {pay}, {qr}, {paste} and {vouches} are the country's rail (countries.py).
CARRY_ON = (' Desde ahí sigue tú con la compra: elige {pay}, confirma el pedido y, con {qr} en pantalla, '
            'toca "Ya terminé".')
NEEDS_PERSON = {
    # What is true (vault.py): kept, encrypted, used only to sign in there, and theirs to delete.
    'login': ('Para comprar en {site} necesito entrar con tu cuenta de esa tienda. Escríbela en la tarjeta: se '
              'guarda cifrada y solo se usa para iniciar sesión ahí. Puedes borrarla cuando quieras en «Tiendas '
              'con tu sesión».'),
    'login_again': '{site} no me dejó entrar con esos datos. Revísalos y escríbelos otra vez.',
    'otp': '{site} te envió un código de verificación. Escríbelo en la tarjeta.',
    # {{item}} and {{total}} are the order's (operate._order).
    # Fixed words: what the store wrote (the item, the total) is shown only on the card.
    # A request about an order already placed (manage.py), named and approved before it is sent.
    'act': 'En {site} está lista tu solicitud: «{{what}}». ¿La envío?',
    # The click judge could not tell: never a dead end, the person says yes or no.
    'step': '{site} pide «{{step}}» para seguir. No sé si conviene: ¿lo hago?',
    'approve': 'Tu pedido en {site} está listo, a pagar con {pay}. Revísalo en la tarjeta y confírmalo: lo hago yo.',
    # Not a Cuenta inteligente subscriber (spec decision 37): the priced order, and the way to have it bought.
    'subscribe': ('Tu pedido en {site} está listo. Para que lo compre y lo pague yo, activa Cuenta inteligente; '
                  'después vuelve aquí y te lo muestro para confirmarlo.'),
    # Confío cannot pay this one: said before they confirm, so nobody orders what they cannot pay.
    'approve_manual': ('Tu pedido en {site} está listo. Esta vez no puedo pagarlo yo: cuando lo haga, te muestro '
                       '{qr} y lo pagas tú desde tu banco con {pay}. Si puedes pagarlo así, confírmalo en la '
                       'tarjeta y lo hago.'),
    'captcha': '{site} pide comprobar que eres una persona. Eso lo haces tú.',
    'choose': 'Encontré estas opciones en {site}. Elige una y yo sigo.',
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
# Confío cannot pay this country's code now (QR Bolivia off): the order is placed and the person pays it.
PAYMENT_MANUAL = ('Tu pedido en {site} está hecho. Abajo tienes {qr} tal como lo muestra la tienda: págalo tú '
                  'desde la app de tu banco. Nadie en Confío verificó a quién pertenece la cuenta: antes de pagar '
                  'revisa que sea la tienda y que el monto sea {{total}}.')
# After it, when a local account would let Confío pay the next one.
OPEN_ACCOUNT = ' Si abres tu cuenta local en Confío, la próxima vez lo pago yo.'
PAYMENT_READY = ('Preparé el pago con {qr} que se veía en {site}. {vouches} Antes de pagar revisa que el monto y el '
                 'cobro sean los de tu pedido.')
# An order already placed (manage.py).
MANAGED = 'Esto muestra {site}: {{text}}'
SENT = 'Envié tu solicitud en {site}; revísala en tus pedidos de {site}.'
# How a request ended when it did not end well: never purchase words ("compra tú"), never "nothing happened"
# after it was sent.
MANAGE_ENDED = 'No pude terminarlo en {site} y no envié ninguna solicitud. Puedes revisarlo en tus pedidos de {site}.'
STOPPED = {
    'answered': 'Esto muestra {site}: {{text}}',
    'request_unclear': ('Envié tu solicitud en {site}, pero no alcancé a ver su resultado. Revísala en tus pedidos de '
                        '{site}; no la envíes otra vez sin revisar.'),
    'declined': 'Listo, no envié nada a {site}.',
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
    'sign_in': 'No pude entrar a tu cuenta de {site}, así que no seguí. Pídemelo otra vez cuando quieras.',
    'unpaid': ('No pude preparar el pago de tu pedido en {site} desde aquí. Puede que el pedido haya quedado hecho '
               'y esté esperando el pago: revísalo en tus compras de {site}.'),
    'cancelled_ordered': ('Dejé de seguir esta compra. Puede que el pedido haya quedado hecho en {site}: revísalo en '
                          'tus compras de la tienda.'),
    'unavailable': 'Ahora no puedo abrir el navegador para comprar por ti. Pídemelo más tarde.',
    # Any store may be searched (founder, 2026-11-25); paying it is what depends on the country.
    'no_rail': ('Encontré lo que elegiste en {site}, pero todavía no puedo pagar tiendas de {{country}}, así que no '
                'lo compré. Hoy pago tiendas de México con SPEI, de Brasil con Pix y de Bolivia con QR. Puedes '
                'comprarlo tú directamente en {site}.'),
}
COUNTRY_NAMES = {'AR': 'Argentina', 'BO': 'Bolivia', 'BR': 'Brasil', 'CL': 'Chile', 'CO': 'Colombia', 'CR': 'Costa Rica',
                 'EC': 'Ecuador', 'ES': 'España', 'GT': 'Guatemala', 'MX': 'México', 'PA': 'Panamá', 'PE': 'Perú',
                 'PY': 'Paraguay', 'DO': 'República Dominicana', 'SV': 'El Salvador', 'US': 'Estados Unidos',
                 'UY': 'Uruguay', 'VE': 'Venezuela'}
# The reasons a give-up names in its own words; anything else ends as before.
WHY_REASONS = frozenset({'cannot_do', 'not_found', 'no_payment', 'out_of_stock'})
_WHY_DROP = re.compile(r'(https?://\S+|www\.\S+|\b[\w.-]+\.(com|net|org|ly|io|me|co|mx|br|ar|ve|bo|pe|cl|app|link)\b\S*'
                       r'|[\w.+-]+@[\w-]+\.[\w.]+|@\w+|\+?\d[\d\s().-]{6,}\d|[<>*_`#\[\]]+)', re.I)


def reason_text(text):
    """The agent's few words on why it stopped, safe to show: no link, address, handle, phone or markup (a
    seller writes on the pages it read), one line, short. '' when nothing readable is left."""
    text = ' '.join(_WHY_DROP.sub(' ', str(text or '')).split()).strip(' .,;:-')
    return text[:140] if re.search(r'[a-záéíóúñ]{3}', text, re.I) else ''
# After the hand-over, nothing may suggest there is no order.
AFTER_CHECKOUT = (' Si ya confirmaste el pedido, sigue en tus compras de {site}: para pagarlo, {paste}.')
TASK_ACTION = {'type': 'task', 'label': 'Ver la compra'}
PUSH = {'person': 'Tu compra te espera', 'payment': 'Revisa tu pago', 'check': 'Revisa tu compra'}


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
    if getattr(task, 'kind', 'buy') == 'manage':
        text = STOPPED[reason] if reason in ('answered', 'declined', 'request_unclear') else MANAGE_ENDED
        if (task.order or {}).get('submitted') and reason not in ('answered', 'declined'):
            text = STOPPED['request_unclear']   # sent: never "nothing happened"
        return say(text, task).replace('{text}', str((task.order or {}).get('answer') or ''))
    if task.checkout_at:
        # The final button was pressed: whatever ended it, an order may exist. Never "compra tú".
        text = STOPPED['cancelled_ordered' if reason in ('cancelled', 'replaced') else 'unpaid']
    else:
        text = STOPPED.get(reason, STOPPED['error'])
        why = str((task.order or {}).get('why') or '') if reason in WHY_REASONS else ''
        if why:
            text = text.rstrip() + ' Motivo: ' + why.replace('{', '(').replace('}', ')') + '.'
    return say(text, task).replace('{country}', COUNTRY_NAMES.get(task.country or '', 'ese país'))


def manual_text(task):
    """The note when the person pays it themselves: the amount, and the account that would let Confío pay it."""
    order = task.order or {}
    text = say(PAYMENT_MANUAL, task).replace('{total}', str(order.get('total') or ''))
    return text + (OPEN_ACCOUNT if order.get('offer') else '')


# An order placed on "Elegir" alone, within its top total (spec decision 42): said as it happens.
PLACED_BY_CAP = ('Estoy haciendo tu pedido en {site}: {{total}}, dentro del máximo que aprobaste al elegir '
                 '({{cap}}). Te aviso cuando la tienda lo confirme.')

# A purchase the person's Cuenta inteligente pays (spec decisions 38 to 41, account_pay.py). {{total}} is the
# store's total, {{usd}} the dollars the account pays for it, the 0.9% exit fee included.
PAID_BY_ACCOUNT = ('Tu Cuenta inteligente está pagando tu pedido en {site}: {{total}}, {{usd}} con la comisión '
                   'de salida de 0,9%, dentro de tu límite de «Compras con Confío IA». No tienes que firmar nada; '
                   'sigue el pago en tu actividad.')
PAID_BY_ACCOUNT_PUSH = 'Tu Cuenta inteligente está pagando tu pedido en {site}.'
# The order was reserved for the account to pay and the pull could not be sent: no money left.
ACCOUNT_NOT_PAID = ('No pude pagar tu pedido en {site} desde tu Cuenta inteligente y no salió dinero de ella. '
                    'Puede que el pedido esté hecho y esperando el pago: revísalo en tus compras de {site}.')
# Why the account cannot pay a purchase now (smart_account.purchases.Standing), for the order card and the
# assistant. {{gross}}: the purchase with its exit fee; {{room}}/{{cap}}: the period's room and cap;
# {{short}}: what the account lacks; {{offer}}: what is offered to move (more than this purchase).
ACCOUNT_PAY = {
    'no_rule': ('Para que pague tus compras desde tu Cuenta inteligente, activa «Compras con Confío IA»: hasta '
                'US$200 cada 28 días, lo firmas una vez con Confío Face y puedes cambiar el límite.'),
    'move': ('A tu Cuenta inteligente le faltan {{short}} para este pedido ({{gross}} con la comisión de salida). '
             'Mueve {{offer}} de tu cuenta personal a tu Cuenta inteligente con Confío Face y lo pago desde ahí.'),
    'topup': ('Ni tu Cuenta inteligente ni tu cuenta personal tienen {{gross}} para este pedido. Recarga dólares '
              'y pásalos a tu Cuenta inteligente: lo pago desde ahí.'),
    'cap': ('Este pedido ({{gross}} con la comisión de salida) pasa tu límite de «Compras con Confío IA» para '
            'estos 28 días: te quedan {{room}} de {{cap}}. Si quieres, cambia el límite con Confío Face.'),
    # Their Cuenta inteligente lapsed (a payment due) or is not active: theirs to renew.
    'renew': ('Tu Cuenta inteligente no está al día o no está activa, así que no puede pagar este pedido. '
              'Ponla al día y lo pago desde ahí.'),
}
# The purchase spender is not allowed right now (Confío's gap, ops were told): nothing paid, said plainly.
ACCOUNT_PAUSED = ('Ahora no puedo pagar compras desde tu Cuenta inteligente, así que no pagué tu pedido en {site} y '
                  'no salió dinero. Puede que el pedido esté hecho y esperando el pago: revísalo en tus compras de '
                  '{site}.')
# A purchase waiting for the account (account_pay.wait): never paid from the personal wallet (founder, 2026-11-24).
# {{hours}}: AGENT_TASKS_ACCOUNT_WAIT_HOURS.
ACCOUNT_WAIT_TAIL = (' Tu pedido espera sin pagarse hasta {{hours}} horas; no lo pago desde tu cuenta personal. '
                     'Cuando lo hagas, toca «Ya lo hice: pagar».')
# The person said they had done it, and the account still cannot pay it.
ACCOUNT_STILL = 'Todavía no puedo pagarlo desde tu Cuenta inteligente. '
# The lock screen: no figures there.
ACCOUNT_WAIT_PUSH = 'Tu pedido en {site} espera a tu Cuenta inteligente.'
# The wait ran out (AGENT_TASKS_ACCOUNT_WAIT_HOURS): the order exists at the store, unpaid.
ACCOUNT_WAIT_EXPIRED = ('Dejé de esperar a tu Cuenta inteligente para pagar tu pedido en {site}, y no salió dinero '
                        'de ninguna de tus cuentas. El pedido quedó hecho en {site} sin pagar: revísalo en tus compras '
                        'de la tienda.')
# The chain or a provider could not be read, a few times: nothing paid, said plainly.
ACCOUNT_UNREAD = ('No pude confirmar que tu Cuenta inteligente pudiera pagar tu pedido en {site}, así que no lo pagué '
                  'y no salió dinero. Puede que el pedido esté hecho y esperando el pago: revísalo en tus compras de '
                  '{site}.')
# How a purchase the account was to pay ended, by its stop reason (schema.task_type).
ACCOUNT_STOPPED = {'account_timeout': ACCOUNT_WAIT_EXPIRED}

BREAKDOWN_LABELS = {'products': 'productos', 'shipping': 'envío', 'tax': 'impuestos', 'discount': 'descuento',
                    'fee': 'cargos', 'other': 'otros cargos'}


def breakdown_text(order):
    """' Total $129.00: productos $85.00 + envío $44.00.' in Confío's own words around the store's figures
    (operate.breakdown checked they are on the page and add up), or ''."""
    lines = [line for line in (order or {}).get('breakdown') or [] if line.get('kind') in BREAKDOWN_LABELS]
    if not lines:
        return ''
    parts = [f"{'- ' if line['kind'] == 'discount' else '+ ' if index else ''}{BREAKDOWN_LABELS[line['kind']]} "
             f"{line['amount']}" for index, line in enumerate(lines)]
    return f" Total {order.get('total')}: {' '.join(parts)}."


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
