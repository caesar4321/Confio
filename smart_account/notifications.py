"""Notifications for Cuenta inteligente (spec 7.7), through the existing
notification service (in-app row + push). Copy in Spanish.

A notification failure never blocks an owner's next action or a task's money
step: callers use `safe(...)`. Deduplication is the caller's (timestamps on
the mirror rows), so a retried task does not send twice.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

ACTION_URL = 'confio://smart-account'
BENEFICIARY_URL = 'confio://smart-account/beneficiary'


def safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — telling someone must never break the flow
        logger.exception('smart account notification failed: %s', getattr(fn, '__name__', fn))
        return None


def _usd(value) -> str:
    return 'US$' + format(Decimal(value).quantize(Decimal('0.01')), ',.2f')


def _date(dt, owner=None) -> str:
    """With `owner`, the day it is where they live."""
    if not dt:
        return ''
    zone = None
    if owner is not None:
        from .services import owner_tz
        zone = owner_tz(owner)
    return timezone.localtime(dt, zone).strftime('%d/%m/%Y')


def _name(user) -> str:
    from .services import display_name
    return display_name(user)


# kind -> the screen the app opens (route names agreed with the app build).
SCREENS = {
    'fee_collected': 'SmartAccountBilling', 'fee_due': 'SmartAccountBilling',
    'payment_notice': 'SmartAccountBilling', 'forced_sale_eve': 'SmartAccountBilling',
    'forced_sale_done': 'SmartAccountBilling', 'forced_sale_failed': 'SmartAccountBilling',
    'cancelled': 'SmartAccountHome', 'assets_returned': 'SmartAccountHome', 'price_change': 'SmartAccountBilling',
    'rule_ok': 'SmartAccountRules', 'rule_skipped': 'SmartAccountRules', 'rule_failed': 'SmartAccountRules',
    'payout_delivered': 'SmartAccountRules', 'rule_deactivated': 'SmartAccountRules',
    'payout_resumed': 'SmartAccountRules', 'card_pulled': 'SmartAccountRules',
    'payout_unconfirmed': 'SmartAccountRules',
    'payout_review': 'SmartAccountRules', 'payout_refunded': 'SmartAccountRules',
    'beneficiary_named': 'BeneficiaryInvite', 'beneficiary_removed': 'BeneficiaryInvite',
    'beneficiary_accepted': 'BeneficiaryStatus', 'beneficiary_declined': 'BeneficiaryStatus',
    'beneficiary_stale_address': 'BeneficiaryStatus',
    'claim_initiated': 'BeneficiaryStatus', 'claim_cancelled': 'BeneficiaryStatus',
    'claim_executed_previous_owner': 'SmartAccountHome',
    'claim_initiated_beneficiary': 'BeneficiaryClaimStatus', 'claim_cancelled_beneficiary': 'BeneficiaryClaimStatus',
    'claim_executable': 'BeneficiaryClaimStatus',
    'claim_executed_new_owner': 'InheritedAccount',
    'watch_triggered': 'SmartAccountWatches',
}


def _send(user, title: str, message: str, *, kind: str, account=None, security: bool = False,
          data=None, action_url: str = ACTION_URL):
    from notifications.models import NotificationType
    from notifications.utils import create_notification
    if user is None:
        return None
    return create_notification(
        user=user,
        notification_type=NotificationType.SECURITY_ALERT if security else NotificationType.SYSTEM,
        title=title[:200], message=message,
        data={'smart_account_event': kind, 'screen': SCREENS.get(kind, 'SmartAccountHome'), **(data or {})},
        related_object_type='SmartAccount',
        related_object_id=str(account.pk) if account is not None else None,
        action_url=action_url,
    )


# ── billing ─────────────────────────────────────────────────────────────

def fee_collected(account, charge):
    return _send(account.owner_user, 'Cuenta inteligente renovada',
                 f'Cobramos {_usd(charge.fee_usd)} desde tu Cuenta inteligente. '
                 f'Tu plan está pagado hasta el {_date(charge.period_end)}.',
                 kind='fee_collected', account=account)


def fee_due(account, fee_usd, shortfall_usd):
    return _send(account.owner_user, 'Falta saldo para tu Cuenta inteligente',
                 f'Tu plan venció y faltan {_usd(shortfall_usd)} para cubrir {_usd(fee_usd)}. '
                 'Agrega dólares a tu Cuenta inteligente. Mientras tanto, tus reglas automáticas están en pausa.',
                 kind='fee_due', account=account)


def payment_notice_started(account, sale_allowed_at, candidates):
    what = ', '.join(candidates) if candidates else 'tus inversiones'
    return _send(account.owner_user, 'Aviso de pago de tu Cuenta inteligente',
                 f'Si no agregas dólares, a partir del {_date(sale_allowed_at)} venderemos parte de {what} '
                 'para cubrir un período. Nada vuelve a tu cuenta personal por falta de pago.',
                 kind='payment_notice', account=account)


def forced_sale_eve(account, candidates):
    what = ', '.join(candidates) if candidates else 'tus inversiones'
    return _send(account.owner_user, 'Mañana venderemos para cubrir tu plan',
                 f'Mañana venderemos parte de {what} para cubrir un período de tu Cuenta inteligente. '
                 'Si agregas dólares hoy, no se vende nada.',
                 kind='forced_sale_eve', account=account)


def forced_sale_done(account, charge):
    return _send(account.owner_user, 'Vendimos parte de tus inversiones',
                 f'Vendimos lo necesario para cubrir {_usd(charge.fee_usd)} de tu Cuenta inteligente. '
                 f'Tu plan está pagado hasta el {_date(charge.period_end)}.',
                 kind='forced_sale_done', account=account)


def forced_sale_failed(account):
    return _send(account.owner_user, 'No pudimos cubrir tu plan',
                 'No pudimos vender para cubrir tu Cuenta inteligente. Volveremos a intentarlo. '
                 'Agrega dólares para reactivar tus reglas automáticas.',
                 kind='forced_sale_failed', account=account)


def cancellation_signed(account):
    return _send(account.owner_user, 'Cancelaste tu Cuenta inteligente',
                 f'Tus activos vuelven a tu cuenta personal el {_date(account.paid_until)}. '
                 'Desde esa fecha tu beneficiario deja de estar cubierto.',
                 kind='cancelled', account=account)


def assets_returned(account):
    return _send(account.owner_user, 'Tus activos volvieron a tu cuenta personal',
                 'Devolvimos todo lo que había en tu Cuenta inteligente a tu cuenta personal.',
                 kind='assets_returned', account=account)


def price_change_scheduled(user, plan_label: str, new_price: str, effective_at, *, before_renewal: bool = False):
    lead = 'Tu próxima renovación' if before_renewal else 'Desde tu próxima renovación'
    return _send(user, 'Cambio de precio de la Cuenta inteligente',
                 f'{lead} del plan {plan_label} costará US${new_price} (vigente desde el {_date(effective_at)}).',
                 kind='price_change')


# ── rules ───────────────────────────────────────────────────────────────

def rule_run(run):
    rule = run.rule
    account = rule.smart_account
    label = {'send': 'envío automático', 'payout': 'pago automático',
             'buy': 'compra automática'}.get(rule.kind, 'regla automática')
    # Still on this slot: it is being retried, until the date in the message.
    pending = (run.status in ('skipped', 'failed') and rule.active and rule.scheduled_for is not None
               and rule.scheduled_for == run.scheduled_for)
    if run.status == 'ok':
        title, body = f'Tu {label} se realizó', f'{_usd(rule.amount)} · {run.message or "Listo."}'
        if rule.active and rule.scheduled_for and rule.scheduled_for > timezone.now():
            body += f' Próxima fecha: {_date(rule.scheduled_for, account.owner_user)}.'
    elif pending:
        title, body = f'Tu {label} está pendiente', run.message or 'Lo estamos reintentando.'
    elif run.status == 'skipped':
        title, body = f'Tu {label} no se realizó', run.message or 'Lo intentaremos en la próxima fecha.'
    else:
        title, body = f'No pudimos hacer tu {label}', run.message or 'No se realizó.'
    return _send(account.owner_user, title, body, kind=f'rule_{run.status}', account=account,
                 data={'rule_id': str(rule.internal_id)})


def _paid_to(run) -> str:
    """Who this run paid (the rule may name someone else by now), masked:
    a push shows on a locked screen. Only a bank's answer is shown as a
    holder; a typed name is marked as the owner's."""
    from payment_accounts.models import PayoutDestination
    from . import payouts, services
    from .models import SmartAccountPagoMovilDestination, SmartAccountPayout
    rule = run.rule
    destination = rule.payout_method or rule.pagomovil_destination
    payout = SmartAccountPayout.objects.select_related('journey', 'ramp').filter(rule_run=run).first()
    if payout is not None and payout.journey is not None:
        paid = (payout.journey.destination_snapshot or {}).get('destination_internal_id')
        row = PayoutDestination.objects.filter(internal_id=paid).first() if paid else None
        destination = row or destination
    elif payout is not None and payout.ramp is not None:
        who = ((payout.ramp.metadata or {}).get('ve_send') or {}).get('beneficiary') or {}
        if who:
            wanted = payouts._payment_identity(who.get('phone'), who.get('bank_code'), who.get('cedula'))
            row = next((d for d in SmartAccountPagoMovilDestination.all_objects.filter(
                user_id=payout.ramp.actor_user_id)
                if payouts._payment_identity(d.phone, d.bank_code, d.id_number) == wanted), None)
            label = row.label if row is not None else f'Pago Móvil · {str(who.get("phone") or "")[-4:]}'
            return services.marked_label(label, who.get('name') or '')
    if destination is None:
        return 'tu destino'
    shown = services.masked_destination(destination)
    if getattr(destination, 'phone', None) is not None:
        return services.marked_label(shown, destination.holder_name)
    if services.payout_holder_state(destination) == services.HOLDER_VERIFIED:
        return ' · '.join(part for part in (shown, destination.holder_name) if part)
    return services.marked_label(shown, services.owner_holder(destination))


def payout_delivered(run, fiat_amount, currency):
    account = run.rule.smart_account
    label = _paid_to(run)
    if fiat_amount:
        amount = f'{currency} {fiat_amount}' if currency == 'Bs.' else f'{fiat_amount} {currency}'
        body = f'Enviamos {amount} a {label}.'
    else:
        body = f'Tu pago llegó a {label}.'
    return _send(account.owner_user, 'Tu pago automático llegó', body, kind='payout_delivered', account=account)


def payout_resumed(run):
    """A payout the owner was told did not happen left the account after all
    (its call landed late): it is on its way, under review."""
    rule = run.rule
    account = rule.smart_account
    return _send(account.owner_user, 'Tu pago automático sí salió',
                 f'Tu pago automático de {_usd(rule.amount)} salió de tu Cuenta inteligente. '
                 'Lo estamos revisando y te avisaremos cuando llegue.',
                 kind='payout_resumed', account=account, data={'rule_id': str(rule.internal_id), 'run_id': run.pk})


def payout_unconfirmed(run):
    """A slot that ends with a payment that may have left and no executed
    run: neither "done" nor "not done" would be true."""
    rule = run.rule
    account = rule.smart_account
    return _send(account.owner_user, 'Tu pago automático está en revisión', run.message,
                 kind='payout_unconfirmed', account=account,
                 data={'rule_id': str(rule.internal_id), 'run_id': run.pk})


def payout_review(run, amount):
    """Parked, refused by the bank or unknown: it may or may not have
    arrived. Not when another notice already said so for this run."""
    from notifications.models import Notification
    rule = run.rule
    account = rule.smart_account
    if Notification.objects.filter(
            user=account.owner_user, data__run_id=run.pk, data__smart_account_event__in=(
                'payout_review', 'payout_rate_held', 'payout_resumed', 'payout_unconfirmed')).exists():
        return None
    return _send(account.owner_user, 'Tu pago automático está en revisión',
                 f'Estamos revisando tu pago automático de {_usd(amount)}: no confirmamos que haya llegado a quien '
                 'recibe. No lo repitas.',
                 kind='payout_review', account=account, data={'rule_id': str(rule.internal_id), 'run_id': run.pk})


def payout_refunded(run, amount):
    rule = run.rule
    account = rule.smart_account
    return _send(account.owner_user, 'Tu pago automático volvió',
                 f'Tu pago automático de {_usd(amount)} no llegó a quien recibe: el dinero volvió a tu Cuenta '
                 'inteligente. Puede ser un poco menos por el costo de devolverlo.',
                 kind='payout_refunded', account=account, data={'rule_id': str(rule.internal_id), 'run_id': run.pk})


def rule_deactivated(rule, reason: str):
    from .payouts import authorization_message
    return _send(rule.smart_account.owner_user, 'Pausamos un pago automático', authorization_message(reason),
                 kind='rule_deactivated', account=rule.smart_account, data={'reason': reason})


def card_pulled(pull):
    """Each card pull (decision 35): what left the account (the gross, the
    0.9% exit fee included) and the room left this period."""
    from . import cards
    account = pull.smart_account
    usdt = Decimal(int(pull.usdt_out_wei)) / Decimal(10 ** 18)  # BSC USDT: 18 decimals
    fee = max(Decimal(0), Decimal(pull.usd_spent) - usdt)
    label = cards.spender_label(pull.spender)
    body = (f'{label} usó {_usd(pull.usd_spent)} de tu Cuenta inteligente '
            f'({_usd(usdt)} del pago y {_usd(fee)} de comisión de salida).')
    rule = pull.rule
    if rule is not None and pull.period_start is not None and pull.spent_in_period is not None:
        left = cards.remaining_usd(rule.amount, pull.spent_in_period)
        body += f' Te quedan {_usd(left)} hasta el {_date(pull.period_start + cards.gap(rule.frequency))}.'
    return _send(account.owner_user, f'Tu tarjeta usó {_usd(pull.usd_spent)}', body, kind='card_pulled',
                 account=account, data={'rule_id': str(rule.internal_id)} if rule is not None else None)


# ── beneficiary ─────────────────────────────────────────────────────────

def beneficiary_named(row, *, reminder: bool = False):
    owner = row.smart_account.owner_user
    days = row.challenge_window_seconds // 86400
    title = 'Recuerda responder: te nombraron beneficiario' if reminder else 'Te nombraron beneficiario'
    return _send(row.beneficiary_user, title,
                 f'{_name(owner)} te nombró beneficiario de su Cuenta inteligente (plazo de reclamo: {days} días). '
                 f'Acepta o rechaza antes del {_date(row.expires_at)}.',
                 kind='beneficiary_named', account=row.smart_account,
                 data={'designationId': str(row.designation_id)}, action_url=BENEFICIARY_URL)


def beneficiary_accepted(row):
    return _send(row.smart_account.owner_user, 'Tu beneficiario aceptó',
                 f'{_name(row.beneficiary_user)} aceptó ser beneficiario de tu Cuenta inteligente.',
                 kind='beneficiary_accepted', account=row.smart_account)


def beneficiary_declined(row):
    return _send(row.smart_account.owner_user, 'Tu beneficiario no aceptó',
                 f'{_name(row.beneficiary_user)} rechazó ser beneficiario de tu Cuenta inteligente.',
                 kind='beneficiary_declined', account=row.smart_account)


def beneficiary_removed(row):
    return _send(row.beneficiary_user, 'Ya no eres beneficiario',
                 f'{_name(row.smart_account.owner_user)} cambió o quitó a su beneficiario.',
                 kind='beneficiary_removed', data={'designationId': str(row.designation_id)},
                 action_url=BENEFICIARY_URL)


def beneficiary_address_changed(row):
    return _send(row.smart_account.owner_user, 'Vuelve a nombrar a tu beneficiario',
                 f'La billetera de {_name(row.beneficiary_user)} cambió. La designación apunta a la billetera '
                 'anterior: nómbralo de nuevo para que siga cubierto.',
                 kind='beneficiary_stale_address', account=row.smart_account, security=True)


# ── claims ──────────────────────────────────────────────────────────────

def claim_initiated_owner(claim, *, reminder: bool = False):
    row = claim.beneficiary_row
    account = row.smart_account
    title = 'Reclamo en curso sobre tu Cuenta inteligente' if reminder else 'Iniciaron un reclamo de tu Cuenta inteligente'
    result = _send(account.owner_user, title,
                   f'{_name(row.beneficiary_user)} inició un reclamo. Si no firmas ninguna acción antes del '
                   f'{_date(claim.executable_at)}, la cuenta y todo lo que contiene pasará a su nombre. '
                   'Abre Confío y cancela el reclamo con un toque.',
                   kind='claim_initiated', account=account, security=True)
    safe(_claim_email, account.owner_user, title, row, claim)
    safe(_claim_assistant_note, account.owner_user, row, claim)
    return result


def _claim_email(user, title, row, claim):
    """Email is one of the owner's channels for the claim schedule."""
    email = (getattr(user, 'email', '') or '').strip()
    if not email:
        return
    from django.core.mail import send_mail
    send_mail(
        f'Confío: {title}',
        f'{_name(row.beneficiary_user)} inició un reclamo de tu Cuenta inteligente.\n\n'
        f'Si no firmas ninguna acción antes del {_date(claim.executable_at)}, la cuenta y todo lo que contiene '
        'pasará a su nombre. Abre la app de Confío y cancela el reclamo.\n',
        None, [email], fail_silently=False)


def _claim_assistant_note(user, row, claim):
    """The assistant thread is one of the owner's channels (spec 7.7): a
    system line in their personal support thread, at most one per claim and
    day (notices are at least a day apart, so each reminder is a new line
    and a retried one is not)."""
    from assistant.service import post_system_note
    post_system_note(
        user,
        f'Hay un reclamo en curso sobre tu Cuenta inteligente: {_name(row.beneficiary_user)} podrá recibir la '
        f'cuenta y todo lo que contiene a partir del {_date(claim.executable_at)}. Si sigues usando tu cuenta, '
        'cancela el reclamo con un toque desde la Cuenta inteligente.',
        f'smart_claim:{claim.pk}:{timezone.localdate():%Y%m%d}')


def claim_initiated_beneficiary(claim):
    row = claim.beneficiary_row
    return _send(row.beneficiary_user, 'Iniciaste el reclamo',
                 f'Podrás completar el reclamo a partir del {_date(claim.executable_at)}.',
                 kind='claim_initiated_beneficiary', data={'designationId': str(row.designation_id)},
                 action_url=BENEFICIARY_URL)


def claim_cancelled(claim):
    row = claim.beneficiary_row
    account = row.smart_account
    _send(account.owner_user, 'Reclamo cancelado', 'Cancelaste el reclamo sobre tu Cuenta inteligente.',
          kind='claim_cancelled', account=account, security=True)
    until = f' Podrás iniciar otro a partir del {_date(row.cooldown_until)}.' if row.cooldown_until else ''
    return _send(row.beneficiary_user, 'El reclamo fue cancelado',
                 f'{_name(account.owner_user)} canceló el reclamo.{until}',
                 kind='claim_cancelled_beneficiary', data={'designationId': str(row.designation_id)},
                 action_url=BENEFICIARY_URL)


def claim_executable(claim):
    row = claim.beneficiary_row
    return _send(row.beneficiary_user, 'Ya puedes completar el reclamo',
                 'El plazo terminó. Abre Confío para recibir la cuenta.',
                 kind='claim_executable', data={'designationId': str(row.designation_id)},
                 action_url=BENEFICIARY_URL)


def claim_executed(account, previous_owner, new_owner):
    _send(previous_owner, 'Tu Cuenta inteligente cambió de dueño',
          f'El reclamo se completó y la cuenta pasó a {_name(new_owner)}.',
          kind='claim_executed_previous_owner', security=True)
    return _send(new_owner, 'Recibiste una cuenta heredada',
                 f'La Cuenta inteligente de {_name(previous_owner)} ahora es tuya. '
                 'Puedes mover sus activos a tu cuenta personal o a tu Cuenta inteligente.',
                 kind='claim_executed_new_owner', account=account,
                 data={'inheritedAccountId': str(account.internal_id)})


def payout_rate_held(run_pk, amount):
    """A payment whose money had left when the rate went outside its limit,
    parked after the wait: true of both rails, and told once per run."""
    from notifications.models import Notification
    from .models import SmartAccountRuleRun
    run = SmartAccountRuleRun.objects.select_related('rule__smart_account__owner_user').filter(pk=run_pk).first()
    if run is None:
        return None
    account = run.rule.smart_account
    if Notification.objects.filter(user=account.owner_user, data__smart_account_event='payout_rate_held',
                                   data__run_id=run.pk).exists():
        return None
    return _send(account.owner_user, 'Tu pago automático está detenido',
                 f'Tu pago de {_usd(amount)} salió de tu Cuenta inteligente, pero no conseguimos una tasa '
                 'de cambio dentro del límite de este pago y no lo enviamos a quien recibe. Lo estamos revisando: '
                 'no lo repitas.',
                 kind='payout_rate_held', account=account,
                 data={'run_id': run.pk, 'rule_id': str(run.rule.internal_id), 'screen': 'SmartAccountRules'})
