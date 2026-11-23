"""CLABE and Pix payment rules on Infinia (payouts.InfiniaAdapter).

One run:

  executeRule -> contract._runPayout -> CusdVault.redeemWithFee(gross,
  usdtOut, relayDeposit): the vault sends the USDT to this run's one-time
  Relay deposit -> Relay delivers USDC to the owner's own Infinia Polygon
  account -> the journey waits for Infinia's credit, converts above the
  rule's FX floor and pays the saved CLABE / Pix key.

The money side is payment_accounts.contract_funding and the ordinary
journey worker. This module binds a run to it, decides skip or wait, and
mirrors the journey onto SmartAccountPayout.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_UP, Decimal
from types import SimpleNamespace

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import SmartAccountPayout, SmartAccountRuleRun

logger = logging.getLogger(__name__)

BPS = 10_000
CENT = Decimal('0.01')
OPEN = ('reserving', 'prepared', 'pending')
SENT = ('onchain_sent', 'funded', 'review', 'paid')
# Relay's cost that grows with the amount (BRIDGING.md, measured 2026-09-15:
# about US$0.043 fixed + 0.19%). Only to suggest a working amount to a
# person; every decision uses the live quote.
BRIDGE_VARIABLE_SHARE = Decimal('0.002')
STALLED_AFTER = timedelta(hours=2)
EXPIRED = 'No se pudo completar a tiempo. Lo intentaremos en la próxima fecha.'


def rail_title(rail: str) -> str:
    from payment_accounts import local_money
    method = local_money.METHODS.get(rail)
    return method.title if method else rail


def skip_from(exc):
    """A provider-side refusal as the run's outcome: a passing one waits
    inside the slot (untold), a final one skips the run and says why."""
    from . import payouts
    return payouts.PayoutSkip(
        exc.code, exc.message, retry_later=exc.retry, wait=exc.retry,
        deactivate=exc.code if exc.code in payouts.DEACTIVATING else '')


def funding_terms(run_pk) -> dict:
    """What a run is authorized to pay, from the database alone. The single
    source of payment_accounts.contract_funding.ContractFunding."""
    from payment_accounts.contract_funding import RAILS, Refused
    from . import chain, payouts
    key = SmartAccountRuleRun.objects.filter(pk=run_pk).values_list(
        'rule__smart_account__contract_address', 'rule__onchain_id').first()
    if key is None:
        raise Refused('run_not_found', EXPIRED)
    # The version first, the rule after it: every use reads both again and
    # refuses a difference, so they never describe two different rules.
    setting = payouts.rule_setting(*key)
    run = SmartAccountRuleRun.objects.select_related(
        'rule__smart_account__owner_user', 'rule__smart_account__owner_account__user',
        'rule__standing_authorization', 'rule__payout_method').filter(pk=run_pk).first()
    if run is None:
        raise Refused('run_not_found', EXPIRED)
    rule, account = run.rule, run.rule.smart_account
    owner = account.owner_account
    if run.status in ('sent', 'ok'):
        # Another worker sent it: its event decides.
        raise Refused('payout_in_progress', payouts.IN_PROGRESS, retry=True)
    if (rule.kind != 'payout' or rule.state != 'onchain' or not rule.active or rule.deleted_at
            # Only the rule's current slot, and only before it is on the wire.
            or run.status not in ('pending', 'failed', 'skipped') or run.scheduled_for != rule.scheduled_for
            or account.status not in ('active', 'cancel_pending') or account.deleted_at
            or account.inherited_at or int(rule.epoch) != int(account.subscription_epoch)
            or owner.user_id != account.owner_user_id):
        raise Refused('rule_not_live', 'Esta regla ya no está activa.')
    if rule.payout_rail not in RAILS:
        raise Refused('provider_path_unverified', 'Ese tipo de cuenta todavía no admite pagos automáticos.')
    problem = payouts.authorization_problem(rule)
    if problem:
        raise Refused(problem, payouts.authorization_message(problem))
    authorization = rule.standing_authorization
    if authorization.amount_usd != rule.amount or authorization.rail != rule.payout_rail:
        raise Refused('no_standing_authorization', payouts.authorization_message('no_standing_authorization'))
    floor = payouts.signed_fx_floor(authorization)
    if floor is None:
        raise Refused(payouts.FLOOR_UNSIGNED, payouts.FLOOR_UNSIGNED_MESSAGE)
    return {
        'rule_event': setting,
        'run': run.pk, 'rule': rule.internal_id, 'owner': owner,
        'destination': payouts.payable_destination(rule.payout_method, authorization),
        'authorization': authorization.internal_id, 'binding_hash': authorization.binding_hash,
        'face_action_key': authorization.face_action_key, 'payout_ref': rule.payout_ref,
        'rail': rule.payout_rail, 'amount': rule.amount, 'contract': account.contract_address,
        'vault': chain.cusd_address(),
        'fee_ceiling': authorization.max_processor_fee_usd or Decimal(0),
        'fx_floor': floor,
    }


def funding_may_land(run_pk, bridge_pk=None) -> bool:
    """An executeRule of this run was broadcast and may fund the bridge."""
    from . import automation
    run = SmartAccountRuleRun.objects.select_related('rule__smart_account').filter(pk=run_pk).first()
    if run is None:
        return False
    sent = SmartAccountPayout.objects.filter(rule_run=run, status__in=SENT)
    if bridge_pk is not None:
        sent = sent.filter(journey__bridge_id=bridge_pk)
    return automation.slot_may_land(run.rule, run) or sent.exists()


# ------------------------------------------------------------ at prepare

def _percent(bps) -> str:
    # 151 bps must not read as the 1,5% it is over.
    places = Decimal('0.1') if int(bps) % 10 == 0 else Decimal('0.01')
    return f'{(Decimal(bps) / 100).quantize(places):f}'.replace('.', ',') + '%'


def suggested_minimum(cost_usd: Decimal, fee: Decimal, usdt: Decimal, amount: Decimal,
                      limit_bps: int) -> Decimal | None:
    """Roughly the smallest whole-dollar amount that works at today's
    prices, or None when none does: the bridge's cost alone fits the limit,
    and what is left still covers the processor's fixed fee."""
    room = Decimal(limit_bps) / BPS - BRIDGE_VARIABLE_SHARE
    if room <= 0 or usdt <= 0:
        return None
    fixed = max(cost_usd - usdt * BRIDGE_VARIABLE_SHARE, Decimal(0))
    needed = max(fixed / room, (fixed + fee) / (1 - BRIDGE_VARIABLE_SHARE))
    gross = needed * amount / usdt * Decimal('1.03')
    return max(gross.to_integral_value(rounding=ROUND_CEILING), amount.to_integral_value() + 1)


def preflight(owner, contract: str, destination, rail: str, amount: Decimal, token_in: str):
    """Before Face, and before the assistant proposes: refuse, with the
    reason, a rule that could never run as things are. Returns the live
    price. Raises payouts.PayoutSkip."""
    from payment_accounts import contract_funding
    from . import payouts, quotes, services
    if payouts.key_rejected(destination):
        # Including a rejection since rewritten DISABLED: such a rule never runs.
        raise payouts.PayoutSkip('payout_method_rejected', services.MESSAGES['payout_method_rejected'])
    from payment_accounts.local_money import is_fixed_amount_qr
    if destination is not None and is_fixed_amount_qr(destination):
        # A rule pays its own signed dollars; a QR with its own amount is paid
        # exactly, once (create_journey refuses it too): never a rule.
        raise payouts.PayoutSkip('payout_fixed_amount_qr', 'Los pagos automáticos no pueden pagar un QR con monto fijo.')
    try:
        route = contract_funding.check_route(owner, destination, rail, amount)
        exit_ = payouts.payout_exit(SimpleNamespace(pk=None, amount=amount, token_in=token_in),
                                    unavailable=services.MESSAGES['payout_quote_unavailable'])
        priced = contract_funding.price(owner=owner, destination=destination, rail=rail, contract=contract,
                                        amount=amount, units=exit_.usdt_wei, route=route)
    except contract_funding.Refused as exc:
        message = exc.message
        if message == contract_funding.TRY_LATER:
            # Nothing is scheduled yet, so nothing "will be retried".
            message = services.MESSAGES['payout_quote_unavailable']
        raise payouts.PayoutSkip(exc.code, message, retry_later=exc.retry) from exc
    except quotes.QuoteUnavailable as exc:
        raise payouts.PayoutSkip('payout_quote_unavailable', services.MESSAGES['payout_quote_unavailable']) from exc
    limit = int(getattr(settings, 'SMART_ACCOUNT_PAYOUT_MAX_BRIDGE_COST_BPS', 150))
    if priced.cost_bps > limit:
        usdt = Decimal(priced.units) / Decimal(10 ** 18)
        fee = contract_funding.fee_usd(priced.fee)
        minimum = suggested_minimum(priced.cost_usd, fee, usdt, amount, limit)
        message = (f'Hoy el envío de {services.usd_text(amount)} por {rail_title(rail)} cuesta '
                   f'{services.usd_text(priced.cost_usd.quantize(CENT, rounding=ROUND_UP))} ({_percent(priced.cost_bps)}), '
                   f'más del {_percent(limit)} que permite una regla.')
        if fee > 0:
            message += f' La comisión fija de {contract_funding.fee_text(fee)} por pago va aparte de ese límite.'
        if minimum is not None and minimum <= services.MAX_RULE_USD:
            message += f' Con los costos de hoy funciona desde unos {services.usd_text(minimum)}.'
        raise payouts.PayoutSkip('bridge_cost_above_limit', message)
    return priced


def signed_fee(priced) -> Decimal:
    """The processor's own fixed fee per payment, which the owner signs as
    a ceiling. Never maintenance or an earlier debt."""
    from payment_accounts import contract_funding
    return contract_funding.fee_usd(getattr(priced, 'fee', None)).quantize(Decimal('0.000001'), rounding=ROUND_UP)


def fee_lines(fee: Decimal) -> list[str]:
    """The fee on the sheet the owner signs, which every build shows line
    by line as sent."""
    if fee <= 0:
        return []
    from payment_accounts.contract_funding import fee_text
    return [f'Comisión del procesador: hasta {fee_text(fee)} por pago, aparte del monto.',
            'No sale de este pago: se suma a la próxima transferencia de tu cuenta local que firmes.',
            'Si la comisión sube, no pagamos hasta que firmes la regla de nuevo.']


def fee_sentence(fee: Decimal) -> str:
    """The same, short enough for the assistant's proposal."""
    if fee <= 0:
        return ''
    from payment_accounts.contract_funding import fee_text
    return (f'Comisión aparte: hasta {fee_text(fee)} por pago, que se suma a la próxima transferencia '
            'de tu cuenta local que firmes.')


# --------------------------------------------------------------- one run

def open_run(rule, run, exit_=None, window=None):
    from payment_accounts import contract_funding
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.eligibility import EligibilityDenied, EligibilityPolicyNotConfigured
    from payment_accounts.services import PaymentAccountError
    from . import payouts
    if run is None:
        raise payouts.PayoutSkip('run_not_found', payouts.EXIT_UNAVAILABLE, retry_later=True, wait=True)
    existing = SmartAccountPayout.objects.filter(rule_run=run).select_related(
        'journey__bridge__quote__money_flow', 'journey__bridge__quote__confio_account').first()
    try:
        if existing is not None:
            plan = _resume(rule, run, existing, window)
            if plan is not None:
                return plan
            exit_ = None    # the closed order's
        return _open(rule, run, exit_, window, replaces=existing)
    except contract_funding.Refused as exc:
        if exc.code == 'deposit_address_reused':
            # Here, not in persist(): its transaction is rolled back.
            contract_funding.alert(
                f'Relay devolvió una dirección de depósito ya usada (regla {rule.pk}, run {run.pk}). '
                'No se envió dinero.', f'contract_funding_reused:{rule.pk}')
        raise skip_from(exc) from exc
    except (EligibilityDenied, EligibilityPolicyNotConfigured, PaymentAccountError, NextError) as exc:
        # A gate that changed between the check and the lock. Nothing was
        # written (one transaction): asked again inside the slot.
        logger.warning('Infinia payout of run %s not opened: %s', run.pk, exc)
        raise payouts.PayoutSkip('provider_unavailable', contract_funding.TRY_LATER,
                                 retry_later=True, wait=True) from exc


def _open(rule, run, exit_, window, replaces=None):
    from payment_accounts import contract_funding
    from . import payouts
    funding = contract_funding.ContractFunding.for_run(run.pk)
    terms = funding.terms()
    owner, destination = terms['owner'], terms['destination']
    if (terms['amount'] != rule.amount or rule.standing_authorization is None
            or terms['authorization'] != rule.standing_authorization.internal_id):
        # Signed again since the worker read it: the next pass uses the new terms.
        raise contract_funding.Refused('authorization_changed', payouts.RULE_CHANGED, retry=True)
    from payment_accounts.local_money import is_fixed_amount_qr
    if destination is not None and is_fixed_amount_qr(destination):
        # Signed before fixed-amount QRs were paid exactly: the rule stops and
        # its owner is told, rather than failing every run.
        raise payouts.PayoutSkip('payout_fixed_amount_qr', 'Los pagos automáticos no pueden pagar un QR con monto fijo.',
                                 deactivate='payout_fixed_amount_qr')
    route = contract_funding.check_route(owner, destination, terms['rail'], terms['amount'])
    contract_funding.require_free(owner, route[0], route[1])
    exit_ = exit_ or payouts.exit_or_wait(rule, window=window)
    priced = contract_funding.price(owner=owner, destination=destination, rail=terms['rail'],
                                    contract=terms['contract'], amount=terms['amount'],
                                    units=exit_.usdt_wei, route=route, fee_ceiling=terms['fee_ceiling'])
    plan = payouts.PayoutPlan(deposit_address=priced.deposit, min_usdt_out=exit_.usdt_wei,
                              bridge_cost_bps=priced.cost_bps, fx_rate=priced.rate,
                              fiat_currency=priced.local.asset, provider=payouts.INFINIA,
                              gross_wei=exit_.gross_wei)
    authorization = rule.standing_authorization
    payouts.check_rule_limits(authorization, plan)      # before anything is reserved
    contract_funding.require_unused(priced)
    minimum = priced.minimum_fx_output(authorization.reference_fx_rate, authorization.fx_tolerance_bps)
    previous = replaces.journey.bridge if replaces is not None else None
    try:
        with transaction.atomic():
            bridge, journey = contract_funding.persist(
                funding, priced, gross_wei=exit_.gross_wei, minimum_fx_output=minimum, replaces=previous)
            values = dict(journey=journey, deposit_address=bridge.deposit_address.lower(),
                          fiat_currency=priced.local.asset, status='prepared')
            if replaces is None:
                SmartAccountPayout.objects.create(
                    rule_run=run, rail=rule.payout_rail, provider=payouts.INFINIA, **values)
            else:
                now = timezone.now()
                if not SmartAccountPayout.objects.filter(
                        pk=replaces.pk, journey_id=replaces.journey_id, status='cancelled').update(
                            created_at=now, updated_at=now, **values):
                    # Replaced or funded late meanwhile: this order is rolled back.
                    raise contract_funding.Refused('payout_in_progress', payouts.IN_PROGRESS, retry=True)
    except IntegrityError as exc:
        raise payouts.PayoutSkip('payout_in_progress', 'Este pago ya está en curso.',
                                 retry_later=True, wait=True) from exc
    plan.journey = journey
    return plan


# An unfunded order that can no longer be sent as it is: closed, and the
# slot gets a fresh one.
REPLACEABLE = ('provider_quote_expired', 'authorization_changed', 'funding_account_changed', 'exit_moved')


def _resume(rule, run, payout, window):
    """A retry of the slot (the relayer call failed or reverted): the SAME
    bridge, journey and USDT while they can still be sent.

    None: that order is closed, unfunded and with no call that may land, and
    the slot may have a fresh one. Never two fundable orders at once."""
    from payment_accounts import contract_funding
    from . import automation, payouts
    busy = payouts.PayoutSkip('payout_in_progress', payouts.IN_PROGRESS, retry_later=True, wait=True)
    if (payout.status not in OPEN + ('cancelled',) or payout.journey_id is None or payout.journey.bridge_id is None
            or automation.slot_may_land(rule, run)):
        raise busy
    journey, bridge = payout.journey, payout.journey.bridge
    quote = bridge.quote
    units = int(quote.amount_units)
    if bridge.source_tx_hash or ((bridge.binding or {}).get(contract_funding.KEY) or {}).get('reported'):
        raise busy
    stale = payout.status == 'cancelled' or journey.stage != 'awaiting_credit'
    try:
        if not stale:
            contract_funding.check_resume(contract_funding.ContractFunding.for_run(run.pk), bridge)
            if payouts.rule_is_plus(rule):
                exit_ = payouts.exit_or_wait(rule, window=window, target=units)
            else:
                exit_ = payouts.exit_or_wait(rule, window=window)
                # The vault's fee moved: the reserved deposit is not this exit.
                stale = exit_.usdt_wei != units
            if not stale:
                rate = contract_funding.rate_now(journey)   # not funded yet: today's rate decides
    except contract_funding.Refused as exc:
        if exc.code not in REPLACEABLE:
            if not exc.retry:
                close_unsent(payout)
            raise
        stale = True
    except payouts.PayoutSkip as exc:
        if exc.code not in REPLACEABLE:
            if not exc.retry_later:
                close_unsent(payout)
            raise
        stale = True
    if stale:
        if not close_unsent(payout):
            raise busy      # being sent, or funded
        payout.status = 'cancelled'
        bound = (quote.money_flow.metadata or {}).get(contract_funding.KEY) or {}
        payouts.check_fresh_order(run, bound.get('attempt'), bridge.created_at)
        return None
    details = quote.money_flow.metadata[contract_funding.KEY]
    return payouts.PayoutPlan(
        deposit_address=payout.deposit_address, min_usdt_out=units, journey=journey,
        bridge_cost_bps=int(details['cost_bps']), fx_rate=rate,
        fiat_currency=payout.fiat_currency, provider=payouts.INFINIA, gross_wei=exit_.gross_wei)


def close_unsent(payout) -> bool:
    """False while a relayer transaction of the run may land, or once it
    is funded: contract_funding.close_unfunded decides under the bridge lock."""
    from payment_accounts import contract_funding
    if payout.journey_id is None or payout.journey.bridge_id is None or payout.status not in OPEN + ('cancelled',):
        return False
    if not contract_funding.close_unfunded(payout.journey.bridge_id):
        return False
    SmartAccountPayout.objects.filter(pk=payout.pk, journey_id=payout.journey_id, status__in=OPEN).update(
        status='cancelled', updated_at=timezone.now())
    return True


def after_onchain(payout, tx_hash: str) -> None:
    """PayoutSent is mirrored: hand its hash over. The bridge worker proves
    it from the receipt; the journey worker does the rest."""
    from payment_accounts import contract_funding
    journey = payout.journey
    if journey is not None and journey.bridge_id:
        try:
            contract_funding.report_funding(journey.bridge_id, tx_hash)
        except Exception:  # noqa: BLE001 — mirror_payout reports it again
            logger.exception('report_funding failed for payout %s', payout.pk)
    mirror_payout(payout.pk)


# ---------------------------------------------------------------- mirror

def money_location(journey) -> str:
    """Where the money is, for the ops alert (ids only)."""
    bridge = journey.bridge
    if bridge.status == 'refunded':
        return 'devuelto como USDT al contrato de la Cuenta inteligente'
    payout = journey.payout_operation
    if payout is not None and payout.status in ('succeeded', 'settling', 'processing', 'submitted', 'unknown'):
        return f'en el pago de Infinia {payout.internal_id}'
    fx = journey.fx_operation
    if fx is not None and fx.status not in ('created', 'failed', 'reversed'):
        return (f'convertido o convirtiéndose en la cuenta local {journey.local_account.internal_id} '
                f'(conversión {fx.internal_id})')
    if bridge.provider_credit_id:
        return f'en USDC en la cuenta Infinia del dueño {journey.crypto_account.internal_id}'
    if bridge.status == 'delivered':
        return f'entregado en Polygon (tx {bridge.destination_tx_hash}), sin crédito de Infinia todavía'
    if bridge.source_tx_hash:
        return f'en el puente Relay (depósito {bridge.deposit_address}, tx {bridge.source_tx_hash})'
    return f'sin financiamiento probado para el depósito {bridge.deposit_address}'


def _alert(text: str, key: str) -> None:
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: {text}', dedupe_key=key, dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')


def _fiat_text(value: Decimal) -> str:
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def mirror_payout(payout_pk: int) -> str | None:
    """Copy the journey's outcome onto the payout: delivered amount and
    currency and one message when paid; ops for a refund, a review or a
    stall, always with where the money is."""
    from payment_accounts import contract_funding
    from . import notifications, payouts
    payout = SmartAccountPayout.objects.select_related(
        'rule_run__rule__smart_account', 'journey__money_flow', 'journey__local_account',
        'journey__crypto_account', 'journey__bridge__quote__money_flow', 'journey__fx_operation',
        'journey__payout_operation').filter(pk=payout_pk).first()
    if payout is None or payout.journey_id is None or payout.status == 'refunded':
        return None
    journey, bridge, run = payout.journey, payout.journey.bridge, payout.rule_run
    if bridge is None:
        return None
    if (journey.stage == 'needs_review' and journey.failure_code == contract_funding.DELAYED
            and bridge.status == 'delivered' and bridge.provider_credit_id):
        try:    # parked by a delay alone, proven since
            contract_funding.reopen_delayed(bridge.pk)
            journey.refresh_from_db()
        except Exception:  # noqa: BLE001 — next pass
            logger.exception('payout %s could not be reopened', payout.pk)
    data = (bridge.binding or {}).get(contract_funding.KEY) or {}
    reported = bool(data.get('reported'))
    if payout.status in SENT and not reported and not bridge.source_tx_hash and run.tx_hash:
        try:    # after_onchain's report was lost
            contract_funding.report_funding(bridge.pk, run.tx_hash)
            bridge.refresh_from_db()
            journey.refresh_from_db()
            reported = True
        except Exception:  # noqa: BLE001 — next pass
            logger.exception('funding report of payout %s failed', payout.pk)
    sent = payout.status in SENT or reported or bool(bridge.source_tx_hash)
    if bridge.status == 'refunded':
        status = 'refunded'         # final receipts prove it is back at the contract
    elif journey.stage == 'completed':
        status = 'paid'
    elif journey.stage == 'failed':
        status = 'review' if sent else 'cancelled'
    elif journey.stage == 'needs_review':
        # Not seen sent: ops already heard from the bridge, and a late
        # PayoutSent must still find this payout.
        status = 'review' if sent else payout.status
    elif bridge.source_tx_hash:
        status = 'funded'
    else:
        status = payout.status

    if status != payout.status:
        values = {'status': status, 'updated_at': timezone.now()}
        first_delivery = status == 'paid' and payout.fiat_amount is None
        if status == 'paid':
            contract_funding.record_fee_debt(journey)
            if journey.payout_operation is not None:
                values['fiat_amount'] = Decimal(journey.payout_operation.source_amount).quantize(CENT)
                values['fiat_currency'] = journey.local_account.asset
        if not SmartAccountPayout.objects.filter(
                pk=payout.pk, status=payout.status, journey_id=payout.journey_id).update(**values):
            return None
        payouts.tell_run(payout.rule_run_id, status)
        if first_delivery:
            amount = values.get('fiat_amount')
            notifications.safe(notifications.payout_delivered, run,
                               _fiat_text(amount) if amount is not None else '', journey.local_account.asset)
        elif status in ('review', 'refunded'):
            reason = '/'.join(dict.fromkeys(c for c in (journey.failure_code, bridge.failure_code) if c)) or status
            _alert(f'pago {rail_title(payout.rail)} {"devuelto" if status == "refunded" else "en revisión"} '
                   f'(payout {payout.pk}, journey {journey.internal_id}, {reason}). '
                   f'El dinero está {money_location(journey)}.'
                   + (' Si ya se puede pagar: admin de pagos, "Revisar de nuevo y continuar".'
                      if status == 'review' and journey.failure_code in contract_funding.RECHECKABLE else ''),
                   f'smart_payout_journey_{status}_{payout.pk}_{reason}')
    if status in ('onchain_sent', 'funded') and payout.created_at < timezone.now() - STALLED_AFTER:
        _alert(f'pago {rail_title(payout.rail)} detenido más de 2 horas (payout {payout.pk}, journey '
               f'{journey.internal_id}, etapa {journey.stage}). El dinero está {money_location(journey)}.',
               f'smart_payout_journey_stalled_{payout.pk}')
    return status


def mirror_payouts() -> dict:
    out = {'updated': 0, 'errors': 0}
    rows = SmartAccountPayout.objects.filter(journey__isnull=False).filter(
        ~Q(status__in=('paid', 'refunded', 'cancelled'))
        # A paid run can be reversed, and a cancelled one funded late.
        | Q(status__in=('paid', 'cancelled'), journey__stage='needs_review'))
    for pk, before in rows.values_list('pk', 'status'):
        try:
            if mirror_payout(pk) not in (None, before):
                out['updated'] += 1
        except Exception:  # noqa: BLE001 — retried next pass
            logger.exception('payout %s journey mirror failed', pk)
            out['errors'] += 1
    return out
