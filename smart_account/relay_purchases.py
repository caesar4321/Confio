"""Hands-off Comprar purchases from the Confío IA chat, paid by the person's
Cuenta inteligente (v2 relayPurchase into ConfioMarketEscrow.depositFrom).

The person's exact "sí" in the chat (assistant/comprar.py) makes one
SmartRelayPurchase row; nothing is ordered or sent in the chat request. The
Celery task `smart_account.run_relay_purchase` then, for that one row:

  1. waits until the reply that carries its status card is in the chat; a
     reply written without it (they wrote "no" meanwhile) cancels;
  2. checks the route again (route(): subscriber, v2, live Purchase rule
     paying the escrow, bucket room, the dollars in the account, not paused,
     depositFrom switched on at the escrow);
  3. creates the Comprar order as checkout does (marketplace.checkout.
     prepare_account_order: every listing, delivery and limit gate, stock
     reserved) with the backend's authorization over depositFromDigest:
     buyer = the owner's wallet, payer = this account. Never the plain
     deposit digest: only this account can spend it;
  4. checks the exact calldata against the order and the rule
     (check_relay_purchase) and the bucket off chain;
  5. sends relayPurchase from the sponsor through relayer.send_relayer_call:
     simulated first, the durable SmartAccountRelayTx row written with the
     signed hash before broadcast (the claim moves this row to 'unknown' and
     the order to 'depositing' in that same transaction), idempotent on
     (account, kind, the row's id);
  6. after the receipt (`smart_account.finish_relay_purchase`), mirrors the
     order from the escrow and posts the result in the chat. A broadcast is
     never assumed landed: an exception after signing leaves the row
     'unknown' and the receipt decides.

What stands in the way is offered as cards, like the hands-off trades: the
weekly Purchase cap (kept small, audit: US$50 / 150 / 300 or another amount,
signed once with Face), a raise when the bucket has no room, the paywall
beside "Hazlo tú" (the product's own screen, paid from the wallet), the
Koywe top-up or a move into the account, and the v1 migration prompt.

The escrow's refund of such an order goes back to the account (refundToOf);
marketplace/ledger.py and notifications say so.

Dormant until SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS (hands_off.enabled()).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from decimal import ROUND_UP, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import abi, chain, hands_off

logger = logging.getLogger(__name__)

WAD = 10 ** 18
CENT = Decimal('0.01')
# Purchase caps stay small (the audit: relayer + order-signer compromise can pay an attacker merchant up to it).
CAP_CHOICES = (Decimal('50'), Decimal('150'), Decimal('300'))
MAX_CAP_USD = Decimal('1000')
FREQUENCY = 'weekly'
# A cUSD+ Purchase rule unwraps the amount plus this margin (PAYOUT_UNWRAP_MARGIN_BPS) inside relayPurchase.
PLUS_MARGIN_BPS = 5
REPLY_WAIT = timedelta(seconds=45)
RULE_WAIT = timedelta(minutes=15)
MAX_ATTEMPTS = 3
# The order's authorization must outlive the send by this much (else a new "sí").
MIN_AUTH_LEFT_S = 120

ACTION_TYPE = 'relay_purchase'
TRIGGER = 'chat_purchase'


class Later(Exception):
    def __init__(self, seconds: int, why: str = ''):
        self.seconds = max(2, int(seconds))
        super().__init__(why or f'later {seconds}s')


class Refused(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# ── the rule and where one purchase stands ──────────────────────────────

def purchase_rule(own):
    """The live Purchase rule of this account's current subscription (payee = the escrow), from the mirror."""
    from marketplace.escrow import escrow_address
    from .models import SmartAccountRule
    escrow = escrow_address()
    if own is None or not escrow:
        return None
    return SmartAccountRule.objects.filter(
        smart_account=own, kind='purchase', state='onchain', active=True, onchain_id__isnull=False,
        payee_address__iexact=escrow, epoch=own.subscription_epoch).order_by('-pk').first()


def suggested_cap(at_least) -> Decimal:
    """The smallest choice that covers this, else a round US$50 above (never past MAX_CAP_USD)."""
    target = Decimal(at_least or 0)
    for choice in CAP_CHOICES:
        if target <= choice:
            return choice
    return min((target / 50).quantize(Decimal('1'), rounding=ROUND_UP) * 50, MAX_CAP_USD)


def needed_usd(rule_token: str, amount: Decimal) -> Decimal:
    """What the account must hold for `amount`: a cUSD+ rule unwraps the margin too."""
    if rule_token == chain.cusd_plus_address():
        return (Decimal(amount) * (1 + Decimal(PLUS_MARGIN_BPS) / 10_000) + CENT).quantize(CENT, rounding=ROUND_UP)
    return Decimal(amount)


def enabled() -> bool:
    try:
        from marketplace.escrow import enabled as comprar_enabled
        return hands_off.enabled() and comprar_enabled()
    except Exception:  # noqa: BLE001
        return False


def route(user, *, amount, personal_address: str = '') -> hands_off.Route:
    """Which path one purchase of `amount` US dollars takes: go, paywall, migrate,
    no_rule, cap, move, topup or off (hands_off.route's vocabulary). Anything
    unread is 'off': the chat then offers only "Hazlo tú"."""
    from .context import own_account
    if not enabled():
        return hands_off.Route('off', why='dormant')
    own = own_account(user)
    if not hands_off.subscribed(user) or own is None or own.status not in ('active', 'cancel_pending'):
        return hands_off.Route('paywall', own=own)
    if own.billing_status != 'current':
        return hands_off.Route('off', own=own, why='billing')
    amount = Decimal(amount or 0)
    try:
        from marketplace.escrow import deposit_from_enabled, escrow_address
        if not hands_off.is_v2(own):
            return hands_off.Route('migrate', own=own)
        if hands_off.trade_paused():
            return hands_off.Route('off', own=own, why='paused')
        if not deposit_from_enabled():
            return hands_off.Route('off', own=own, why='escrow')
        rule = purchase_rule(own)
        if rule is None:
            return hands_off.Route('no_rule', own=own, suggested=suggested_cap(amount))
        onchain = chain.account_rule(own.contract_address, int(rule.onchain_id))
        dollars = (chain.cusd_plus_address(), chain.cusd_address())
        if (onchain['kind'] != 'purchase' or not onchain['active'] or onchain['payee'] != escrow_address()
                or onchain['token_in'] not in dollars):
            return hands_off.Route('no_rule', own=own, suggested=suggested_cap(amount))
        cap_wei = int(onchain['amount_usd_wei'])
        used, _last = hands_off.bucket_of(own.contract_address, int(rule.onchain_id))
        cap, room = hands_off._usd(cap_wei), hands_off._usd(max(0, cap_wei - used))
        facts = dict(own=own, rule=rule, cap=cap, room=room)
        if amount > room:
            return hands_off.Route('cap', suggested=suggested_cap(cap + amount), **facts)
        token = onchain['token_in']
        need = needed_usd(token, amount)
        held = hands_off.dollar_usd(token, chain.balance_of(token, own.contract_address))
        if held >= need:
            return hands_off.Route('go', **facts)
        short = need - held
        plus = chain.cusd_plus_address()
        personal = (hands_off.dollar_usd(plus, chain.balance_of(plus, personal_address))
                    if personal_address and token == plus else Decimal(0))
        if personal >= short:
            return hands_off.Route('move', facts={'short': short, 'personal': personal,
                                                  'move': hands_off.move_amount(short, personal)}, **facts)
        return hands_off.Route('topup', facts={'short': short}, **facts)
    except Exception as exc:  # noqa: BLE001 - unread is never "the account pays"
        logger.warning('hands-off purchase route unreadable: %s', type(exc).__name__, exc_info=True)
        return hands_off.Route('off', own=own, why='unread')


# ── rows ────────────────────────────────────────────────────────────────

def create(user, *, nonce: str, product, quantity: int, delivery, amount, title: str, store_name: str, meta,
           conversation_id=None, status: str = 'pending'):
    """The row for one "sí". The same question's second "sí" gets the first row back."""
    from .context import own_account
    from .models import SmartRelayPurchase
    from .relay_trades import kept_meta
    defaults = dict(smart_account=own_account(user), product=product, quantity=int(quantity),
                    delivery_address=delivery, amount_usd=Decimal(amount), title=title[:100],
                    store_name=(store_name or '')[:80], meta=kept_meta(meta), status=status,
                    conversation_id=conversation_id)
    try:
        with transaction.atomic():
            row, created = SmartRelayPurchase.objects.get_or_create(user=user, nonce=nonce, defaults=defaults)
    except IntegrityError:
        row, created = SmartRelayPurchase.objects.get(user=user, nonce=nonce), False
    if created and status == 'pending':
        schedule(row.pk, countdown=2)
    return row, created


def schedule(row_id: int, countdown: int = 2) -> None:
    def go():
        try:
            from .tasks import run_relay_purchase
            run_relay_purchase.apply_async(args=[row_id], countdown=countdown)
        except Exception:  # noqa: BLE001
            logger.exception('relay purchase %s could not be scheduled', row_id)
    transaction.on_commit(go)


def resume(user, internal_id):
    """The cap or move card was signed: the purchase waiting for it runs. Only the owner's own waiting row."""
    from .models import SmartRelayPurchase
    try:
        row = SmartRelayPurchase.objects.filter(user=user, internal_id=internal_id).first()
    except (TypeError, ValueError):
        return None
    if row is None:
        return None
    if row.status in ('waiting_rule', 'waiting_move'):
        won = SmartRelayPurchase.objects.filter(pk=row.pk, status=row.status).update(
            status='pending', updated_at=timezone.now())
        if won:
            row.status = 'pending'
            schedule(row.pk)
    return row


# ── the chat ────────────────────────────────────────────────────────────

def label(row) -> str:
    from assistant.trades import money
    return f'Comprar {row.title} por {money(row.amount_usd)}'


def card(row) -> dict:
    # `target` carries the id to the app (AssistantActionType has no other free field).
    return {'type': ACTION_TYPE, 'purchase': str(row.internal_id), 'target': str(row.internal_id),
            'label': label(row)}


def _reply_state(row) -> str:
    from inbox.models import SupportMessage
    if row.conversation_id is None:
        return 'shown'
    later = SupportMessage.objects.filter(conversation_id=row.conversation_id, sender_type='AGENT',
                                          created_at__gte=row.created_at - timedelta(seconds=5))
    # Any card naming this row: its status card, or the cap / move card it waited on (a purchase resumed
    # after the cap card was signed carried 'purchase_cap', never 'relay_purchase').
    if later.filter(metadata__actions__contains=[{'purchase': str(row.internal_id)}]).exists():
        return 'shown'
    if timezone.now() - row.created_at > REPLY_WAIT:
        return 'withdrawn'
    return 'waiting'


MESSAGES = {
    'done': {'es': 'Listo: compré {what} por {spent} desde tu Cuenta inteligente. Tu pago queda protegido hasta que '
                   'lo recibas; lo sigues en Comprar, Mis compras. Si se reembolsa, vuelve a tu Cuenta inteligente.',
             'pt': 'Pronto: comprei {what} por {spent} pela sua Cuenta inteligente. Seu pagamento fica protegido até '
                   'você receber; acompanhe em Comprar, Mis compras. Se for reembolsado, volta para sua Cuenta '
                   'inteligente.',
             'en': 'Done: I bought {what} for {spent} from your Cuenta inteligente. Your payment stays protected '
                   'until you receive it; follow it in Comprar, Mis compras. If it is refunded, it goes back to your '
                   'Cuenta inteligente.'},
    'cap': {'es': 'Todavía no lo compré: supera tu límite semanal de compras. Si lo subes con Confío Face, lo compro '
                  'y te aviso aquí.',
            'pt': 'Ainda não comprei: passa do seu limite semanal de compras. Se você aumentar com Confío Face, eu '
                  'compro e aviso aqui.',
            'en': "I haven't bought it yet: it is above your weekly purchase limit. Raise it with Confío Face and "
                  "I'll buy it and tell you here."},
    'balance': {'es': 'No compré nada: tu Cuenta inteligente no tiene dólares suficientes. Puedes recargar desde el '
                      'chat.',
                'pt': 'Não comprei nada: sua Cuenta inteligente não tem dólares suficientes. Você pode recarregar '
                      'pelo chat.',
                'en': "I didn't buy anything: your Cuenta inteligente doesn't have enough dollars. You can top up "
                      "from the chat."},
    'price': {'es': 'No lo compré: el precio o el envío cambió y no se movió nada. Pídemelo de nuevo para ver el '
                    'nuevo total.',
              'pt': 'Não comprei: o preço ou o frete mudou e nada foi movido. Peça de novo para ver o novo total.',
              'en': "I didn't buy it: the price or the shipping changed, and nothing moved. Ask me again to see the "
                    "new total."},
    'unavailable': {'es': 'No lo compré: ese producto ya no está disponible así y no se movió nada.',
                    'pt': 'Não comprei: esse produto não está mais disponível assim e nada foi movido.',
                    'en': "I didn't buy it: that product is no longer available like that, and nothing moved."},
    'reverted': {'es': 'No se hizo: la compra no pasó en la red y no se movió nada. Puedes pedírmela otra vez.',
                 'pt': 'Não foi feito: a compra não passou na rede e nada foi movido. Pode me pedir de novo.',
                 'en': "It didn't go through: the purchase failed on the network and nothing moved. You can ask me "
                       "again."},
    'failed': {'es': 'No pude comprarlo ahora y no se movió nada. Puedes pedírmelo otra vez o comprarlo tú en '
                     'Comprar.',
               'pt': 'Não consegui comprar agora e nada foi movido. Pode me pedir de novo ou comprar você em Comprar.',
               'en': "I couldn't buy it now and nothing moved. You can ask me again or buy it yourself in Comprar."},
}
# Checkout refusals that mean the listing or the delivery changed (said as 'unavailable').
UNAVAILABLE = frozenset(('product_unavailable', 'out_of_stock', 'city_not_live', 'store_city_only',
                         'store_country_only', 'store_cannot_receive', 'pin_outside_area', 'age_required',
                         'alcohol_hours', 'alcohol_paused', 'alcohol_license', 'own_store', 'order_too_large',
                         'marketplace_busy', 'marketplace_disabled'))


def _post(row, key: str, **values) -> None:
    from assistant.service import post_system_note
    try:
        from .relay_trades import lang_of, said
        post_system_note(row.user, said(MESSAGES[key], lang_of(row)).format(**values),
                         f'relay_purchase:{row.internal_id}:{row.status}',
                         actions=[card(row)])
        from .models import SmartRelayPurchase
        SmartRelayPurchase.objects.filter(pk=row.pk).update(notified_at=timezone.now())
    except Exception:  # noqa: BLE001 — the card shows the state; the note is best effort
        logger.exception('relay purchase %s result not posted', row.pk)


def _drop_order(row) -> None:
    """An order whose authorization will never be used: cancelled; its stock comes back through the keeper
    once the authorization provably expired unspent (marketplace.escrow.release_unspent_reservation)."""
    if row.order_id is None:
        return
    from marketplace.models import Order
    Order.objects.filter(pk=row.order_id, status__in=('draft', 'depositing')).update(
        status='cancelled', pending_action='', pending_action_at=None)


def _offer_mark(row) -> int:
    """Which raise offer this is: the time the row last moved (a resume), so a later one is a new note."""
    return int(row.updated_at.timestamp()) if row.updated_at else 0


def _offer_raise(row) -> None:
    from assistant.service import post_system_note
    from .models import SmartRelayPurchase
    mark = _offer_mark(row)
    _drop_order(row)
    SmartRelayPurchase.objects.filter(pk=row.pk).update(status='waiting_rule', error_code='cap', order=None,
                                                        updated_at=timezone.now())
    try:
        from .relay_trades import lang_of, said
        post_system_note(row.user, said(MESSAGES['cap'], lang_of(row)), f'relay_purchase:{row.internal_id}:cap:{mark}',
                         actions=[{'type': 'purchase_cap', 'purchase': str(row.internal_id),
                                   'target': str(row.internal_id), 'label': 'Subir mi límite de compras'}])
    except Exception:  # noqa: BLE001
        logger.exception('relay purchase %s raise offer not posted', row.pk)


def _end(row, status: str, code: str = '', note: str | None = 'failed', **values) -> None:
    from .models import SmartRelayPurchase
    if status in ('failed', 'cancelled'):
        _drop_order(row)
    SmartRelayPurchase.objects.filter(pk=row.pk).update(status=status, error_code=code[:60],
                                                        updated_at=timezone.now())
    row.status, row.error_code = status, code
    if note:
        _post(row, note, **values)


# ── the order and the call ──────────────────────────────────────────────

def make_order(row, own):
    """The escrow order for this row (once): checkout's gates, depositFromDigest with payer = the account."""
    from marketplace.checkout import CheckoutError, prepare_account_order
    from .context import personal_account
    from .models import SmartRelayPurchase
    if row.order_id is not None:
        return row.order
    personal = personal_account(row.user)
    if personal is None or (own.owner_account_id and personal.pk != own.owner_account_id):
        raise Refused('no_owner_wallet')
    # One transaction with the row locked: the order exists only linked to its row (no orphan draft holding
    # stock), and a second run waits here and then finds it. A refusal rolls both back.
    with transaction.atomic():
        locked = SmartRelayPurchase.objects.select_for_update().get(pk=row.pk)
        if locked.order_id is not None:
            row.order_id = locked.order_id
            row.order = locked.order
            return row.order
        try:
            order = prepare_account_order(row.user, personal, payer=own.contract_address,
                                          product_id=row.product_id, quantity=row.quantity,
                                          delivery=row.delivery_address)
        except CheckoutError as exc:
            raise Refused(exc.code) from exc
        if Decimal(order.amount_usd) > Decimal(row.amount_usd):
            raise Refused('price_changed')
        SmartRelayPurchase.objects.filter(pk=row.pk).update(order=order)
    row.order, row.order_id = order, order.pk
    return order


def purchase_calldata(rule, order) -> str:
    return abi.relay_purchase_call(int(rule.onchain_id), order.order_id32, order.merchant_address,
                                   int(order.amount_wei), int(order.fee_bps), int(order.deposit_deadline),
                                   bytes.fromhex(order.deposit_signature.removeprefix('0x')))


def check_relay_purchase(own, rule, calldata: str, order) -> None:
    """The exact relayPurchase the relayer is about to sign: this account's live
    Purchase rule, the order's own terms, the owner as buyer, this account as
    payer, and an authorization from the escrow's order signer over
    depositFromDigest. Raises Refused."""
    from marketplace import escrow
    try:
        rule_id, order_id, merchant, amount, fee_bps, deadline, sig = abi.decode_relay_purchase(calldata)
    except ValueError as exc:
        raise Refused('bad_calldata') from exc
    if rule is None or rule.kind != 'purchase' or rule.onchain_id is None or int(rule.onchain_id) != rule_id \
            or rule.smart_account_id != own.pk:
        raise Refused('bad_rule')
    if (order_id != order.order_id32 or merchant != order.merchant_address.lower()
            or amount != int(order.amount_wei) or fee_bps != int(order.fee_bps)
            or deadline != int(order.deposit_deadline)):
        raise Refused('order_mismatch')
    owner = (getattr(own.owner_account, 'bsc_address', '') or '').lower()
    if not owner or order.buyer_address.lower() != owner or order.payer_address.lower() != own.contract_address.lower():
        raise Refused('order_not_this_account')
    if order.token_address.lower() != escrow.token_address() or merchant in (owner, own.contract_address.lower()):
        raise Refused('order_mismatch')
    if deadline <= int(time.time()) + MIN_AUTH_LEFT_S:
        raise Refused('authorization_expired')
    digest = escrow.deposit_from_digest(order.order_id32, owner, own.contract_address, merchant,
                                        order.token_address, amount, fee_bps, deadline)
    try:
        recovered = escrow.recover_signer(digest, '0x' + sig.hex())
    except Exception as exc:  # noqa: BLE001
        raise Refused('bad_authorization') from exc
    if not recovered or recovered.lower() != (order.deposit_signer or '').lower():
        raise Refused('bad_authorization')


# ── the task's body ─────────────────────────────────────────────────────

BUSY_CODES = ('sponsor_busy', 'claim_busy', 'gas_price_too_high', 'simulation_unreadable')


def run(row_id: int) -> None:
    """One pass for one row. Raises Later to be run again; every other end is final and told in the chat."""
    from marketplace.models import Order
    from . import relayer
    from .context import personal_account
    from .models import SmartRelayPurchase
    row = SmartRelayPurchase.objects.select_related('user', 'order').filter(pk=row_id).first()
    if row is None or row.status != 'pending':
        return
    state = _reply_state(row)
    if state == 'waiting':
        raise Later(3, 'reply not written yet')
    if state == 'withdrawn':
        return _end(row, 'cancelled', 'withdrawn', note=None)
    personal = personal_account(row.user)
    found = route(row.user, amount=row.amount_usd, personal_address=getattr(personal, 'bsc_address', '') or '')
    if found.code in ('no_rule', 'move') and timezone.now() - row.updated_at < RULE_WAIT:
        raise Later(15, 'rule or moved dollars not live yet')
    if found.code == 'cap':
        return _offer_raise(row)
    if found.code == 'topup':
        return _end(row, 'failed', 'balance', note='balance')
    if found.code != 'go':
        return _end(row, 'failed', f'route_{found.code}')
    own, rule = found.own, found.rule

    try:
        order = make_order(row, own)
        calldata = purchase_calldata(rule, order)
        check_relay_purchase(own, rule, calldata, order)
    except Refused as exc:
        if exc.code == 'price_changed':
            return _end(row, 'failed', exc.code, note='price')
        if exc.code in UNAVAILABLE:
            return _end(row, 'failed', exc.code, note='unavailable')
        return _end(row, 'failed', exc.code)
    # The bucket off chain: never send one the contract would refuse.
    used, _last = hands_off.bucket_of(own.contract_address, int(rule.onchain_id))
    cap_wei = int(chain.account_rule(own.contract_address, int(rule.onchain_id))['amount_usd_wei'])
    if used + int(order.amount_wei) > cap_wei:
        return _offer_raise(row)

    def claim(tx_hash):
        # Inside the transaction that writes the durable relay row: the purchase row is 'unknown' and the order
        # 'depositing' with that hash until the broadcast is known to have left.
        won = SmartRelayPurchase.objects.filter(pk=row.pk, status='pending').update(
            status='unknown', tx_hash=tx_hash, updated_at=timezone.now())
        took = Order.objects.filter(pk=order.pk, status='draft').update(
            status='depositing', pending_action='deposit', pending_action_at=timezone.now(),
            deposit_tx_hash=tx_hash, last_tx_hash=tx_hash)
        if not won or not took:
            raise relayer.RelayError('claim_busy', 'purchase row or order moved on')

    try:
        relay_row, _created = relayer.send_relayer_call(own, calldata, abi.RELAY_PURCHASE_KIND, str(row.internal_id),
                                                        gas=abi.RELAY_PURCHASE_GAS, claim=claim)
    except relayer.RelayError as exc:
        # Nothing was broadcast.
        reverted = abi.v2_revert_error(exc.detail) if exc.code == 'simulation_reverted' else None
        row.refresh_from_db()
        if row.status != 'pending':
            # Signed and recorded before the refusal (sponsor_lock_lost): the receipt decides.
            return schedule_finish(row.pk)
        if reverted == 'CapExceeded':
            return _offer_raise(row)
        if exc.code in BUSY_CODES and row.attempts + 1 < MAX_ATTEMPTS:
            SmartRelayPurchase.objects.filter(pk=row.pk, status='pending').update(attempts=row.attempts + 1)
            raise Later(10, exc.code)
        return _end(row, 'failed', exc.code)
    except Exception:  # noqa: BLE001 — signed, broadcast unknown: the receipt decides (row stays 'unknown')
        logger.exception('relay purchase %s broadcast outcome unknown', row.pk)
        relay_row = relayer.live_tx(own, abi.RELAY_PURCHASE_KIND, str(row.internal_id))
        if relay_row is None:
            row.refresh_from_db()
            if row.status == 'pending':
                # Nothing was signed and recorded (the claim and the durable row are one transaction).
                return _retry_or_fail(row)
    if relay_row is not None:
        SmartRelayPurchase.objects.filter(pk=row.pk).update(
            relay_tx=relay_row, tx_hash=relay_row.signed_tx_hash,
            status='sent' if relay_row.status == 'sent' else 'unknown', updated_at=timezone.now())
    schedule_finish(row.pk)


# ── never stranded ──────────────────────────────────────────────────────

MAX_ERRORS = 5
STALE = timedelta(minutes=20)
GIVE_UP = timedelta(hours=6)


def _retry_or_fail(row):
    from .models import SmartRelayPurchase
    attempts = row.attempts + 1
    SmartRelayPurchase.objects.filter(pk=row.pk).update(attempts=attempts)
    if attempts < MAX_ERRORS:
        raise Later(10, 'error before signing')
    row.attempts = attempts
    return _end(row, 'failed', 'error')


def on_error(row_id: int) -> bool:
    """The task hit an unexpected error (KMS, RPC, database): True to try again; False once the row was told
    as failed. A row no longer 'pending' is left to its own path (the receipt decides a claimed one)."""
    from .models import SmartRelayPurchase
    row = SmartRelayPurchase.objects.select_related('user', 'order').filter(pk=row_id).first()
    if row is None or row.status != 'pending':
        return False
    try:
        _retry_or_fail(row)
    except Later:
        return True
    return False


def sweep() -> dict:
    """Beat: rows a lost schedule (broker outage) or a dead worker left behind. 'pending' ones run again
    (or, past GIVE_UP, are told as failed); 'sent'/'unknown' ones have their receipt read again."""
    from .models import SmartRelayPurchase
    now, out = timezone.now(), {'rerun': 0, 'gave_up': 0, 'finish': 0}
    for row in SmartRelayPurchase.objects.select_related('user', 'order').filter(
            status='pending', updated_at__lt=now - STALE).order_by('updated_at')[:100]:
        if row.created_at < now - GIVE_UP:
            _end(row, 'failed', 'stale')
            out['gave_up'] += 1
            continue
        SmartRelayPurchase.objects.filter(pk=row.pk, status='pending').update(updated_at=now)
        schedule(row.pk, countdown=1)
        out['rerun'] += 1
    for row_id in SmartRelayPurchase.objects.filter(status__in=('sent', 'unknown'),
                                                    updated_at__lt=now - STALE).values_list('pk', flat=True)[:100]:
        SmartRelayPurchase.objects.filter(pk=row_id).update(updated_at=now)
        schedule_finish(row_id, countdown=1)
        out['finish'] += 1
    return out


def schedule_finish(row_id: int, countdown: int = 5) -> None:
    try:
        from .tasks import finish_relay_purchase
        finish_relay_purchase.apply_async(args=[row_id], countdown=countdown)
    except Exception:  # noqa: BLE001
        logger.exception('relay purchase %s finish could not be scheduled', row_id)


def finish(row_id: int) -> None:
    """After the broadcast: the receipt decides; the order is mirrored and the result goes to the chat."""
    from assistant.trades import money
    from marketplace import escrow
    from . import relayer
    from .models import SmartAccountRelayTx, SmartRelayPurchase
    row = SmartRelayPurchase.objects.select_related('user', 'smart_account', 'order').filter(pk=row_id).first()
    if row is None or row.status not in ('sent', 'unknown'):
        return
    relay_row = row.relay_tx or (SmartAccountRelayTx.objects.filter(signed_tx_hash=row.tx_hash).first()
                                 if row.tx_hash else None)
    if relay_row is None:
        raise Later(10, 'no relay row yet')
    if relay_row.status in ('signed', 'sent'):
        relayer.resolve_receipt(relay_row)
        if relay_row.status == 'sent':
            relayer.drop_if_nonce_passed(relay_row)
    if relay_row.status in ('signed', 'sent'):
        raise Later(10, 'receipt pending')
    if relay_row.status != 'confirmed':
        return _end(row, 'failed', relay_row.status, note='reverted')
    receipt = chain.receipt(relay_row.signed_tx_hash) or {}
    event = None
    for log in receipt.get('logs') or []:
        if (log.get('address') or '').lower() == row.smart_account.contract_address.lower():
            event = abi.decode_relay_purchased(log)
            if event:
                break
    spent = row.amount_usd
    if event:
        SmartRelayPurchase.objects.filter(pk=row.pk).update(usd_counted=event['usdCounted'])
        spent = hands_off._usd(int(event['amount']))
    if row.order is not None:
        try:
            escrow.sync_order(row.order)        # the chain is the authority on funded
        except Exception:  # noqa: BLE001 — the keeper re-mirrors depositing orders
            logger.warning('relay purchase %s: order %s not mirrored yet', row.pk, row.order_id, exc_info=True)
    from .relay_trades import lang_of
    _end(row, 'done', '', note='done', what=row.title, spent=money(spent, lang_of(row)))


def status_of(user, internal_id) -> dict | None:
    """The card's view of one purchase (assistantRelayPurchase)."""
    from .models import SmartRelayPurchase
    try:
        row = SmartRelayPurchase.objects.select_related('order').filter(user=user, internal_id=internal_id).first()
    except (TypeError, ValueError):
        row = None
    if row is None:
        return None
    shown = {'sent': 'pending', 'unknown': 'pending'}
    from .relay_trades import result_text
    out = {'status': shown.get(row.status, row.status), 'tx_hash': row.tx_hash or '',
           'label': result_text(row, 'relay_purchase') or label(row),
           'error_code': row.error_code or '', 'amount': format(row.amount_usd, 'f'),
           'order': str(row.order.public_id) if row.order is not None and row.status == 'done' else None}
    if row.status == 'waiting_rule':
        rule = purchase_rule(row.smart_account)
        current = Decimal(rule.amount) if rule is not None else Decimal(0)
        out.update(mode='raise' if rule is not None else 'new', choices=[str(c) for c in CAP_CHOICES],
                   current_cap=str(current) if rule is not None else None,
                   preselected=str(suggested_cap(current + Decimal(row.amount_usd))))
    if row.status == 'waiting_move':
        found = move_route(row)
        out['move_amount'] = format(found.facts['move'], 'f') if found.code == 'move' else None
    return out


def move_route(row):
    from .context import personal_account
    personal = personal_account(row.user)
    return route(row.user, amount=row.amount_usd, personal_address=getattr(personal, 'bsc_address', '') or '')


# ── owner-signed: the Purchase rule and the move in ─────────────────────

def create_purchase_authorization(viewer, *, account, amount: Decimal):
    """The owner's Face for a Purchase rule, claimed once when it is created or
    edited, bound to (account, cap, period, the escrow)."""
    import hashlib
    import json

    from marketplace.escrow import escrow_address
    from . import payouts
    terms = {'kind': 'purchase', 'account': account.contract_address.lower(), 'frequency': FREQUENCY,
             'amount': format(Decimal(amount).quantize(CENT), 'f'), 'payee': escrow_address()}
    digest = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return payouts._authorize(
        viewer, 'purchase', digest, 'smart_account_purchase_rule',
        {'account': account.contract_address.lower(), 'amount': format(amount, 'f'), 'frequency': FREQUENCY},
        'Confirma con Confío Face para que Confío pueda comprar por ti en Comprar.', create={},
        terms=dict(payout_destination=None, payee_address=escrow_address(), rail='', amount_usd=amount,
                   frequency=FREQUENCY))


def prepare_purchase_rule(viewer, amount_usd, proposal=None):
    """The Purchase rule (v2 RuleKind.Purchase) the chat's cap card signs once
    with Face: Confío may pay Comprar orders the person asks for in the chat,
    from the account into the escrow only, up to `amount_usd` per week on
    average (leaky bucket). Created, or edited to raise or lower the cap.
    Kept small (MAX_CAP_USD). Always cUSD+ (unwrapped inside relayPurchase)."""
    from marketplace.escrow import escrow_address
    from . import services
    services._require_enabled()
    if not enabled():
        raise services.PrepareError('purchase_not_available', 'Las compras desde el chat todavía no están disponibles.')
    own = services._own_active(viewer, allow_payment_due=False)
    if not services._chain(hands_off.is_v2, own):
        raise services.PrepareError('needs_migration', 'Primero actualiza tu Cuenta inteligente.')
    amount = services._parse_usd(amount_usd)
    if amount > MAX_CAP_USD:
        raise services.PrepareError('bad_amount', f'El límite de compras es de hasta {services.usd_text(MAX_CAP_USD)} '
                                                  'por semana.')
    escrow = escrow_address()
    token_in = chain.cusd_plus_address()
    if not escrow or not token_in:
        raise services.PrepareError('chain_unavailable')
    existing = purchase_rule(own)
    if existing is not None and (existing.token_in or '').lower() != token_in:
        existing = None
    first_run_at = services._first_run_at(own, existing)
    services._refuse_duplicate_create(viewer, own, existing, 'purchase', amount, FREQUENCY, payee_address=escrow)
    authorization = create_purchase_authorization(viewer, account=own, amount=amount)
    rule_tuple = abi.rule_input('purchase', FREQUENCY, token_in, payee=escrow, amount_usd_wei=int(amount * WAD),
                                first_run_at=first_run_at)
    summary = [f'Confío puede pagar tus compras en Comprar, cuando se lo pidas en el chat, '
               f'{services.trade_cap_text(amount)}',
               'Solo al pago protegido de Comprar. Si una compra se reembolsa, vuelve a tu Cuenta inteligente.']
    return services._rule_batch(viewer, own, existing, dict(
        kind='purchase', token_in=token_in, payee_address=escrow, amount=amount, frequency=FREQUENCY,
        standing_authorization=authorization), rule_tuple, summary, proposal)


def prepare_purchase_move(viewer, purchase_id):
    """Personal wallet -> account in cUSD+, for a chat purchase the account is
    short of: the ordinary deposit batch (Face like any move out of the
    wallet). The amount is the server's, from the purchase."""
    from . import services
    from .models import SmartRelayPurchase
    try:
        row = SmartRelayPurchase.objects.filter(user=viewer.user, internal_id=purchase_id,
                                                status='waiting_move').first()
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise services.PrepareError('not_open', 'Esa compra ya no está pendiente. Pídemela de nuevo en el chat.')
    found = move_route(row)
    if found.code != 'move':
        raise services.PrepareError('not_open', 'Ya no hace falta mover dólares para esta compra.')
    p_plus = services._chain(chain.p_plus_wad)
    units = (int(found.facts['move'] * WAD) * WAD + p_plus - 1) // p_plus
    return services.prepare_deposit(viewer, [{'asset_key': 'cusd_plus', 'units': str(units)}])


# ── every RelayPurchased the reconciler sees ────────────────────────────

PAID_TITLE = {'es': 'Tu Cuenta inteligente pagó una compra', 'pt': 'Sua Cuenta inteligente pagou uma compra',
              'en': 'Your Cuenta inteligente paid for a purchase'}
PAID_BODY = {'es': 'Tu Cuenta inteligente pagó una compra en Comprar',
             'pt': 'Sua Cuenta inteligente pagou uma compra em Comprar',
             'en': 'Your Cuenta inteligente paid for a purchase in Comprar'}
NOT_ASKED = {'es': ' No lo pediste en el chat: si no reconoces esta compra, escríbenos aquí ahora.',
             'pt': ' Você não pediu isso no chat: se não reconhece esta compra, escreva aqui agora.',
             'en': " You didn't ask for it in the chat: if you don't recognize this purchase, write to us here now."}


def on_relay_purchased(account, event) -> None:
    """The owner hears of every hands-off purchase at once: a push always, and a
    chat note unless the chat purchase's own result note covers it. One no
    chat proposal asked for (no SmartRelayPurchase row) is a security alert
    to the owner and to ops."""
    from config.ops_alerts import send_ops_alert
    from marketplace.models import Order
    from .models import SmartRelayPurchase
    from .notifications import _send, safe
    args = event.args or {}
    tx = (event.tx_hash or '').lower()
    row = SmartRelayPurchase.objects.filter(tx_hash__iexact=tx).first()
    order_id = str(args.get('orderId') or '').lower().removeprefix('0x')
    order = Order.objects.filter(order_id32=order_id).select_related('store').first() if order_id else None
    from .relay_trades import FOR_VALUE, conversation_lang, lang_of, said
    user = account.owner_user
    lang = lang_of(row) if row is not None else conversation_lang(user)
    try:
        from assistant.trades import money
        value = money(hands_off._usd(int(args.get('amount') or 0)), lang)
    except Exception:  # noqa: BLE001
        value = ''
    what = f' {order.product_title}' if order is not None else ''
    title = said(PAID_TITLE, lang)
    body = said(PAID_BODY, lang) + (f':{what}' if what else '') + (
        said(FOR_VALUE, lang).format(value=value) if value else '') + '.'
    if row is None:
        body += said(NOT_ASKED, lang)
    safe(_send, user, title, body, kind='relay_purchased', account=account,
         security=row is None, data={'tx_hash': tx})
    if row is None:
        try:
            from assistant.service import post_system_note
            post_system_note(user, body, f'relay_purchased:{tx}:{event.log_index}')
        except Exception:  # noqa: BLE001
            logger.exception('unexpected relay purchase note not posted for %s', tx)
        send_ops_alert(f'Cuenta inteligente: relayPurchase sin pedido en el chat. Cuenta {account.contract_address}, '
                       f'usuario {account.owner_user_id}, orden {order_id or "?"}, tx {tx}, regla {args.get("id")}.',
                       dedupe_key=f'relay_purchase_unasked_{tx}_{event.log_index}', dedupe_seconds=86400)
