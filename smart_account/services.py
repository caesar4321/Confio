"""Prepare steps for every owner- and beneficiary-signed action (spec 7.3).

Each function validates, builds the exact call list and registers a
SmartAccountPreparedAction; the relay policy (relay_policy.py) later accepts
a batch only if it byte-matches that row. Nothing here writes mirror state
that reflects the chain: rules and designations created here are inert
drafts until reconcile.py sees their event.

Authority never comes from a client-supplied account id or address: the
signer is the JWT user's personal account, and every other account is
reached through a server-issued opaque id checked against that user.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import abi, assets as assets_mod, chain, context, offer
from .models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountStandingAuthorization,
)

logger = logging.getLogger(__name__)

WAD = 10 ** 18
PREPARED_TTL_SECONDS = 15 * 60
# The sponsor endpoint takes at most 4 own calls (plus an optional referral arm).
MAX_CALLS = 4
MAX_WITHDRAW_ALL_TOKENS = 12
MIN_RULE_USD = Decimal('1.00')
MAX_RULE_USD = Decimal('10000.00')

MESSAGES = {
    'disabled': 'La Cuenta inteligente todavía no está disponible.',
    'bad_plan': 'Elige el plan anual o el mensual.',
    'disclosures_required': 'Acepta las condiciones para continuar.',
    'already_subscribed': 'Ya tienes una Cuenta inteligente activa.',
    'no_account': 'Todavía no tienes una Cuenta inteligente.',
    'account_not_active': 'Tu Cuenta inteligente no está activa.',
    'payment_due': 'Tu Cuenta inteligente tiene un pago pendiente. Agrega dólares para continuar.',
    'bad_asset': 'No reconocemos ese activo.',
    'bad_amount': 'Revisa el monto.',
    'insufficient_balance': 'No tienes saldo suficiente.',
    'nothing_to_move': 'No hay nada para mover.',
    'too_many_assets': 'Son demasiados activos para una sola firma. Mueve el resto después.',
    'first_fee_short': 'Agrega dólares suficientes para cubrir el primer período.',
    'chain_unavailable': 'No pudimos consultar la red. Inténtalo de nuevo en unos minutos.',
    'bad_direction': 'Dirección no válida.',
    'bad_batch_index': 'Ese paso ya no existe. Vuelve a abrir la pantalla.',
    'bad_frequency': 'Elige una frecuencia válida.',
    'payee_not_found': 'No encontramos a esa persona en Confío.',
    'payee_is_self': 'No puedes programar un envío a ti mismo.',
    'payee_no_wallet': 'Esa persona todavía no puede recibir en Confío.',
    'rule_not_found': 'No encontramos esa regla.',
    'rule_kind_mismatch': 'Esa regla es de otro tipo.',
    'payout_not_available': 'Los pagos automáticos a cuentas bancarias todavía no están disponibles.',
    'payout_method_not_found': 'No encontramos ese destino guardado.',
    'payout_rail_not_available': 'Ese tipo de cuenta todavía no admite pagos automáticos.',
    'payout_method_unverified': 'Revisa de nuevo a quien recibe antes de programar el pago.',
    'stock_needs_dollar_plus': 'La compra automática de acciones usa Confío Dollar+.',
    'trade_not_available': 'Esta inversión no está disponible para tu cuenta.',
    'beneficiary_disabled': 'El beneficiario todavía no está disponible.',
    'disclosure_required': 'Acepta la condición del beneficiario para continuar.',
    'bad_window': 'Elige un plazo de 90, 180 o 365 días.',
    'beneficiary_not_found': 'No encontramos a esa persona en Confío.',
    'beneficiary_is_self': 'No puedes nombrarte a ti mismo como beneficiario.',
    'beneficiary_no_wallet': 'Esa persona todavía no tiene una billetera activa en Confío.',
    'beneficiary_unverified': 'Tu beneficiario debe verificar su identidad en Confío antes de ser nombrado.',
    'beneficiary_ineligible': 'Por su país de residencia, esa persona no puede ser beneficiaria.',
    'beneficiary_residence_unknown': 'No pudimos confirmar el país de residencia de esa persona. '
                                     'Debe completar su perfil en Confío antes de ser nombrada.',
    'beneficiary_on_hold': 'Esa persona no puede ser nombrada beneficiaria en este momento.',
    'designation_not_found': 'No encontramos esa designación.',
    'designation_not_pending': 'Esa designación ya no está pendiente.',
    'designation_expired': 'El plazo para aceptar venció. Pide que te nombren de nuevo.',
    'designation_acceptance_in_progress': ('Ya empezaste a aceptar esta designación. Si no la firmaste, '
                                           'podrás rechazarla en una hora.'),
    'designation_already_accepted': 'Ya aceptaste esta designación.',
    'no_beneficiary': 'No tienes un beneficiario registrado.',
    'no_pending_designation': 'No tienes una designación pendiente.',
    'no_claim': 'No hay un reclamo pendiente.',
    'claim_not_allowed': 'Todavía no puedes iniciar un reclamo.',
    'claim_not_executable': 'El plazo del reclamo todavía no termina.',
    'inherited_not_found': 'No encontramos esa cuenta heredada.',
    'bad_destination': 'Destino no válido.',
    'no_own_account': 'Necesitas tu propia Cuenta inteligente activa para mover los activos allí.',
    'identity_hold': 'Tu cuenta está en revisión. Escríbenos por soporte para continuar.',
    'bad_trade': 'No pudimos validar esa operación.',
    'complex_product_ack_required': ('Para comprar fondos apalancados o inversos, actualiza la app y confirma '
                                     'que entiendes cómo funcionan.'),
    'crypto_ack_required': 'Acepta primero los riesgos de bitcoin y oro en Invertir.',
    'review_amount_cap': 'Ese monto supera el límite de tu cuenta. Prueba con un monto menor.',
    'stock_quote_window': 'El precio se está actualizando. Inténtalo de nuevo en unos segundos.',
}


class PrepareError(Exception):
    def __init__(self, code: str, message: str = ''):
        self.code = code
        self.message = message or MESSAGES.get(code) or offer.BLOCKED.get(code) or 'No pudimos preparar la operación.'
        super().__init__(code)


@dataclass
class PreparedBatch:
    request_id: str
    calls: list
    kind: str
    summary: list = field(default_factory=list)
    not_after: int | None = None


# ── helpers ─────────────────────────────────────────────────────────────

def usd_text(value) -> str:
    return 'US$' + format(Decimal(value).quantize(Decimal('0.01')), ',.2f')


def calls_hash(calls: list) -> str:
    canonical = [{'to': c['to'].lower(), 'value': str(int(c['value'])), 'data': c['data'].lower()} for c in calls]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def display_name(user) -> str:
    name = ' '.join(p for p in [(user.first_name or '').strip(), (user.last_name or '').strip()] if p)
    return name or (user.username or 'Usuario Confío')


def _chain(fn, *args):
    """A chain read on a prepare path: unreadable is an error, never a default."""
    try:
        return fn(*args)
    except PrepareError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('smart account chain read failed: %s', exc, exc_info=True)
        raise PrepareError('chain_unavailable') from exc


def _require_enabled():
    if not chain.enabled():
        raise PrepareError('disabled')


def _require_configured():
    """For exits and protective actions (withdraw, cancel, cancelClaim,
    removing a beneficiary, inherited withdrawals): the feature flag being
    switched off must never trap an owner's assets, so these need only a
    configured factory."""
    if not chain.factory_address():
        raise PrepareError('disabled')


def _require_no_identity_hold(user):
    from security.identity_reuse import outgoing_identity_restriction
    restriction = outgoing_identity_restriction(user)
    if restriction:
        raise PrepareError('identity_hold', restriction)


def claim_pending_on_own_account(user) -> SmartAccount | None:
    """The signer's own account when a claim is pending on it (mirror OR a
    fresh chain read: either one is enough to append cancelClaim, which is a
    no-op success when nothing is pending) AND the chain still names the
    owner key as owner() of a non-inherited account. After a ClaimExecuted
    the mirror has not applied, cancelClaim reverts (NotOwner): it is not
    appended, and ops are alerted while the reconciler is kicked.

    Mirror says pending and the chain is unreadable: appended (today's
    protective no-op). Mirror says nothing: the chain read is required."""
    from . import relay_policy
    own = context.own_account(user)
    if own is None or own.status == 'none':
        return None
    signer = (own.owner_account.bsc_address or '').lower()
    if SmartAccountClaim.objects.filter(beneficiary_row__smart_account=own, state='pending').exists():
        try:
            state = chain.account_control(own.contract_address)
        except Exception:  # noqa: BLE001 — unknown: the protective no-op rides along
            logger.warning('account control unreadable for %s; appending cancelClaim',
                           own.contract_address, exc_info=True)
            return own
    else:
        if not int(_chain(chain.account_view, own.contract_address, 'claimStartedAt')):
            return None
        state = _chain(chain.account_control, own.contract_address)
    if relay_policy.signer_controls(state, signer) is False:
        relay_policy.ownership_mismatch(own.contract_address, signer)
        return None
    return own


def with_cancel_claim(user, calls: list) -> list:
    """While a claim is pending on the signer's account, every batch that
    owner signs carries account.cancelClaim() (spec 6.4, 7.4). It is part of
    the prepared call list the user signs, never added afterwards."""
    own = claim_pending_on_own_account(user)
    if own is None:
        return calls
    cancel = abi.call(own.contract_address, abi.encode_call('cancelClaim'))
    if cancel in calls:
        return calls
    return calls + [cancel]


def _register(viewer, kind: str, calls: list, *, target: str, smart_account=None, summary=None,
              payload=None, append_cancel_claim: bool = True) -> PreparedBatch:
    calls = [abi.call(c['to'], c['data']) for c in calls]
    if append_cancel_claim:
        calls = with_cancel_claim(viewer.user, calls)
    if not calls or len(calls) > MAX_CALLS:
        raise PrepareError('too_many_assets')
    request_id = 'sa-' + uuid.uuid4().hex
    not_after = int(timezone.now().timestamp()) + PREPARED_TTL_SECONDS
    SmartAccountPreparedAction.objects.create(
        request_id=request_id, user=viewer.user, signer_address=viewer.signer_address,
        target_address=target.lower(), smart_account=smart_account, kind=kind, calls=calls,
        calls_hash=calls_hash(calls), payload=payload or {}, not_after=not_after,
        expires_at=timezone.now() + timedelta(seconds=PREPARED_TTL_SECONDS))
    return PreparedBatch(request_id=request_id, calls=calls, kind=kind, summary=summary or [], not_after=not_after)


def _own_active(viewer, *, allow_payment_due: bool = True) -> SmartAccount:
    own = context.own_account(viewer.user)
    if own is None or own.status == 'none':
        raise PrepareError('no_account')
    if own.status not in ('active', 'cancel_pending'):
        raise PrepareError('account_not_active')
    if not allow_payment_due and own.billing_status != 'current':
        raise PrepareError('payment_due')
    return own


def _own_any(viewer) -> SmartAccount:
    own = context.own_account(viewer.user)
    if own is None:
        raise PrepareError('no_account')
    return own


def _parse_usd(value) -> Decimal:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PrepareError('bad_amount') from exc
    if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
        raise PrepareError('bad_amount')
    if amount < MIN_RULE_USD or amount > MAX_RULE_USD:
        raise PrepareError('bad_amount')
    return amount


def _resolve_units(asset_key: str, units: str, holder: str):
    """(resolved asset tuple, amount) for an asset key and a base-unit string
    or 'max', checked against `holder`'s fresh balance."""
    resolved = assets_mod.resolve_asset_key(asset_key)
    if resolved is None or not resolved[2]:
        raise PrepareError('bad_asset')
    kind, symbol, token, decimals = resolved
    balance = _chain(chain.balance_of, token, holder)
    text = str(units or '').strip().lower()
    if text == 'max':
        amount = balance
    else:
        if not text.isdigit():
            raise PrepareError('bad_amount')
        amount = int(text)
    if amount <= 0:
        raise PrepareError('bad_amount')
    if amount > balance:
        raise PrepareError('insufficient_balance')
    return resolved, amount


def _token_usd(kind: str, symbol: str, token: str, amount: int, decimals: int) -> Decimal | None:
    if token == chain.cusd_address():
        return Decimal(amount) / Decimal(WAD)
    if token == chain.cusd_plus_address():
        return Decimal(amount) * Decimal(_chain(chain.p_plus_wad)) / Decimal(10 ** 36)
    return None


def _deposit_calls(viewer, deposits, target: str):
    """transfer(target, amount) per requested asset, recipient pinned to the
    signer's own account. Returns (calls, summary lines, dollars deposited)."""
    calls, lines, dollars = [], [], Decimal(0)
    seen = set()
    for item in deposits or []:
        key = (getattr(item, 'asset_key', None) or (item.get('asset_key') if isinstance(item, dict) else '') or '')
        units = (getattr(item, 'units', None) or (item.get('units') if isinstance(item, dict) else '') or '')
        if key in seen:
            raise PrepareError('bad_asset')
        seen.add(key)
        if key == 'usdt':
            raise PrepareError('bad_asset')
        (kind, symbol, token, decimals), amount = _resolve_units(key, units, viewer.signer_address)
        calls.append(abi.transfer_call(token, target, amount))
        value = _token_usd(kind, symbol, token, amount, decimals)
        if value is not None:
            dollars += value
            lines.append(f'Mover a tu Cuenta inteligente: {usd_text(value)}')
        else:
            whole = Decimal(amount) / Decimal(10 ** decimals)
            lines.append(f'Mover a tu Cuenta inteligente: {whole.normalize():f} {symbol}')
    return calls, lines, dollars


# ── subscribe / deposit / move / withdraw ───────────────────────────────

def prepare_subscribe(viewer, plan: str, deposits, disclosures_accepted: bool) -> PreparedBatch:
    block = offer.subscribe_block(viewer.user, personal_context=True, meta=viewer.meta)
    if block:
        raise PrepareError(block, offer.BLOCKED[block])
    if plan not in abi.PLAN_IDS:
        raise PrepareError('bad_plan')
    if not disclosures_accepted:
        raise PrepareError('disclosures_required')
    signer = viewer.signer_address
    own = context.own_account(viewer.user)
    if own is not None and own.status in ('active', 'cancel_pending'):
        raise PrepareError('already_subscribed')
    calls = []
    if own is not None:
        target = own.contract_address
    else:
        existing = _chain(chain.account_of, signer)
        if int(existing, 16):
            # Created on chain, not reconciled yet, and still this signer's
            # by chain truth (owner(), inherited()), whatever the mirror says.
            block = offer.mapped_clone_block(viewer.user, existing, signer)
            if block:
                raise PrepareError(block, offer.BLOCKED[block])
            target = existing
        else:
            target = _chain(chain.predict_address, signer)
            calls.append(abi.call(chain.factory_address(), abi.encode_call('createAccount')))
    fee_wei = _chain(offer.signing_fee_wei, plan)
    if fee_wei <= 0:
        raise PrepareError('chain_unavailable')
    deposit_calls, lines, deposited = _deposit_calls(viewer, deposits, target)
    already = Decimal(0)
    if own is not None:
        already = Decimal(_chain(chain.account_view, target, 'dollarsUsd')) / Decimal(WAD)
    fee = Decimal(fee_wei) / Decimal(WAD)
    if deposited + already < fee:
        raise PrepareError('first_fee_short')
    calls += deposit_calls
    calls.append(abi.call(target, abi.encode_call('subscribe', abi.PLAN_IDS[plan], fee_wei)))
    label = 'Plan anual' if plan == 'annual' else 'Plan mensual'
    summary = [f'{label} · {usd_text(fee)}'] + lines
    return _register(
        viewer, 'smart_subscribe', calls, target=target, smart_account=own, summary=summary,
        payload={'plan': plan, 'fee_usd_wei': str(fee_wei),
                 'disclosures_accepted_at': timezone.now().isoformat()})


def prepare_deposit(viewer, deposits) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer)
    if not deposits:
        raise PrepareError('nothing_to_move')
    calls, lines, _dollars = _deposit_calls(viewer, deposits, own.contract_address)
    return _register(viewer, 'smart_deposit', calls, target=own.contract_address, smart_account=own, summary=lines)


def _movable(asset) -> tuple[bool, str | None]:
    if asset.key == 'usdt':
        return False, 'Se convierte primero a tu dólar Confío.'
    if asset.kind == 'other':
        return False, 'Confío no maneja este activo.'
    return True, None


def move_preview(viewer, direction: str) -> dict:
    if direction not in ('in', 'out'):
        raise PrepareError('bad_direction')
    _require_enabled() if direction == 'in' else _require_configured()
    own = _own_active(viewer) if direction == 'in' else _own_any(viewer)
    holder = viewer.signer_address if direction == 'in' else own.contract_address
    try:
        held = assets_mod.assets_of(holder)
    except assets_mod.AssetsUnknown as exc:
        raise PrepareError('chain_unavailable') from exc
    except Exception as exc:  # noqa: BLE001
        raise PrepareError('chain_unavailable') from exc
    rows, included = [], []
    for asset in held:
        ok, reason = (True, None) if direction == 'out' else _movable(asset)
        rows.append({'asset': asset, 'included': ok, 'reason': reason})
        if ok:
            included.append(asset)
    per_batch = _move_batch_size(viewer, direction)
    batches = (len(included) + per_batch - 1) // per_batch if included else 0
    # Never moved in either direction (spec 3.4); shown so nobody assumes otherwise.
    notes = [
        {'key': 'presale_locked', 'symbol': 'CONFIO', 'name': 'CONFIO de preventa (bloqueado)',
         'reason': 'No se mueve: sigue bloqueado en la preventa.'},
        {'key': 'perps', 'symbol': 'Futuros', 'name': 'Posiciones de Futuros',
         'reason': 'No se mueve: Futuros no forma parte de la Cuenta inteligente.'},
    ] if direction == 'in' else []
    return {'direction': direction, 'rows': rows, 'included': included, 'batches': batches,
            'per_batch': per_batch, 'notes': notes, 'own': own}


def _move_batch_size(viewer, direction: str) -> int:
    if direction == 'out':
        return MAX_WITHDRAW_ALL_TOKENS
    return MAX_CALLS - (1 if claim_pending_on_own_account(viewer.user) else 0)


def prepare_move_everything(viewer, direction: str, batch_index: int = 0) -> PreparedBatch:
    preview = move_preview(viewer, direction)
    included, per_batch, own = preview['included'], preview['per_batch'], preview['own']
    if not included:
        raise PrepareError('nothing_to_move')
    try:
        batch_index = int(batch_index or 0)
    except (TypeError, ValueError) as exc:
        raise PrepareError('bad_batch_index') from exc
    chunk = included[batch_index * per_batch:(batch_index + 1) * per_batch] if batch_index >= 0 else []
    if not chunk:
        raise PrepareError('bad_batch_index')
    if direction == 'in':
        calls = [abi.transfer_call(a.address, own.contract_address, a.units) for a in chunk]
        kind = 'smart_deposit'
        verb = 'Mover a tu Cuenta inteligente'
    else:
        calls = [abi.call(own.contract_address, abi.encode_call('withdrawAll', [a.address for a in chunk]))]
        kind = 'smart_withdraw'
        verb = 'Mover a tu cuenta personal'
    summary = [f'{verb}: {a.symbol}' + (f' · {usd_text(a.value_usd)}' if a.value_usd is not None else '')
               for a in chunk]
    return _register(viewer, kind, calls, target=own.contract_address, smart_account=own, summary=summary,
                     payload={'direction': direction, 'batch_index': batch_index})


def prepare_withdraw(viewer, asset_key: str, units: str) -> PreparedBatch:
    _require_configured()
    own = _own_any(viewer)
    (kind, symbol, token, decimals), amount = _resolve_units(asset_key, units, own.contract_address)
    if str(units or '').strip().lower() == 'max':
        data = abi.encode_call('withdrawAll', [token])
    else:
        data = abi.encode_call('withdraw', token, amount)
    value = _token_usd(kind, symbol, token, amount, decimals)
    line = (f'Mover a tu cuenta personal: {usd_text(value)}' if value is not None
            else f'Mover a tu cuenta personal: {(Decimal(amount) / Decimal(10 ** decimals)).normalize():f} {symbol}')
    return _register(viewer, 'smart_withdraw', [abi.call(own.contract_address, data)],
                     target=own.contract_address, smart_account=own, summary=[line])


# ── plan ────────────────────────────────────────────────────────────────

def prepare_plan_change(viewer, plan: str) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer, allow_payment_due=False)
    if plan not in abi.PLAN_IDS:
        raise PrepareError('bad_plan')
    price = offer.price_usd(plan)
    label = 'anual' if plan == 'annual' else 'mensual'
    return _register(
        viewer, 'smart_cancel', [abi.call(own.contract_address, abi.encode_call('changePlan', abi.PLAN_IDS[plan]))],
        target=own.contract_address, smart_account=own,
        summary=[f'Cambiar al plan {label} desde tu próxima renovación · US${price}'], payload={'plan': plan})


def prepare_cancel(viewer) -> PreparedBatch:
    _require_configured()
    own = _own_active(viewer)
    when = timezone.localtime(own.paid_until).strftime('%d/%m/%Y') if own.paid_until else ''
    summary = ['Cancelar tu Cuenta inteligente',
               (f'Tus activos vuelven a tu cuenta personal el {when}.' if when and own.billing_status == 'current'
                else 'Tus activos vuelven a tu cuenta personal.'),
               'La cobertura de tu beneficiario termina.']
    return _register(viewer, 'smart_cancel',
                     [abi.call(own.contract_address, abi.encode_call('cancelSubscription'))],
                     target=own.contract_address, smart_account=own, summary=summary)


def prepare_undo_cancel(viewer) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer)
    if own.status != 'cancel_pending':
        raise PrepareError('account_not_active', 'Tu Cuenta inteligente no tiene una cancelación pendiente.')
    return _register(viewer, 'smart_cancel', [abi.call(own.contract_address, abi.encode_call('undoCancel'))],
                     target=own.contract_address, smart_account=own, summary=['Mantener tu Cuenta inteligente'])


# ── rules ───────────────────────────────────────────────────────────────

FREQUENCY_LABELS = {'daily': 'cada día', 'weekly': 'cada semana', 'biweekly': 'cada dos semanas',
                    'monthly': 'cada mes'}


def account_dollar_token(own: SmartAccount, user, meta=None) -> str:
    """The dollar the account holds (decision 17: one of the two). The one
    with a balance; with neither or both, the owner's dollar by eligibility."""
    plus, cusd = chain.cusd_plus_address(), chain.cusd_address()
    plus_balance = _chain(chain.balance_of, plus, own.contract_address) if plus else 0
    cusd_balance = _chain(chain.balance_of, cusd, own.contract_address) if cusd else 0
    if plus_balance and not cusd_balance:
        return plus
    if cusd_balance and not plus_balance:
        return cusd
    token = plus if offer.viewer_dollar(user, meta) == 'cusd_plus' else cusd
    if not token:
        raise PrepareError('chain_unavailable')
    return token


def resolve_handle(handle: str):
    """A Confío user by username (with or without @) or phone number."""
    from django.contrib.auth import get_user_model
    from users.phone_utils import find_user_by_phone
    handle = (handle or '').strip()
    if not handle:
        return None
    User = get_user_model()
    user = User.objects.filter(username__iexact=handle.lstrip('@')).first()
    # Otherwise a FULL phone number (E.164): key-only, full-number matching,
    # ambiguous numbers refused (users.phone_utils.find_user_by_phone).
    if user is None and handle.startswith('+'):
        try:
            user = find_user_by_phone(handle)
        except Exception:  # noqa: BLE001 — not found, not an error
            user = None
    return user if (user is not None and user.is_active) else None


def _existing_rule(own: SmartAccount, rule_id, kind: str) -> SmartAccountRule | None:
    if rule_id in (None, ''):
        return None
    try:
        rule = SmartAccountRule.objects.filter(smart_account=own, internal_id=uuid.UUID(str(rule_id))).first()
    except (ValueError, TypeError):
        rule = None
    if rule is None or rule.state != 'onchain' or rule.onchain_id is None:
        raise PrepareError('rule_not_found')
    if rule.kind != kind:
        raise PrepareError('rule_kind_mismatch')
    return rule


def _first_run_at(own: SmartAccount, existing: SmartAccountRule | None) -> int:
    """firstRunAt for the rule tuple. 0 for a new rule (runs from now). For
    an edit, the rule's CURRENT next run, so editing never moves a run
    earlier: _storeRule sets nextRunAt = max(firstRunAt, now), and 0 would
    reset it to now and run the edited rule again at once. Read fresh from
    the chain; the mirror's slot is used instead only when it is the same or
    later (the calendar slot can sit after the contract's minimum gap)."""
    if existing is None:
        return 0
    onchain = _chain(chain.account_rule, own.contract_address, int(existing.onchain_id))
    if not onchain['active']:
        raise PrepareError('rule_not_found')
    first = int(onchain['next_run_at'])
    for mirror in (existing.scheduled_for, existing.next_run_at):
        if mirror is not None:
            first = max(first, int(mirror.timestamp()))
    return first


def _rule_batch(viewer, own, existing, draft_fields: dict, rule_tuple: tuple, summary: list) -> PreparedBatch:
    with transaction.atomic():
        draft = SmartAccountRule.objects.create(
            smart_account=own, state='draft', active=False, replaces=existing, **draft_fields)
        if existing is not None:
            data = abi.encode_call('updateRule', int(existing.onchain_id), rule_tuple)
        else:
            data = abi.encode_call('createRule', rule_tuple)
        return _register(viewer, 'smart_rule', [abi.call(own.contract_address, data)],
                         target=own.contract_address, smart_account=own, summary=summary,
                         payload={'rule_pk': draft.pk, 'replaces_pk': existing.pk if existing else None})


def _check_frequency(frequency: str):
    if frequency not in abi.FREQUENCY_IDS:
        raise PrepareError('bad_frequency')


def prepare_send_rule(viewer, rule_id, payee_handle: str, amount_usd, frequency: str) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer)
    _require_no_identity_hold(viewer.user)
    _check_frequency(frequency)
    amount = _parse_usd(amount_usd)
    existing = _existing_rule(own, rule_id, 'send')
    first_run_at = _first_run_at(own, existing)
    payee = resolve_handle(payee_handle)
    if payee is None:
        raise PrepareError('payee_not_found')
    if payee.pk == viewer.user.pk:
        raise PrepareError('payee_is_self')
    payee_account = context.personal_account(payee)
    if payee_account is None or not payee_account.bsc_address:
        raise PrepareError('payee_no_wallet')
    payee_address = payee_account.bsc_address.lower()
    token_in = account_dollar_token(own, viewer.user, viewer.meta)
    rule_tuple = abi.rule_input('send', frequency, token_in, payee=payee_address,
                                amount_usd_wei=int(amount * WAD), first_run_at=first_run_at)
    summary = [f'Enviar {usd_text(amount)} a {display_name(payee)} {FREQUENCY_LABELS[frequency]}']
    # Money leaves to another person with nobody present: Face once, at
    # creation or edit, bound to payee, amount and frequency (the personal
    # send flow's step-up; payouts.create_send_authorization).
    from . import payouts
    authorization = payouts.create_send_authorization(
        viewer, account=own, payee_address=payee_address, amount=amount, frequency=frequency)
    return _rule_batch(viewer, own, existing, dict(
        kind='send', token_in=token_in, payee_address=payee_address, payee_user=payee,
        standing_authorization=authorization, amount=amount, frequency=frequency), rule_tuple, summary)


def payout_ref_for(destination) -> bytes:
    """Hash of the saved bank destination, as stored on-chain. Covers the
    destination's identity AND its payable details, so an edited destination
    no longer matches its rule."""
    from eth_utils import keccak
    body = json.dumps({'id': str(destination.internal_id), 'details': destination.details,
                       'country': destination.country, 'kind': destination.kind},
                      sort_keys=True, separators=(',', ':'))
    return keccak(text=body)


def destination_rail(destination) -> str:
    return str((destination.provider_data or {}).get('method_id') or '')


def owned_payout_destination(viewer, payout_method_id):
    from payment_accounts.models import PayoutDestination
    try:
        internal_id = uuid.UUID(str(payout_method_id))
    except (ValueError, TypeError) as exc:
        raise PrepareError('payout_method_not_found') from exc
    destination = PayoutDestination.objects.filter(
        internal_id=internal_id, confio_account=viewer.personal_account, provider='infinia').first()
    if destination is None or destination.status not in ('pending', 'active'):
        raise PrepareError('payout_method_not_found')
    return destination


def prepare_payout_rule(viewer, rule_id, payout_method_id, amount_usd, frequency: str) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer)
    rails = offer.payout_rails()
    if not rails:
        raise PrepareError('payout_not_available')
    _check_frequency(frequency)
    amount = _parse_usd(amount_usd)
    existing = _existing_rule(own, rule_id, 'payout')
    first_run_at = _first_run_at(own, existing)
    destination = owned_payout_destination(viewer, payout_method_id)
    rail = destination_rail(destination)
    if rail not in rails:
        raise PrepareError('payout_rail_not_available')
    from payment_accounts import local_money
    validation = (destination.provider_data or {}).get('validation')
    if local_money.verification_state(validation) != local_money.VERIFIED or not local_money.checked_recently(validation):
        raise PrepareError('payout_method_unverified')
    from . import payouts
    token_in = account_dollar_token(own, viewer.user, viewer.meta)
    ref = payout_ref_for(destination)
    # Face, once, at rule creation: the standing authorization (spec 7.5).
    authorization = payouts.create_standing_authorization(
        viewer, destination=destination, rail=rail, amount=amount, frequency=frequency)
    rule_tuple = abi.rule_input('payout', frequency, token_in, payout_ref=ref, amount_usd_wei=int(amount * WAD),
                                first_run_at=first_run_at)
    summary = [f'Pagar {usd_text(amount)} a {destination.label} {FREQUENCY_LABELS[frequency]}',
               'El monto en dólares es fijo; el monto en moneda local sigue la tasa del día.']
    return _rule_batch(viewer, own, existing, dict(
        kind='payout', token_in=token_in, payout_method=destination, payout_ref='0x' + ref.hex(),
        payout_rail=rail, standing_authorization=authorization, amount=amount, frequency=frequency),
        rule_tuple, summary)


def buyable_assets(viewer, search: str = '') -> list[dict]:
    """Assets a buy rule may target for this viewer."""
    from cusd_plus import crypto_catalog
    out = []
    search = (search or '').strip().lower()
    if offer.crypto_investing_enabled(viewer.user, viewer.meta):
        for token in crypto_catalog.tokens():
            if assets_mod.is_feed_token(token):
                out.append({'asset_key': f'crypto:{token.symbol}', 'kind': 'crypto',
                            'symbol': token.ticker, 'name': token.name})
    if _stock_buy_allowed(viewer):
        try:
            market = assets_mod._stock_market()
        except Exception:  # noqa: BLE001 — list without stocks rather than fail the screen
            logger.warning('smart account: stock list unavailable', exc_info=True)
            market = {}
        registry = assets_mod.stock_registry()
        for symbol, item in sorted(market.items(), key=lambda kv: str(kv[0])):
            if not symbol or symbol not in registry:
                continue
            under = item.get('underlyingMarket') or {}
            out.append({'asset_key': f'stock:{symbol}', 'kind': 'stock',
                        'symbol': under.get('ticker') or symbol.removesuffix('on'),
                        'name': under.get('name') or symbol})
    if search:
        out = [a for a in out if search in a['symbol'].lower() or search in a['name'].lower()]
    return out


def _stock_buy_allowed(viewer) -> bool:
    from cusd_plus.eligibility import check_stock_buy_eligibility
    if not getattr(settings, 'CUSD_PLUS_STOCK_TRADING_ENABLED', False):
        return False
    return bool(check_stock_buy_eligibility(viewer.user, viewer.meta))


def prepare_buy_rule(viewer, rule_id, asset_key: str, amount_usd, frequency: str) -> PreparedBatch:
    _require_enabled()
    own = _own_active(viewer)
    _check_frequency(frequency)
    amount = _parse_usd(amount_usd)
    existing = _existing_rule(own, rule_id, 'buy')
    first_run_at = _first_run_at(own, existing)
    resolved = assets_mod.resolve_asset_key(asset_key)
    if resolved is None or resolved[0] not in ('stock', 'crypto'):
        raise PrepareError('bad_asset')
    kind, symbol, token_out, _decimals = resolved
    token_in = account_dollar_token(own, viewer.user, viewer.meta)
    if kind == 'stock':
        if not _stock_buy_allowed(viewer):
            raise PrepareError('trade_not_available')
        from cusd_plus import complex_products
        if complex_products.factor_for_symbol(symbol) is not None and not complex_products.acknowledged(viewer.user):
            raise PrepareError('trade_not_available', complex_products.ACK_REQUIRED_MESSAGE)
        if token_in != chain.cusd_plus_address():
            raise PrepareError('stock_needs_dollar_plus')
        _require_stock_minimum(amount)
    else:
        from cusd_plus import crypto_catalog, crypto_risk
        token = crypto_catalog.by_symbol(symbol)
        if token is None or not assets_mod.is_feed_token(token):
            raise PrepareError('bad_asset')
        if not crypto_risk.trading_ready() or not crypto_risk.buy_enabled(viewer.user, viewer.meta):
            raise PrepareError('trade_not_available')
        if not crypto_risk.acknowledged(viewer.user):
            raise PrepareError('trade_not_available', 'Acepta primero los riesgos de bitcoin y oro en Invertir.')
    from security.geo import review_cap_exceeded
    # The store-review amount cap trade_gate applies to every trade entry.
    if review_cap_exceeded(viewer.user, amount):
        raise PrepareError('review_amount_cap')
    rule_tuple = abi.rule_input('buy', frequency, token_in, token_out=token_out,
                                amount_usd_wei=int(amount * WAD), first_run_at=first_run_at)
    summary = [f'Comprar {usd_text(amount)} de {symbol.removesuffix("on") if kind == "stock" else symbol} '
               f'{FREQUENCY_LABELS[frequency]}']
    return _rule_batch(viewer, own, existing, dict(
        kind='buy', token_in=token_in, token_out=token_out, asset_key=asset_key,
        amount=amount, frequency=frequency), rule_tuple, summary)


def _require_stock_minimum(amount: Decimal) -> None:
    """A stock rule whose order (quotes.stock_buy_notional) would be below
    Ondo's minimum could never run: refused here, with the smallest amount
    that works, computed from the live fee policy."""
    from . import quotes
    try:
        if quotes.stock_buy_notional(amount) >= quotes.MIN_STOCK_ORDER_USD:
            return
        minimum = quotes.min_stock_rule_amount()
    except quotes.QuoteUnavailable as exc:
        raise PrepareError('stock_quote_window' if exc.retry_later else 'trade_not_available') from exc
    raise PrepareError(
        'stock_below_minimum',
        f'El monto mínimo para comprar acciones automáticamente es {usd_text(minimum)}.')


def prepare_cancel_rule(viewer, rule_id) -> PreparedBatch:
    _require_configured()
    own = _own_any(viewer)
    try:
        rule = SmartAccountRule.objects.filter(smart_account=own, internal_id=uuid.UUID(str(rule_id))).first()
    except (ValueError, TypeError):
        rule = None
    if rule is None or rule.state != 'onchain' or rule.onchain_id is None:
        raise PrepareError('rule_not_found')
    return _register(viewer, 'smart_rule_cancel',
                     [abi.call(own.contract_address, abi.encode_call('cancelRule', int(rule.onchain_id)))],
                     target=own.contract_address, smart_account=own, summary=['Cancelar esta regla'],
                     payload={'cancel_rule_pk': rule.pk})


# ── trade inside the account ────────────────────────────────────────────

def trade_parameters(venue_call: dict) -> dict:
    """Validate a router call with the SAME checks the relay applies to a
    personal-wallet trade and derive the account.trade arguments from it."""
    from cusd_plus import sponsor_7702
    from cusd_plus.crypto_policy import DOLLAR_PLUS, CryptoPolicyError, decode_crypto_call

    stock = sponsor_7702._decode_stock_call(venue_call)
    if stock is not None:
        plus = chain.cusd_plus_address()
        if stock['kind'] == 'stock_buy':
            return {'kind': 'stock_buy', 'venue': chain.stock_router_address(), 'token_in': plus,
                    'token_out': stock['asset'], 'max_in': int(stock['shares']),
                    'min_out': int(stock['quantity']) * 99 // 100, 'action': stock, 'call': venue_call}
        min_shares = int(sponsor_7702.abi_decode(
            [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256'],
            bytes.fromhex(venue_call['data'][10:]))[3])
        return {'kind': 'stock_sell', 'venue': chain.stock_router_address(), 'token_in': stock['asset'],
                'token_out': plus, 'max_in': int(stock['quantity']), 'min_out': min_shares, 'action': stock,
                'call': venue_call}
    try:
        crypto = decode_crypto_call(venue_call)
    except CryptoPolicyError as exc:
        raise sponsor_7702.PolicyError(str(exc)) from exc
    if crypto is None:
        raise sponsor_7702.PolicyError('destination_not_allowed')
    if not assets_mod.is_feed_token(crypto['token']):
        # The account only trades tokens it could later sell for a fee.
        raise sponsor_7702.PolicyError('token_not_listed')
    dollar_token = chain.cusd_plus_address() if crypto['dollar'] == DOLLAR_PLUS else chain.cusd_address()
    if not dollar_token:
        raise sponsor_7702.PolicyError('cusd_not_configured')
    if crypto['kind'] == 'crypto_buy':
        return {'kind': 'crypto_buy', 'venue': chain.swap_router_address(), 'token_in': dollar_token,
                'token_out': crypto['asset'], 'max_in': int(crypto['amount_in']),
                'min_out': int(crypto['min_out']), 'action': crypto, 'call': venue_call}
    return {'kind': 'crypto_sell', 'venue': chain.swap_router_address(), 'token_in': crypto['asset'],
            'token_out': dollar_token, 'max_in': int(crypto['amount_in']),
            'min_out': int(crypto['min_out']), 'action': crypto, 'call': venue_call}


def trade_gate(user, meta, params: dict) -> str | None:
    """The entry gates the sponsor applies to a personal-wallet trade
    (cusd_plus/schema.SponsorBscBatch, stock_buy / crypto_buy rail), run at
    prepare AND again at submit (relay_policy.trade_refusal): country and
    issuer policy, the complex-product acknowledgement for the quoted fund,
    the crypto buy gates and the store-review amount cap. Returns the same
    error code that rail returns, or None."""
    from security.geo import review_cap_exceeded_wei, store_review_exempt
    kind = params['kind']
    meta = meta or {}
    if kind in ('stock_buy', 'stock_sell'):
        from cusd_plus.eligibility import ONDO_POLICY, check_stock_buy_eligibility
        if not ONDO_POLICY.evaluate(user, meta).allowed:
            return 'trade_not_available'
        if kind == 'stock_buy':
            if not check_stock_buy_eligibility(user, meta):
                return 'trade_not_available'
            from cusd_plus import complex_products
            # Matched by the GM token inside the signed router call, never by
            # a client-supplied symbol (a quote is not bound to its requester).
            if complex_products.buys_complex_product([params['call']]) and not complex_products.acknowledged(user):
                return 'complex_product_ack_required'
            if review_cap_exceeded_wei(user, int(params['action']['history_amount_wei'])):
                return 'review_amount_cap'
        return None
    from cusd_plus import crypto_risk
    dollar = params['action']['dollar']
    refusal = crypto_risk.sponsor_gate(kind, user, meta, dollar=dollar)
    if refusal:
        return refusal
    if kind == 'crypto_buy' and store_review_exempt(user):
        from cusd_plus.crypto_policy import expected_exit_usdt
        gross_wei, _net = expected_exit_usdt(dollar, int(params['action']['amount_in']))
        if review_cap_exceeded_wei(user, gross_wei):
            return 'review_amount_cap'
    return None


def prepare_trade(viewer, venue: str, data: str) -> PreparedBatch:
    """Wrap a router call the app built from the existing quote flow in
    account.trade(...)."""
    from cusd_plus import sponsor_7702
    _require_enabled()
    own = _own_active(viewer, allow_payment_due=False)
    router = {'stock': chain.stock_router_address(), 'crypto': chain.swap_router_address()}.get(venue)
    data = (data or '').lower()
    if not router or not data.startswith('0x'):
        raise PrepareError('bad_trade')
    if venue == 'stock' and data[2:10] == sponsor_7702.SEL_STOCK_BUY:
        # The app's personal-wallet quote adds an exit buffer to the shares,
        # which comes back as loose USDT in the account (and a second fee
        # when converted): re-sized to the contract's arithmetic instead.
        from . import quotes
        try:
            data = quotes.resize_stock_buy_call({'to': router, 'value': '0', 'data': data})['data'].lower()
        except quotes.QuoteUnavailable as exc:
            raise PrepareError('stock_quote_window' if exc.retry_later else 'bad_trade') from exc
        except Exception as exc:  # noqa: BLE001 — undecodable: refused, never sent as is
            raise PrepareError('bad_trade') from exc
    try:
        params = trade_parameters({'to': router, 'value': '0', 'data': data})
    except sponsor_7702.PolicyError as exc:
        raise PrepareError('bad_trade', f'No pudimos validar esa operación ({exc.code}).') from exc
    refusal = trade_gate(viewer.user, viewer.meta, params)
    if refusal:
        raise PrepareError(refusal if refusal in MESSAGES else 'trade_not_available')
    call_data = abi.encode_call('trade', router, bytes.fromhex(data[2:]), params['token_in'],
                                params['token_out'], params['max_in'], params['min_out'])
    verb = 'Comprar' if params['kind'].endswith('buy') else 'Vender'
    return _register(viewer, 'smart_trade', [abi.call(own.contract_address, call_data)],
                     target=own.contract_address, smart_account=own,
                     summary=[f'{verb} dentro de tu Cuenta inteligente'], payload={'trade_kind': params['kind']})


# ── beneficiary: owner side ─────────────────────────────────────────────

def residence_check(user) -> str:
    """'ok', 'us_resident' or 'unknown'. A US phone, a US majority residence
    over recent sessions, or a US identity document blocks the designation
    (decision 11: Ondo's no-US-person representation covers cUSD+ and stock
    tokens). A person whose country cannot be determined is not 'ok': fail
    closed, as ONDO_POLICY's phone check does (allow_missing_phone=False)."""
    from security.geo import country_of, residence_country_for
    country = (country_of(user) or '').strip().upper()
    if not country:
        return 'unknown'
    if country == 'US':
        return 'us_resident'
    if (residence_country_for(user) or '').upper() == 'USA':
        return 'us_resident'
    return 'ok'


def beneficiary_checks(owner_user, beneficiary) -> tuple[object, str]:
    """Every designation-time check on the named person (spec 6.1). Returns
    (personal account, residence result). Re-run unchanged at acceptance."""
    from security.identity_reuse import outgoing_identity_restriction
    from security.identity_status import is_identity_verified
    if beneficiary is None:
        raise PrepareError('beneficiary_not_found')
    if beneficiary.pk == owner_user.pk:
        raise PrepareError('beneficiary_is_self')
    account = context.personal_account(beneficiary)
    if account is None or not account.bsc_address:
        raise PrepareError('beneficiary_no_wallet')
    if not is_identity_verified(beneficiary):
        raise PrepareError('beneficiary_unverified')
    residence = residence_check(beneficiary)
    if residence == 'unknown':
        raise PrepareError('beneficiary_residence_unknown')
    if residence != 'ok':
        raise PrepareError('beneficiary_ineligible')
    if outgoing_identity_restriction(beneficiary):
        raise PrepareError('beneficiary_on_hold')
    from cusd_plus import fee_referral
    if fee_referral.same_person(owner_user, beneficiary):
        raise PrepareError('beneficiary_is_self')
    return account, residence


def prepare_designation(viewer, beneficiary_handle, window_days, disclosure_accepted: bool, *,
                        beneficiary=None) -> PreparedBatch:
    _require_enabled()
    if not offer.beneficiary_enabled(viewer.user.pk):
        raise PrepareError('beneficiary_disabled')
    own = _own_active(viewer)
    _require_no_identity_hold(viewer.user)
    if not disclosure_accepted:
        raise PrepareError('disclosure_required')
    try:
        window_days = int(window_days)
    except (TypeError, ValueError) as exc:
        raise PrepareError('bad_window') from exc
    if window_days not in offer.WINDOW_OPTIONS_DAYS:
        raise PrepareError('bad_window')
    window = window_days * 86400
    if beneficiary is None:
        beneficiary = resolve_handle(beneficiary_handle)
    account, residence = beneficiary_checks(viewer.user, beneficiary)
    if not _chain(chain.inheritance_enabled):
        raise PrepareError('beneficiary_disabled')
    if not _chain(chain.window_allowed, window):
        raise PrepareError('bad_window')
    address = account.bsc_address.lower()
    # The exact list the owner will sign (with cancelClaim while a claim is
    # pending), built BEFORE the approval so nothing that can fail after it
    # depends on the chain.
    calls = with_cancel_claim(
        viewer.user, [abi.call(own.contract_address, abi.encode_call('setBeneficiary', address, window))])
    if len(calls) > MAX_CALLS:
        raise PrepareError('too_many_assets')
    # Naming a beneficiary hands someone else a path to everything in the
    # account: the owner's Face, as for a send to another person, bound to
    # this exact designation (account, wallet, window) AND its own draft row,
    # so a removed or withdrawn designation named again never reuses the
    # consumed grant. The draft and the claim share one transaction: a
    # refused Face leaves no row. An exact retry (same account, person,
    # wallet and window, still a draft, recent: e.g. after the approval
    # below was not yet mined) reuses the draft and re-claims the same key.
    from . import payouts
    now = timezone.now()
    with transaction.atomic():
        row = (SmartAccountBeneficiary.objects
               .filter(smart_account=own, beneficiary_user=beneficiary, beneficiary_address=address,
                       challenge_window_seconds=window, state='draft',
                       created_at__gte=now - timedelta(seconds=PREPARED_TTL_SECONDS))
               .order_by('-pk').first())
        if row is None:
            row = SmartAccountBeneficiary.objects.create(
                smart_account=own, beneficiary_user=beneficiary, beneficiary_address=address,
                challenge_window_seconds=window, verified_at_designation=True, residence_check=residence,
                disclosure_accepted_at=now, state='draft')
        face_key, face_required = payouts.claim_face(
            viewer, 'smart_account_designation',
            payouts.face_identifier(
                hashlib.sha256(f'{own.contract_address.lower()}:{address}:{window}'.encode()).hexdigest(), row.pk),
            {'account': own.contract_address.lower(), 'beneficiary': address, 'window': window,
             'designation': str(row.designation_id)},
            'Confirma con Confío Face para nombrar a tu beneficiario.')
    # Every check above passed: the relayer records the factory approval for
    # exactly this designation, and only once it is on chain is the batch
    # returned (outside any transaction: the relay row must be durable
    # before its broadcast).
    from . import approvals
    approval = approvals.ensure_designation(own, address, window)
    SmartAccountBeneficiary.objects.filter(pk=row.pk).update(residence_check=residence, disclosure_accepted_at=now)
    with transaction.atomic():
        return _register(
            viewer, 'smart_beneficiary', calls,
            target=own.contract_address, smart_account=own,
            summary=[f'Nombrar a {display_name(beneficiary)} como beneficiario',
                     f'Plazo del reclamo: {window_days} días'],
            payload={'beneficiary_pk': row.pk, 'approval': approval, 'face_required': face_required,
                     'face_action_key': face_key}, append_cancel_claim=False)


def prepare_window_change(viewer, window_days) -> PreparedBatch:
    """Re-name the current accepted beneficiary with a new window. They must
    accept again; until then the current window stays (contract rule)."""
    _require_enabled()
    if not offer.beneficiary_enabled(viewer.user.pk):
        raise PrepareError('beneficiary_disabled')
    own = _own_active(viewer)
    current = (SmartAccountBeneficiary.objects.filter(smart_account=own, state='active')
               .select_related('beneficiary_user').order_by('-accepted_at').first())
    if current is None:
        raise PrepareError('no_beneficiary')
    user = current.beneficiary_user
    return prepare_designation(viewer, None, window_days, True, beneficiary=user)


def prepare_designation_withdrawal(viewer) -> PreparedBatch:
    _require_configured()
    own = _own_any(viewer)
    if not SmartAccountBeneficiary.objects.filter(smart_account=own, state='pending_acceptance').exists():
        raise PrepareError('no_pending_designation')
    return _register(viewer, 'smart_beneficiary_remove',
                     [abi.call(own.contract_address, abi.encode_call('withdrawDesignation'))],
                     target=own.contract_address, smart_account=own,
                     summary=['Retirar la designación pendiente'])


def prepare_beneficiary_removal(viewer) -> PreparedBatch:
    _require_configured()
    own = _own_any(viewer)
    if not SmartAccountBeneficiary.objects.filter(
            smart_account=own, state__in=('pending_acceptance', 'active', 'stale_address')).exists():
        raise PrepareError('no_beneficiary')
    return _register(viewer, 'smart_beneficiary_remove',
                     [abi.call(own.contract_address, abi.encode_call('removeBeneficiary'))],
                     target=own.contract_address, smart_account=own, summary=['Quitar a tu beneficiario'])


def prepare_claim_cancel(viewer) -> PreparedBatch:
    """Always allowed for an owner: cancelClaim is a no-op success when no
    claim is pending, and must never be refused while one is."""
    _require_configured()
    own = _own_any(viewer)
    if own.status == 'none':
        raise PrepareError('no_account')
    return _register(viewer, 'smart_claim',
                     [abi.call(own.contract_address, abi.encode_call('cancelClaim'))],
                     target=own.contract_address, smart_account=own, summary=['Cancelar el reclamo pendiente'],
                     append_cancel_claim=False)


# ── beneficiary: named person side ──────────────────────────────────────

def _designation_for(viewer, designation_id, states) -> SmartAccountBeneficiary:
    try:
        row = (SmartAccountBeneficiary.objects.select_related('smart_account', 'smart_account__owner_user')
               .filter(designation_id=uuid.UUID(str(designation_id)), beneficiary_user=viewer.user).first())
    except (ValueError, TypeError):
        row = None
    if row is None:
        raise PrepareError('designation_not_found')
    if row.state not in states:
        raise PrepareError('designation_not_pending')
    if row.beneficiary_address.lower() != viewer.signer_address:
        # The wallet named on-chain is no longer this person's wallet.
        raise PrepareError('designation_not_pending', 'Tu billetera cambió. Pide que te nombren de nuevo.')
    return row


def prepare_acceptance(viewer, designation_id) -> PreparedBatch:
    _require_enabled()
    row = _designation_for(viewer, designation_id, ('pending_acceptance',))
    if row.expires_at and row.expires_at <= timezone.now():
        raise PrepareError('designation_expired')
    owner = row.smart_account.owner_user
    # The identity and residence checks are re-run at acceptance (spec 6.1).
    beneficiary_checks(owner, viewer.user)
    _require_no_identity_hold(viewer.user)
    account = row.smart_account
    if account.status not in ('active', 'cancel_pending'):
        raise PrepareError('designation_not_pending', 'Esa Cuenta inteligente ya no está activa.')
    calls = with_cancel_claim(
        viewer.user, [abi.call(account.contract_address, abi.encode_call('acceptBeneficiary'))])
    if len(calls) > MAX_CALLS:
        raise PrepareError('too_many_assets')
    # Checks re-run and passed: the relayer approves exactly this acceptance
    # on the factory, and the batch is returned only once that is on chain.
    from . import approvals
    approval = approvals.ensure_acceptance(account, viewer.signer_address)
    SmartAccountBeneficiary.objects.filter(pk=row.pk).update(acceptance_checked_at=timezone.now())
    return _register(viewer, 'smart_beneficiary', calls,
                     target=account.contract_address, smart_account=account,
                     summary=[f'Aceptar ser beneficiario de {display_name(owner)}'],
                     payload={'beneficiary_pk': row.pk, 'approval': approval}, append_cancel_claim=False)


ACCEPTANCE_IN_FLIGHT = timedelta(seconds=3600)  # approvals.APPROVAL_TTL_SECONDS


def _refuse_decline_after_acceptance(viewer, row) -> None:
    """A decline must not race an acceptance the same person already set in
    motion: once an acceptance approval was issued (it lives an hour on the
    factory) or the chain already names this signer, the server state would
    contradict the chain. Fails closed on an unreadable chain."""
    from .models import SmartAccountRelayTx
    since = timezone.now() - ACCEPTANCE_IN_FLIGHT
    address = row.beneficiary_address.lower()
    if (row.acceptance_checked_at and row.acceptance_checked_at >= since) or SmartAccountRelayTx.objects.filter(
            smart_account=row.smart_account, kind='smart_acceptance_approval',
            source_id__startswith=f'acceptance:{address}:', created_at__gte=since,
            status__in=SmartAccountRelayTx.LIVE_STATUSES).exists():
        raise PrepareError('designation_acceptance_in_progress')
    beneficiary = str(_chain(chain.account_view, row.smart_account.contract_address, 'beneficiary') or '').lower()
    if beneficiary == viewer.signer_address.lower():
        raise PrepareError('designation_already_accepted')


def decline_designation(viewer, designation_id) -> SmartAccountBeneficiary:
    """Server-only: records declined_at and tells the owner. No transaction;
    the on-chain pending entry lapses by itself after 30 days."""
    row = _designation_for(viewer, designation_id, ('pending_acceptance',))
    _refuse_decline_after_acceptance(viewer, row)
    updated = SmartAccountBeneficiary.objects.filter(pk=row.pk, state='pending_acceptance').update(
        state='declined', declined_at=timezone.now(), updated_at=timezone.now())
    if not updated:
        raise PrepareError('designation_not_pending')
    row.refresh_from_db()
    from . import notifications
    notifications.safe(notifications.beneficiary_declined, row)
    return row


def prepare_claim(viewer, designation_id) -> PreparedBatch:
    _require_configured()
    row = _designation_for(viewer, designation_id, ('active',))
    account = row.smart_account
    if account.status not in ('active', 'cancel_pending'):
        raise PrepareError('claim_not_allowed')
    if row.claims.filter(state='pending').exists():
        raise PrepareError('claim_not_allowed', 'Ya tienes un reclamo en curso.')
    if row.cooldown_until and row.cooldown_until > timezone.now():
        raise PrepareError('claim_not_allowed', 'Todavía no puedes volver a iniciar un reclamo.')
    days = row.challenge_window_seconds // 86400
    return _register(viewer, 'smart_claim',
                     [abi.call(account.contract_address, abi.encode_call('initiateClaim'))],
                     target=account.contract_address, smart_account=account,
                     summary=['Iniciar el reclamo de la cuenta', f'Podrás completarlo en {days} días.'],
                     payload={'beneficiary_pk': row.pk})


def prepare_claim_execute(viewer, designation_id) -> PreparedBatch:
    _require_configured()
    row = _designation_for(viewer, designation_id, ('active',))
    claim = row.claims.filter(state='pending').order_by('-initiated_at').first()
    if claim is None:
        raise PrepareError('no_claim')
    if claim.executable_at > timezone.now():
        raise PrepareError('claim_not_executable')
    account = row.smart_account
    return _register(viewer, 'smart_claim',
                     [abi.call(account.contract_address, abi.encode_call('executeClaim'))],
                     target=account.contract_address, smart_account=account,
                     summary=['Completar el reclamo y recibir la cuenta'],
                     payload={'beneficiary_pk': row.pk, 'claim_pk': claim.pk})


# ── inherited account ───────────────────────────────────────────────────

def inherited_account_for(viewer, inherited_account_id) -> SmartAccount:
    try:
        account = SmartAccount.objects.filter(
            internal_id=uuid.UUID(str(inherited_account_id)), owner_user=viewer.user, status='inherited',
            account__user=viewer.user, account__deleted_at__isnull=True).first()
    except (ValueError, TypeError):
        account = None
    if account is None:
        raise PrepareError('inherited_not_found')
    return account


def prepare_inherited_withdraw(viewer, inherited_account_id, asset_keys, destination: str) -> PreparedBatch:
    _require_configured()
    account = inherited_account_for(viewer, inherited_account_id)
    if destination == 'wallet':
        to = viewer.signer_address
        where = 'tu cuenta personal'
    elif destination == 'smart_account':
        own = context.own_account(viewer.user)
        if own is None or own.status not in ('active', 'cancel_pending'):
            raise PrepareError('no_own_account')
        to = own.contract_address
        where = 'tu Cuenta inteligente'
    else:
        raise PrepareError('bad_destination')
    try:
        held = assets_mod.assets_of(account.contract_address)
    except Exception as exc:  # noqa: BLE001
        raise PrepareError('chain_unavailable') from exc
    if asset_keys:
        wanted = set(asset_keys)
        chosen = [a for a in held if a.key in wanted]
        if len(chosen) != len(wanted):
            raise PrepareError('bad_asset')
    else:
        chosen = held
    if not chosen:
        raise PrepareError('nothing_to_move')
    if len(chosen) > MAX_WITHDRAW_ALL_TOKENS:
        raise PrepareError('too_many_assets')
    data = abi.encode_call('withdrawAllTo', [a.address for a in chosen], to)
    return _register(viewer, 'smart_inherited_withdraw', [abi.call(account.contract_address, data)],
                     target=account.contract_address, smart_account=account,
                     summary=[f'Mover a {where}: {a.symbol}' for a in chosen],
                     payload={'destination': destination})
