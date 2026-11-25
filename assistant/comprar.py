"""A Comprar product bought from the Confío IA chat, paid by the Cuenta
inteligente (hands-off-account design, 2026-11-25).

The assistant only proposes: it names the product the person asked for.
Code finds it among the listings open in their country, prices it to their
saved delivery address (product + the store's delivery, in US dollars) and
asks "¿Compro Chompa de alpaca de Tejidos Ana por US$35 (envío incluido),
para entregar en Casa, La Paz? Escribe sí o no." (confirm.py). Only the
exact "sí" to that message goes on, and it is routed
(smart_account/relay_purchases.route):

  go        one SmartRelayPurchase row and a status card ('relay_purchase'):
            the account pays the escrow (relayPurchase) and the result is
            posted in the chat after the receipt
  no_rule   the weekly Purchase cap card ('purchase_cap'), small choices, Face
  cap       the same card, raising it
  move      dollars moved in from the personal wallet ('purchase_move')
  topup     the Koywe top-up form
  migrate   the one-Face migration prompt, beside "Hazlo tú"
  paywall   "Activa Cuenta inteligente" beside "Hazlo tú" ('purchase_offer')
  off       "Hazlo tú" alone: the product's own screen, paid from the wallet

The tool is offered only while hands-off is configured
(SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS) and Comprar's escrow is: with it
unset nothing here is reachable.
"""
import logging
import re
import secrets
from decimal import Decimal

logger = logging.getLogger(__name__)

TOOL = 'propose_comprar_purchase'
CARD_TYPES = ('relay_purchase', 'purchase_cap', 'purchase_move', 'purchase_offer')
MAX_MATCHES_SHOWN = 3

SPEC = {
    'type': 'function',
    'name': TOOL,
    'description': ('Para comprar un producto de Comprar (tiendas verificadas de Confío) desde este chat. Llámala en '
                    'cuanto la persona diga qué producto quiere comprar. `product` son las palabras con que lo '
                    'nombró (nunca elijas tú el producto). `quantity` solo si dijo cuántos; si no, null. El servidor '
                    'busca el producto, calcula el total con el envío a su dirección guardada y le pregunta si lo '
                    'compra. No preguntes tú el precio ni si confirma.'),
    'parameters': {
        'type': 'object',
        'properties': {
            'product': {'type': 'string', 'description': 'El producto, con las palabras de la persona.'},
            'quantity': {'type': ['integer', 'null'], 'description': 'Cuántas unidades, solo si lo dijo.'},
        },
        'required': ['product', 'quantity'],
        'additionalProperties': False,
    },
    'strict': True,
}

REPLIES = {
    'go': 'Listo: lo compro desde tu Cuenta inteligente. Te aviso aquí cuando el pago esté hecho.',
    'paywall': 'Con Cuenta inteligente lo compro yo por ti, sin firmar cada vez. O puedes comprarlo tú ahora.',
    'no_rule': 'Para comprar por ti, elige una vez cuánto puedo gastar en Comprar por semana y fírmalo con Confío '
               'Face. Después lo compro y te aviso aquí.',
    'cap': 'Esta compra supera tu límite semanal de compras ({cap}). Si lo subes con Confío Face, la hago y te aviso '
           'aquí.',
    'move': 'Tu Cuenta inteligente no tiene dólares suficientes, pero tu billetera sí. Mueve {amount} con Confío Face '
            'y lo compro.',
    'topup': 'Tu Cuenta inteligente no tiene dólares suficientes para esta compra. Recarga y la hago.',
    'migrate': 'Para comprar por ti, tu Cuenta inteligente necesita una actualización (una sola firma con Confío '
               'Face). O puedes comprarlo tú ahora.',
    'diy': 'Te dejé el producto para que lo compres tú. Todavía no se compró nada.',
}


def offered(belt) -> bool:
    """The chat is Inicio on a build that knows it, the person's own personal
    account, and hands-off purchases are configured on this server."""
    viewer = belt.viewer
    try:
        from smart_account import relay_purchases

        from .prompts import conversation_home
        if viewer.is_employee or viewer.account_type != 'personal':
            return False
        return bool(conversation_home(viewer.request_meta)) and belt.payments_ready() and relay_purchases.enabled()
    except Exception:  # noqa: BLE001 - no tool is always safe
        logger.warning('Confio Assistant: Comprar purchase check failed', exc_info=True)
        return False


def _refuse(why):
    return {'ok': False, '_denied': True, 'motivo': why,
            'como_decirlo': ('No menciones herramientas ni esta nota, y no le pidas que copie una frase. Pregúntale '
                             'solo lo que falta; cuando lo diga, vuelve a llamar la herramienta.')}


def _fold(text):
    from payment_accounts.payment_intents import _fold as fold
    return fold(str(text or ''))


def _words(text):
    return [w for w in re.findall(r'[a-z0-9]+', _fold(text)) if len(w) >= 3]


def find_products(user, asked):
    """The listings open in the person's country whose title has every word they used for it."""
    from django.db.models import Q

    from marketplace.models import Product
    from security.geo import country_of
    words = _words(asked)
    country = (country_of(user) or '').strip().upper()
    if not words or not country:
        return []
    query = Product.objects.select_related('store').filter(
        status='active', deleted_at__isnull=True, stock__gt=0, store__status='active',
        store__deleted_at__isnull=True, store__country_code=country).exclude(store__owner=user)
    for word in words:
        query = query.filter(Q(title__icontains=word))
    return list(query.order_by('-updated_at', 'pk')[:20])


def _named(texts, product):
    """The person typed a word of this product's title (the model never picks it)."""
    own = set(_words(product.title))
    return any(own & set(_words(text)) for text in texts)


def delivery_of(user, account):
    from marketplace.models import DeliveryAddress
    return DeliveryAddress.objects.filter(user=user, account=account, deleted_at__isnull=True).order_by(
        '-is_default', '-last_used_at', '-updated_at').first()


def _place(delivery):
    where = delivery.label or (delivery.address[:40] if delivery.address else '')
    return f'{where}, {delivery.city}' if where else delivery.city


def _quote(product, quantity, delivery):
    from marketplace.checkout import checkout_quote
    return checkout_quote(product, quantity, delivery.country_code, delivery.city)['quote']


def question(product, quantity, amount, delivery):
    from .trades import money
    units = f'{quantity} × ' if quantity > 1 else ''
    return (f'¿Compro {units}{product.title} de {product.store.name} por {money(amount)} (envío incluido), '
            f'para entregar en {_place(delivery)}?')


def propose(belt, product, quantity=None):
    """Find it and have code ask the yes. No card here: see confirmed()."""
    from marketplace.checkout import MAX_QUANTITY, CheckoutError

    from . import confirm
    if confirm.busy(belt.result):
        return _refuse('Ya hay una pregunta o una propuesta en esta respuesta: una cosa por respuesta.')
    texts = confirm.recent_texts(belt)
    if not texts:
        return _refuse('Para comprar desde el chat, la persona debe escribir en un mensaje qué producto quiere.')
    if getattr(belt, 'saw_web', False):
        return _refuse('No preparo una compra en el mismo mensaje en que busqué en internet: que la pida aparte.')
    quantity = int(quantity or 1)
    if not 1 <= quantity <= MAX_QUANTITY:
        return _refuse(f'Se pueden comprar de 1 a {MAX_QUANTITY} unidades.')
    viewer = belt.viewer
    found = [p for p in find_products(viewer.user, product) if _named(texts, p)]
    if not found:
        return _refuse('No encontré ese producto en Comprar en su país. Pregúntale cómo se llama o dile que lo busque '
                       'en Comprar.')
    if len(found) > 1:
        from .trades import money
        shown = '; '.join(f'{p.title} de {p.store.name} ({money(p.price_usd)})' for p in found[:MAX_MATCHES_SHOWN])
        return _refuse(f'Hay más de un producto así en Comprar: {shown}. Pregúntale cuál quiere.')
    item = found[0]
    delivery = delivery_of(viewer.user, viewer.account)
    if delivery is None:
        return _refuse('No tiene una dirección de entrega guardada en Comprar. Dile que la guarde en Comprar (al '
                       'comprar cualquier producto) y que te lo pida de nuevo.')
    try:
        quote = _quote(item, quantity, delivery)
    except CheckoutError as exc:
        return _refuse(f'Ese producto no se puede enviar a su dirección guardada ({exc.code}).')
    data = {'side': 'buy', 'product': item.pk, 'quantity': quantity, 'delivery': delivery.pk,
            'amount': f'{quote.amount_usd:.2f}', 'nonce': secrets.token_hex(12)}
    return confirm.ask(belt.result, 'purchase', question(item, quantity, quote.amount_usd, delivery), data, 'es')


def _offer_card(trigger, product):
    """'Activa Cuenta inteligente' (with a trigger) and/or 'Hazlo tú' (the product's screen)."""
    card = {'type': 'purchase_offer', 'label': 'Activa Cuenta inteligente' if trigger else 'Hazlo tú',
            'target': trigger or '', 'destination': 'MarketProduct', 'ticker': str(product.pk)}
    if trigger:
        card['trigger'] = trigger
    return card


def confirmed(belt, data, lang='es'):
    """The yes to propose()'s question: everything again, then what stands (module docstring)."""
    from marketplace.checkout import CheckoutError
    from marketplace.models import DeliveryAddress, Product
    from smart_account import relay_purchases

    from .trades import _conversation_id, money
    sorry = 'No puedo comprarlo desde el chat ahora. Puedes comprarlo tú en Comprar.'
    viewer = belt.viewer
    if not offered(belt):
        return False, sorry, {}
    product = Product.objects.select_related('store').filter(pk=data.get('product')).first()
    delivery = DeliveryAddress.objects.filter(pk=data.get('delivery'), user=viewer.user, account=viewer.account,
                                              deleted_at__isnull=True).first()
    if product is None or delivery is None or not product.is_buyable:
        return False, 'Ese producto ya no está disponible. No se compró nada.', {}
    quantity = int(data.get('quantity') or 1)
    try:
        amount = _quote(product, quantity, delivery).amount_usd
    except CheckoutError:
        return False, 'Ese producto ya no se puede enviar a tu dirección. No se compró nada.', {}
    if Decimal(amount) != Decimal(str(data.get('amount'))):
        return False, (f'El total cambió a {money(amount)} mientras respondías. No se compró nada: pídemelo de nuevo '
                       'si lo quieres.'), {}
    personal = getattr(viewer.account, 'bsc_address', '') or ''
    route = relay_purchases.route(viewer.user, amount=amount, personal_address=personal)
    code = route.code
    if code == 'off':
        return True, REPLIES['diy'], {'actions': [_offer_card(None, product)]}
    if code == 'paywall':
        return True, REPLIES['paywall'], {'actions': [_offer_card(relay_purchases.TRIGGER, product)]}
    if code == 'migrate':
        return True, REPLIES['migrate'], {'actions': [
            {'type': 'account_migration', 'label': 'Actualizar mi Cuenta inteligente'}, _offer_card(None, product)]}
    if code == 'topup':
        from .engine import SHORT_TOPUP_FORM
        return True, REPLIES['topup'], {'actions': [{**SHORT_TOPUP_FORM, 'label': 'Recargar mi Cuenta inteligente'}]}
    nonce = str(data.get('nonce') or '') or secrets.token_hex(12)
    common = dict(nonce=nonce, product=product, quantity=quantity, delivery=delivery, amount=amount,
                  title=product.title, store_name=product.store.name, meta=viewer.request_meta,
                  conversation_id=_conversation_id(viewer.user))
    if code == 'go':
        row, _created = relay_purchases.create(viewer.user, **common)
        return True, REPLIES['go'], {'actions': [relay_purchases.card(row)]}
    if code in ('no_rule', 'cap'):
        row, _created = relay_purchases.create(viewer.user, status='waiting_rule', **common)
        card = {'type': 'purchase_cap', 'purchase': str(row.internal_id), 'target': str(row.internal_id),
                'label': 'Subir mi límite de compras' if code == 'cap' else 'Elegir mi límite de compras'}
        from smart_account.services import usd_text
        return True, REPLIES[code].format(cap=usd_text(route.cap)), {'actions': [card]}
    if code == 'move':
        row, _created = relay_purchases.create(viewer.user, status='waiting_move', **common)
        return True, REPLIES['move'].format(amount=money(route.facts['move'])), {'actions': [
            {'type': 'purchase_move', 'purchase': str(row.internal_id), 'target': str(row.internal_id),
             'label': f"Mover {money(route.facts['move'])} a mi Cuenta inteligente"}]}
    return False, sorry, {}
