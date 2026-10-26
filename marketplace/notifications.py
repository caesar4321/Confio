"""Order notifications. Best-effort: a failed push never blocks a money state."""

import logging

logger = logging.getLogger(__name__)

# (new status) → [(recipient role, title, message)]
_MESSAGES = {
    'funded': [
        ('merchant', 'Nuevo pedido en Comprar',
         '{buyer} compró {qty} × {title}. Prepáralo y márcalo como enviado.{adults}'),
        ('buyer', 'Pago protegido',
         'Tu pago por {title} está protegido hasta que lo recibas.'),
    ],
    'shipped': [
        ('buyer', 'Tu pedido va en camino',
         '{store} envió {title}. Paga el envío al repartidor al recibirlo.'),
    ],
    'disputed': [
        ('merchant', 'Pedido en revisión',
         'El comprador reportó un problema con {title}. Confío revisará el caso.'),
    ],
    'released': [
        ('merchant', 'Recibiste un pago',
         'El pago por {title} ya está en tu cuenta.'),
    ],
    'refunded': [
        ('buyer', 'Reembolso recibido',
         'Te devolvimos el pago por {title}.'),
        ('merchant', 'Pedido reembolsado',
         'El pedido de {title} fue reembolsado al comprador.'),
    ],
}


# Adults-only orders: the seller hands them over only to an adult.
ADULTS_NOTE = ' Entrégalo solo a un mayor de 18 que muestre su carnet.'


def order_status_changed(order, previous: str) -> None:
    from notifications.models import NotificationType
    from notifications.utils import create_notification

    for role, title, message in _MESSAGES.get(order.status, []):
        user = order.buyer if role == 'buyer' else order.store.owner
        account = order.buyer_account if role == 'buyer' else order.store.owner_account
        try:
            create_notification(
                user=user, account=account,
                notification_type=NotificationType.MARKETPLACE_ORDER_UPDATED,
                title=title,
                message=message.format(
                    buyer=order.buyer.first_name or 'Un cliente', qty=order.quantity,
                    title=order.product_title, store=order.store.name,
                    adults=ADULTS_NOTE if order.age_restricted else ''),
                data={'order_id': str(order.public_id), 'status': order.status,
                      'previous': previous, 'role': role},
                related_object_type='MarketplaceOrder',
                related_object_id=str(order.public_id),
                action_url=f'confio://comprar/order/{order.public_id}',
            )
        except Exception:  # noqa: BLE001
            logger.exception('[COMPRAR] notification failed for order %s (%s)', order.pk, role)
