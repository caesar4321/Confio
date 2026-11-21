"""GraphQL for Cuenta inteligente. Implements the frozen contract
(smart_account_api.graphql, 2026-11-20) exactly; additions are marked
"ADDITION". Account context comes from the JWT only; no resolver takes an
account id or address as authority.
"""
from __future__ import annotations

import base64
import logging
from decimal import Decimal

import graphene
from django.conf import settings
from django.utils import timezone
from graphene import relay

from . import abi, assets as assets_mod, chain, context, offer, services
from .models import (
    SmartAccount as SmartAccountModel, SmartAccountBeneficiary as BeneficiaryModel,
    SmartAccountCharge as ChargeModel, SmartAccountClaim as ClaimModel, SmartAccountRule as RuleModel,
)

logger = logging.getLogger(__name__)
CHAIN_NAME = 'BNB Smart Chain'


# ── types ───────────────────────────────────────────────────────────────

class SmartAccountCallType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountCall'
    to = graphene.String(required=True)
    value_wei = graphene.String(required=True)
    data = graphene.String(required=True)


class SmartAccountPreparedBatchType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountPreparedBatch'
    success = graphene.Boolean(required=True)
    error_code = graphene.String()
    error_message = graphene.String()
    request_id = graphene.String()
    calls = graphene.List(graphene.NonNull(SmartAccountCallType))
    not_after = graphene.Int()
    summary = graphene.List(graphene.NonNull(graphene.String))
    # ADDITION: the kind the server stores this batch as. The signed intentId
    # may bind either this kind or the app's existing generic derivation.
    intent_kind = graphene.String()


class SmartAccountPlanType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountPlan'
    key = graphene.String(required=True)
    price_usd = graphene.String(required=True)
    period_days = graphene.Int(required=True)
    next_price_usd = graphene.String()
    next_price_effective_at = graphene.DateTime()
    is_default = graphene.Boolean(required=True)


class SmartAccountBenefitType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountBenefit'
    key = graphene.String(required=True)
    title = graphene.String(required=True)
    body = graphene.String(required=True)


class SmartAccountOfferType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountOffer'
    available = graphene.Boolean(required=True)
    can_subscribe = graphene.Boolean(required=True)
    blocked_reason = graphene.String()
    plans = graphene.List(graphene.NonNull(SmartAccountPlanType), required=True)
    headline = graphene.String(required=True)
    benefits = graphene.List(graphene.NonNull(SmartAccountBenefitType), required=True)
    disclosures = graphene.List(graphene.NonNull(graphene.String), required=True)
    beneficiary_enabled = graphene.Boolean(required=True)
    investing_crypto_enabled = graphene.Boolean(required=True)
    payout_rails = graphene.List(graphene.NonNull(graphene.String), required=True)
    dollar = graphene.String(required=True)
    min_first_deposit_usd = graphene.String(required=True)
    # ADDITION: the residual-risk disclosure of the beneficiary setup screen
    # (8.3, item 7) as short sentences with {name} and {days} placeholders.
    beneficiary_risk_disclosure = graphene.List(graphene.NonNull(graphene.String), required=True)
    # ADDITION: stable machine code for blockedReason.
    blocked_code = graphene.String()


class SmartAccountAssetType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountAsset'
    key = graphene.String(required=True)
    kind = graphene.String(required=True)
    symbol = graphene.String(required=True)
    name = graphene.String(required=True)
    address = graphene.String(required=True)
    units = graphene.String(required=True)
    decimals = graphene.Int(required=True)
    value_usd = graphene.String()
    can_pay_fee = graphene.Boolean(required=True)


class SmartAccountRuleType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountRule'
    id = graphene.ID(required=True)
    onchain_id = graphene.String()
    kind = graphene.String(required=True)
    frequency = graphene.String(required=True)
    amount_usd = graphene.String(required=True)
    active = graphene.Boolean(required=True)
    next_run_at = graphene.DateTime()
    last_run_at = graphene.DateTime()
    last_run_status = graphene.String()
    last_run_message = graphene.String()
    payee_name = graphene.String()
    payee_handle = graphene.String()
    payout_method_id = graphene.String()
    payout_label = graphene.String()
    payout_rail = graphene.String()
    asset_key = graphene.String()
    asset_symbol = graphene.String()
    asset_name = graphene.String()


class SmartAccountChargeType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountCharge'
    id = graphene.ID(required=True)
    charged_at = graphene.DateTime(required=True)
    period_start = graphene.DateTime(required=True)
    period_end = graphene.DateTime(required=True)
    plan = graphene.String(required=True)
    fee_usd = graphene.String(required=True)
    paid_with = graphene.String(required=True)
    tx_hash = graphene.String()


class SmartAccountClaimType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountClaim'
    state = graphene.String(required=True)
    initiated_at = graphene.DateTime(required=True)
    executable_at = graphene.DateTime(required=True)
    cancelled_at = graphene.DateTime()
    executed_at = graphene.DateTime()


class SmartAccountBeneficiaryType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountBeneficiary'
    designation_id = graphene.String(required=True)
    state = graphene.String(required=True)
    name = graphene.String(required=True)
    handle = graphene.String()
    window_days = graphene.Int(required=True)
    designated_at = graphene.DateTime(required=True)
    accepted_at = graphene.DateTime()
    expires_at = graphene.DateTime()
    cooldown_until = graphene.DateTime()
    claim = graphene.Field(SmartAccountClaimType)


class SmartAccountBillingType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountBilling'
    status = graphene.String(required=True)
    plan = graphene.String(required=True)
    next_plan = graphene.String()
    fee_usd = graphene.String(required=True)
    paid_until = graphene.DateTime()
    cancel_requested = graphene.Boolean(required=True)
    returns_at = graphene.DateTime()
    shortfall_usd = graphene.String()
    notice_started_at = graphene.DateTime()
    sale_allowed_at = graphene.DateTime()
    sale_candidates = graphene.List(graphene.NonNull(graphene.String))


class SmartAccountType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccount'
    status = graphene.String(required=True)
    contract_address = graphene.String()
    total_usd = graphene.String()
    dollars_usd = graphene.String()
    billing = graphene.Field(SmartAccountBillingType)
    assets = graphene.List(graphene.NonNull(SmartAccountAssetType), required=True)
    rules = graphene.List(graphene.NonNull(SmartAccountRuleType), required=True)
    beneficiary = graphene.Field(SmartAccountBeneficiaryType)
    pending_beneficiary = graphene.Field(SmartAccountBeneficiaryType)
    window_options_days = graphene.List(graphene.NonNull(graphene.Int), required=True)
    default_window_days = graphene.Int(required=True)
    assistant_plus = graphene.Boolean(required=True)
    # ADDITION: may this viewer use the beneficiary screens now.
    beneficiary_enabled = graphene.Boolean(required=True)


class InheritedAccountType(graphene.ObjectType):
    class Meta:
        name = 'InheritedAccount'
    inherited_account_id = graphene.String(required=True)
    contract_address = graphene.String(required=True)
    from_name = graphene.String(required=True)
    inherited_at = graphene.DateTime(required=True)
    total_usd = graphene.String()
    assets = graphene.List(graphene.NonNull(SmartAccountAssetType), required=True)
    can_move_to_smart_account = graphene.Boolean(required=True)
    # ADDITION: the JWT account_index to switch to this account
    # (switchAccountToken(accountType: "smart", accountIndex: N)); 1 and up.
    account_index = graphene.Int(required=True)


class BeneficiaryDesignationType(graphene.ObjectType):
    class Meta:
        name = 'BeneficiaryDesignation'
    designation_id = graphene.String(required=True)
    state = graphene.String(required=True)
    owner_name = graphene.String(required=True)
    owner_handle = graphene.String()
    window_days = graphene.Int(required=True)
    designated_at = graphene.DateTime(required=True)
    accepted_at = graphene.DateTime()
    expires_at = graphene.DateTime()
    contract_address = graphene.String()
    chain_name = graphene.String()
    cooldown_until = graphene.DateTime()
    claim = graphene.Field(SmartAccountClaimType)
    can_claim = graphene.Boolean(required=True)
    can_execute = graphene.Boolean(required=True)


class SmartAccountClaimAlertType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountClaimAlert'
    beneficiary_name = graphene.String(required=True)
    initiated_at = graphene.DateTime(required=True)
    executable_at = graphene.DateTime(required=True)
    # The owner's own account: the app appends account.cancelClaim() to this
    # address at the end of every batch it builds from the personal wallet
    # while the alert is shown (spec 6.4, 7.4).
    contract_address = graphene.String()


class SmartAccountMoveAssetType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountMoveAsset'
    key = graphene.String(required=True)
    symbol = graphene.String(required=True)
    name = graphene.String(required=True)
    units = graphene.String(required=True)
    decimals = graphene.Int(required=True)
    value_usd = graphene.String()
    included = graphene.Boolean(required=True)
    reason = graphene.String()


class SmartAccountMovePreviewType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountMovePreview'
    direction = graphene.String(required=True)
    assets = graphene.List(graphene.NonNull(SmartAccountMoveAssetType), required=True)
    total_usd = graphene.String()
    batches = graphene.Int(required=True)


class SmartAccountPayoutMethodType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountPayoutMethod'
    payout_method_id = graphene.String(required=True)
    rail = graphene.String(required=True)
    label = graphene.String(required=True)
    holder_name = graphene.String(required=True)
    available = graphene.Boolean(required=True)


class SmartAccountBuyableAssetType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountBuyableAsset'
    asset_key = graphene.String(required=True)
    kind = graphene.String(required=True)
    symbol = graphene.String(required=True)
    name = graphene.String(required=True)


class SmartAccountChargeEdge(graphene.ObjectType):
    node = graphene.Field(SmartAccountChargeType, required=True)
    cursor = graphene.String(required=True)


class SmartAccountChargeConnection(graphene.ObjectType):
    edges = graphene.List(graphene.NonNull(SmartAccountChargeEdge), required=True)
    page_info = graphene.Field(relay.PageInfo, required=True)


class SmartAccountBuyableAssetEdge(graphene.ObjectType):
    node = graphene.Field(SmartAccountBuyableAssetType, required=True)
    cursor = graphene.String(required=True)


class SmartAccountBuyableAssetConnection(graphene.ObjectType):
    edges = graphene.List(graphene.NonNull(SmartAccountBuyableAssetEdge), required=True)
    page_info = graphene.Field(relay.PageInfo, required=True)


class SmartAccountDepositInput(graphene.InputObjectType):
    asset_key = graphene.String(required=True)
    units = graphene.String(required=True)


class SmartAccountSimpleResultType(graphene.ObjectType):
    class Meta:
        name = 'SmartAccountSimpleResult'
    success = graphene.Boolean(required=True)
    error_code = graphene.String()
    error_message = graphene.String()


# ── builders ────────────────────────────────────────────────────────────

def _asset_type(asset) -> SmartAccountAssetType:
    return SmartAccountAssetType(
        key=asset.key, kind=asset.kind, symbol=asset.symbol, name=asset.name, address=asset.address,
        units=str(asset.units), decimals=asset.decimals, value_usd=assets_mod.money(asset.value_usd),
        can_pay_fee=asset.can_pay_fee)


def _claim_type(claim) -> SmartAccountClaimType | None:
    if claim is None:
        return None
    return SmartAccountClaimType(
        state=claim.display_state(), initiated_at=claim.initiated_at, executable_at=claim.executable_at,
        cancelled_at=claim.cancelled_at, executed_at=claim.executed_at)


def _pending_claim(row):
    return row.claims.filter(state='pending').order_by('-initiated_at').first()


def _beneficiary_type(row) -> SmartAccountBeneficiaryType | None:
    if row is None:
        return None
    user = row.beneficiary_user
    return SmartAccountBeneficiaryType(
        designation_id=str(row.designation_id), state=row.state, name=services.display_name(user),
        handle=user.username or None, window_days=row.challenge_window_seconds // 86400,
        designated_at=row.designated_at or row.created_at, accepted_at=row.accepted_at,
        expires_at=row.expires_at if row.state == 'pending_acceptance' else None,
        cooldown_until=row.cooldown_until, claim=_claim_type(_pending_claim(row)))


def _rule_type(rule) -> SmartAccountRuleType:
    last = rule.runs.exclude(status__in=('pending', 'sent')).order_by('-scheduled_for').first()
    out = SmartAccountRuleType(
        id=str(rule.internal_id), onchain_id=str(rule.onchain_id) if rule.onchain_id is not None else None,
        kind=rule.kind, frequency=rule.frequency, amount_usd=format(rule.amount, 'f'), active=rule.active,
        next_run_at=rule.scheduled_for or rule.next_run_at,
        last_run_at=last.updated_at if last else None, last_run_status=last.status if last else None,
        last_run_message=(last.message or None) if last else None)
    if rule.kind == 'send' and rule.payee_user is not None:
        out.payee_name = services.display_name(rule.payee_user)
        out.payee_handle = rule.payee_user.username or None
    if rule.kind == 'payout':
        out.payout_rail = rule.payout_rail or None
        if rule.payout_method is not None:
            out.payout_method_id = str(rule.payout_method.internal_id)
            out.payout_label = ' · '.join(p for p in (rule.payout_method.label, rule.payout_method.holder_name) if p)
    if rule.kind == 'buy':
        out.asset_key = rule.asset_key or None
        resolved = assets_mod.resolve_asset_key(rule.asset_key) if rule.asset_key else None
        if resolved:
            symbol = resolved[1]
            out.asset_symbol = symbol.removesuffix('on') if resolved[0] == 'stock' else symbol
            out.asset_name = out.asset_symbol
    return out


def _offset_cursor(offset: int) -> str:
    return base64.b64encode(f'offset:{offset}'.encode()).decode()


def _cursor_offset(after) -> int:
    if not after:
        return 0
    try:
        text = base64.b64decode(after.encode()).decode()
        return max(0, int(text.split(':', 1)[1]) + 1)
    except Exception:  # noqa: BLE001 — a bad cursor is the first page
        return 0


def _page(items, first, after, edge_cls, connection_cls, node):
    start = _cursor_offset(after)
    size = max(1, min(int(first or 20), 100))
    window = list(items[start:start + size + 1])
    has_next = len(window) > size
    window = window[:size]
    edges = [edge_cls(node=node(item), cursor=_offset_cursor(start + i)) for i, item in enumerate(window)]
    return connection_cls(edges=edges, page_info=relay.PageInfo(
        has_next_page=has_next, has_previous_page=start > 0,
        start_cursor=edges[0].cursor if edges else None, end_cursor=edges[-1].cursor if edges else None))


def _viewer(info, *, require_wallet: bool = True):
    try:
        return context.resolve_viewer(info, require_wallet=require_wallet)
    except context.ContextError:
        return None


def _is_employee_context(info) -> bool:
    from users.jwt_context import get_jwt_business_context_with_validation, is_business_employee
    ctx = get_jwt_business_context_with_validation(info, required_permission=None, allow_smart=True)
    if not ctx or ctx.get('account_type') != 'business':
        return False
    return is_business_employee(info.context.user, ctx.get('business_id'))


def _has_balance(viewer) -> bool:
    """Display only (headline order): a failed read is 'no balance'."""
    try:
        signer = viewer.signer_address
        for token in (chain.cusd_plus_address(), chain.cusd_address()):
            if token and chain.balance_of(token, signer) > 0:
                return True
    except Exception:  # noqa: BLE001
        logger.info('smart account offer: balance read failed', exc_info=True)
    return False


# ── queries ─────────────────────────────────────────────────────────────

class Query(graphene.ObjectType):
    smart_account_offer = graphene.Field(SmartAccountOfferType)
    smart_account = graphene.Field(SmartAccountType)
    smart_account_charges = graphene.Field(
        SmartAccountChargeConnection, first=graphene.Int(default_value=20), after=graphene.String())
    smart_account_move_preview = graphene.Field(SmartAccountMovePreviewType, direction=graphene.String(required=True))
    smart_account_payout_methods = graphene.List(graphene.NonNull(SmartAccountPayoutMethodType))
    smart_account_buyable_assets = graphene.Field(
        SmartAccountBuyableAssetConnection, search=graphene.String(),
        first=graphene.Int(default_value=30), after=graphene.String())
    inherited_accounts = graphene.List(graphene.NonNull(InheritedAccountType))
    beneficiary_designations = graphene.List(graphene.NonNull(BeneficiaryDesignationType))
    smart_account_claim_alert = graphene.Field(SmartAccountClaimAlertType)

    def resolve_smart_account_offer(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        meta = dict(getattr(info.context, 'META', {}) or {})
        viewer = _viewer(info, require_wallet=False)
        personal = viewer is not None
        block = offer.subscribe_block(user, personal_context=personal, meta=meta)
        own = context.own_account(user) if personal else None
        has_account = own is not None and own.status != 'none'
        from users import paid_offers
        from users.models_product_waitlist import PRODUCT_SMART_ACCOUNT
        pitch = paid_offers.available(PRODUCT_SMART_ACCOUNT, is_employee=_is_employee_context(info),
                                      meta=meta, user_id=user.pk) if personal else False
        headline = 'beneficiary_first' if (viewer is not None and viewer.signer_address
                                           and _has_balance(viewer)) else 'automation_first'
        beneficiary_on = offer.beneficiary_enabled(user.pk)
        order = [k for k in offer.HEADLINE_ORDER[headline]]
        plans = offer.plans()
        cheapest = min(Decimal(p['price_usd']) for p in plans)
        return SmartAccountOfferType(
            available=bool(personal and (block is None or has_account or pitch)),
            can_subscribe=block is None and not (own is not None and own.status in ('active', 'cancel_pending')),
            blocked_reason=offer.BLOCKED.get(block) if block else None,
            blocked_code=block,
            plans=[SmartAccountPlanType(**p) for p in plans],
            headline=headline,
            benefits=[SmartAccountBenefitType(key=k, title=offer.BENEFITS[k][0], body=offer.BENEFITS[k][1])
                      for k in order],
            disclosures=list(offer.DISCLOSURES),
            beneficiary_risk_disclosure=list(offer.BENEFICIARY_RISK_DISCLOSURE),
            beneficiary_enabled=beneficiary_on,
            investing_crypto_enabled=offer.crypto_investing_enabled(user, meta),
            payout_rails=offer.payout_rails(),
            dollar=offer.viewer_dollar(user, meta),
            min_first_deposit_usd=format(cheapest, 'f'),
        )

    def resolve_smart_account(self, info):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        from assistant.billing import has_plus
        own = context.own_account(viewer.user)
        base = dict(window_options_days=list(offer.WINDOW_OPTIONS_DAYS),
                    default_window_days=offer.DEFAULT_WINDOW_DAYS,
                    beneficiary_enabled=offer.beneficiary_enabled(viewer.user.pk))
        if own is None:
            return SmartAccountType(status='none', assets=[], rules=[], assistant_plus=False, **base)
        from . import reconcile
        reconcile.refresh_derived(own)
        # Unknown holdings are an error for this field, never an empty list.
        held = assets_mod.assets_of(own.contract_address, include_zero_dollars=False)
        dollars = assets_mod.dollars_usd(held)
        billing = None
        if own.status in ('active', 'cancel_pending', 'expired') and own.plan:
            renewal = own.next_plan or own.plan
            try:
                fee = chain.usd(chain.account_view(own.contract_address, 'feeUsd'))
            except Exception:  # noqa: BLE001 — display falls back to the offer price
                fee = Decimal(offer.price_usd(renewal))
            due = own.billing_status != 'current'
            candidates = None
            if due and dollars < fee:
                from .automation import sale_candidate_symbols
                candidates = sale_candidate_symbols(own)
            billing = SmartAccountBillingType(
                status=own.billing_status, plan=own.plan, next_plan=own.next_plan or None,
                fee_usd=assets_mod.money(fee), paid_until=own.paid_until,
                cancel_requested=own.cancel_requested_at is not None,
                returns_at=own.paid_until if own.cancel_requested_at is not None else None,
                shortfall_usd=assets_mod.money(fee - dollars) if (due and dollars < fee) else None,
                notice_started_at=own.notice_started_at, sale_allowed_at=own.sale_allowed_at,
                sale_candidates=candidates)
        rows = BeneficiaryModel.objects.filter(smart_account=own).select_related('beneficiary_user')
        accepted = rows.filter(state__in=('active', 'stale_address')).order_by('-accepted_at').first()
        pending = rows.filter(state__in=('pending_acceptance', 'declined', 'lapsed')).order_by('-id').first()
        if pending is not None and accepted is not None and pending.id < accepted.id:
            pending = None
        rules = (RuleModel.objects.filter(smart_account=own, state='onchain')
                 .select_related('payee_user', 'payout_method').order_by('id'))
        return SmartAccountType(
            status=own.status, contract_address=own.contract_address,
            total_usd=assets_mod.money(assets_mod.total_usd(held)), dollars_usd=assets_mod.money(dollars),
            billing=billing, assets=[_asset_type(a) for a in held], rules=[_rule_type(r) for r in rules],
            beneficiary=_beneficiary_type(accepted), pending_beneficiary=_beneficiary_type(pending),
            assistant_plus=bool(own.subscription_current() and has_plus(viewer.user)), **base)

    def resolve_smart_account_charges(self, info, first=20, after=None):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        own = context.own_account(viewer.user)
        charges = ChargeModel.objects.filter(smart_account=own).order_by('-charged_at', '-id') if own else []
        return _page(charges, first, after, SmartAccountChargeEdge, SmartAccountChargeConnection,
                     lambda c: SmartAccountChargeType(
                         id=str(c.pk), charged_at=c.charged_at, period_start=c.period_start,
                         period_end=c.period_end, plan=c.plan, fee_usd=assets_mod.money(c.fee_usd),
                         paid_with=c.paid_with, tx_hash=c.tx_hash or None))

    def resolve_smart_account_move_preview(self, info, direction):
        viewer = _viewer(info)
        if viewer is None:
            return None
        try:
            preview = services.move_preview(viewer, direction)
        except services.PrepareError:
            return None
        rows = [SmartAccountMoveAssetType(
            key=r['asset'].key, symbol=r['asset'].symbol, name=r['asset'].name, units=str(r['asset'].units),
            decimals=r['asset'].decimals, value_usd=assets_mod.money(r['asset'].value_usd),
            included=r['included'], reason=r['reason']) for r in preview['rows']]
        rows += [SmartAccountMoveAssetType(key=n['key'], symbol=n['symbol'], name=n['name'], units='0',
                                           decimals=18, value_usd=None, included=False, reason=n['reason'])
                 for n in preview['notes']]
        return SmartAccountMovePreviewType(
            direction=direction, assets=rows,
            total_usd=assets_mod.money(assets_mod.total_usd(preview['included'])), batches=preview['batches'])

    def resolve_smart_account_payout_methods(self, info):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        from payment_accounts import local_money
        from payment_accounts.models import PayoutDestination
        rails = set(offer.payout_rails())
        out = []
        for destination in PayoutDestination.objects.filter(
                confio_account=viewer.personal_account, provider='infinia',
                status__in=('pending', 'active')).order_by('-created_at'):
            rail = services.destination_rail(destination)
            method = local_money.METHODS.get(rail)
            if method is None or method.direction != 'send' or method.kind == 'qr' or rail.endswith('_qr'):
                continue  # a QR is a one-time payment intent, not a saved destination
            if local_money.verification_state((destination.provider_data or {}).get('validation')) != local_money.VERIFIED:
                continue
            out.append(SmartAccountPayoutMethodType(
                payout_method_id=str(destination.internal_id), rail=rail, label=destination.label,
                holder_name=destination.holder_name or '', available=rail in rails))
        return out

    def resolve_smart_account_buyable_assets(self, info, search=None, first=30, after=None):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        items = services.buyable_assets(viewer, search or '')
        return _page(items, first, after, SmartAccountBuyableAssetEdge, SmartAccountBuyableAssetConnection,
                     lambda a: SmartAccountBuyableAssetType(**a))

    def resolve_inherited_accounts(self, info):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        own = context.own_account(viewer.user)
        can_move = own is not None and own.status in ('active', 'cancel_pending')
        out = []
        for account in (SmartAccountModel.objects.filter(owner_user=viewer.user, status='inherited')
                        .filter(account__isnull=False)
                        .select_related('inherited_from_user', 'account').order_by('inherited_at')):
            held = assets_mod.assets_of(account.contract_address)
            out.append(InheritedAccountType(
                inherited_account_id=str(account.internal_id), contract_address=account.contract_address,
                from_name=services.display_name(account.inherited_from_user) if account.inherited_from_user else '',
                inherited_at=account.inherited_at, total_usd=assets_mod.money(assets_mod.total_usd(held)),
                assets=[_asset_type(a) for a in held], can_move_to_smart_account=can_move,
                account_index=account.account.account_index))
        return out

    def resolve_beneficiary_designations(self, info):
        viewer = _viewer(info, require_wallet=False)
        if viewer is None:
            return None
        now = timezone.now()
        out = []
        rows = (BeneficiaryModel.objects
                .filter(beneficiary_user=viewer.user, state__in=('pending_acceptance', 'active', 'declined', 'lapsed'))
                .select_related('smart_account', 'smart_account__owner_user').order_by('-id'))
        for row in rows:
            owner = row.smart_account.owner_user
            claim = _pending_claim(row)
            accepted = row.state == 'active'
            account_ok = row.smart_account.status in ('active', 'cancel_pending')
            cooling = row.cooldown_until is not None and row.cooldown_until > now
            out.append(BeneficiaryDesignationType(
                designation_id=str(row.designation_id), state=row.state,
                owner_name=services.display_name(owner), owner_handle=owner.username or None,
                window_days=row.challenge_window_seconds // 86400,
                designated_at=row.designated_at or row.created_at, accepted_at=row.accepted_at,
                expires_at=row.expires_at if row.state == 'pending_acceptance' else None,
                # Shown only after acceptance: the beneficiary's record for the direct path (6.7).
                contract_address=row.smart_account.contract_address if accepted else None,
                chain_name=CHAIN_NAME if accepted else None,
                cooldown_until=row.cooldown_until, claim=_claim_type(claim),
                can_claim=bool(accepted and account_ok and claim is None and not cooling),
                can_execute=bool(accepted and account_ok and claim is not None and claim.executable_at <= now)))
        return out

    def resolve_smart_account_claim_alert(self, info):
        """Owner-side alert, shown app-wide in EVERY account context: this
        one field therefore reads the user, not the active account."""
        user = getattr(info.context, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        own = context.own_account(user)
        if own is None:
            return None
        claim = (ClaimModel.objects.filter(beneficiary_row__smart_account=own, state='pending')
                 .select_related('beneficiary_row__beneficiary_user').order_by('-initiated_at').first())
        if claim is None:
            return None
        return SmartAccountClaimAlertType(
            beneficiary_name=services.display_name(claim.beneficiary_row.beneficiary_user),
            initiated_at=claim.initiated_at, executable_at=claim.executable_at,
            contract_address=own.contract_address.lower())


# ── mutations ───────────────────────────────────────────────────────────

def _batch_error(code: str, message: str) -> SmartAccountPreparedBatchType:
    return SmartAccountPreparedBatchType(success=False, error_code=code, error_message=message)


def _prepare(info, fn, *args, any_context: bool = False, **kwargs) -> SmartAccountPreparedBatchType:
    """Every prepare mutation: JWT viewer (personal or smart context only;
    business and employee contexts are refused), then the service.
    `any_context` is for prepareClaimCancel alone."""
    try:
        viewer = (context.resolve_owner_any_context(info) if any_context
                  else context.resolve_viewer(info))
    except context.ContextError as exc:
        return _batch_error(exc.code, exc.message)
    try:
        batch = fn(viewer, *args, **kwargs)
    except services.PrepareError as exc:
        return _batch_error(exc.code, exc.message)
    except Exception:  # noqa: BLE001 — nothing was prepared; the user retries
        logger.exception('smart account prepare failed (%s)', getattr(fn, '__name__', fn))
        return _batch_error('internal_error', 'No pudimos preparar la operación. Inténtalo de nuevo.')
    return SmartAccountPreparedBatchType(
        success=True, request_id=batch.request_id,
        calls=[SmartAccountCallType(to=c['to'], value_wei=str(c['value']), data=c['data']) for c in batch.calls],
        not_after=batch.not_after, summary=batch.summary, intent_kind=batch.kind)


def _prepare_mutation(name: str, fn, arguments: dict, doc: str = '', any_context: bool = False):
    """One Mutation class per SDL field, returning SmartAccountPreparedBatch."""
    def mutate(self, info, **kwargs):
        return _prepare(info, fn, any_context=any_context, **kwargs)
    attrs = {'Output': SmartAccountPreparedBatchType, 'mutate': mutate, '__doc__': doc or name,
             'Arguments': type('Arguments', (), arguments)}
    return type(name, (graphene.Mutation,), attrs)


def _subscribe(viewer, plan, disclosures_accepted, deposits=None):
    return services.prepare_subscribe(viewer, plan, deposits, disclosures_accepted)


def _move(viewer, direction, batch_index=0):
    return services.prepare_move_everything(viewer, direction, batch_index)


def _send_rule(viewer, payee_handle, amount_usd, frequency, rule_id=None):
    return services.prepare_send_rule(viewer, rule_id, payee_handle, amount_usd, frequency)


def _payout_rule(viewer, payout_method_id, amount_usd, frequency, rule_id=None):
    return services.prepare_payout_rule(viewer, rule_id, payout_method_id, amount_usd, frequency)


def _buy_rule(viewer, asset_key, amount_usd, frequency, rule_id=None):
    return services.prepare_buy_rule(viewer, rule_id, asset_key, amount_usd, frequency)


def _inherited(viewer, inherited_account_id, destination, asset_keys=None):
    return services.prepare_inherited_withdraw(viewer, inherited_account_id, asset_keys, destination)


_S, _ID, _I, _B = graphene.String, graphene.ID, graphene.Int, graphene.Boolean
_DEPOSITS = graphene.List(graphene.NonNull(SmartAccountDepositInput))

PrepareSmartAccountSubscribe = _prepare_mutation('PrepareSmartAccountSubscribe', _subscribe, {
    'plan': _S(required=True), 'deposits': _DEPOSITS, 'disclosures_accepted': _B(required=True)})
PrepareSmartAccountDeposit = _prepare_mutation(
    'PrepareSmartAccountDeposit', lambda viewer, deposits: services.prepare_deposit(viewer, deposits),
    {'deposits': graphene.List(graphene.NonNull(SmartAccountDepositInput), required=True)})
PrepareSmartAccountMoveEverything = _prepare_mutation('PrepareSmartAccountMoveEverything', _move, {
    'direction': _S(required=True), 'batch_index': _I(default_value=0)})
PrepareSmartAccountWithdraw = _prepare_mutation(
    'PrepareSmartAccountWithdraw', lambda viewer, asset_key, units: services.prepare_withdraw(viewer, asset_key, units),
    {'asset_key': _S(required=True), 'units': _S(required=True)})
PrepareSmartAccountPlanChange = _prepare_mutation(
    'PrepareSmartAccountPlanChange', lambda viewer, plan: services.prepare_plan_change(viewer, plan),
    {'plan': _S(required=True)})
PrepareSmartAccountCancel = _prepare_mutation('PrepareSmartAccountCancel', services.prepare_cancel, {})
PrepareSmartAccountUndoCancel = _prepare_mutation('PrepareSmartAccountUndoCancel', services.prepare_undo_cancel, {})
PrepareSmartAccountSendRule = _prepare_mutation('PrepareSmartAccountSendRule', _send_rule, {
    'rule_id': _ID(), 'payee_handle': _S(required=True), 'amount_usd': _S(required=True),
    'frequency': _S(required=True)})
PrepareSmartAccountPayoutRule = _prepare_mutation('PrepareSmartAccountPayoutRule', _payout_rule, {
    'rule_id': _ID(), 'payout_method_id': _S(required=True), 'amount_usd': _S(required=True),
    'frequency': _S(required=True)})
PrepareSmartAccountBuyRule = _prepare_mutation('PrepareSmartAccountBuyRule', _buy_rule, {
    'rule_id': _ID(), 'asset_key': _S(required=True), 'amount_usd': _S(required=True),
    'frequency': _S(required=True)})
PrepareSmartAccountCancelRule = _prepare_mutation(
    'PrepareSmartAccountCancelRule', lambda viewer, rule_id: services.prepare_cancel_rule(viewer, rule_id),
    {'rule_id': _ID(required=True)})
# ADDITION (spec 7.3 lists it; the frozen SDL has no trade mutation): wraps a
# router call built from the existing quote flow in account.trade(...).
PrepareSmartAccountTrade = _prepare_mutation(
    'PrepareSmartAccountTrade', lambda viewer, venue, data: services.prepare_trade(viewer, venue, data),
    {'venue': _S(required=True, description="'stock' or 'crypto'"),
     'data': _S(required=True, description='Router calldata (buyWithSavings/sellToSavings or buy/sell)')})
PrepareBeneficiaryDesignation = _prepare_mutation(
    'PrepareBeneficiaryDesignation',
    lambda viewer, beneficiary_handle, window_days, disclosure_accepted: services.prepare_designation(
        viewer, beneficiary_handle, window_days, disclosure_accepted),
    {'beneficiary_handle': _S(required=True), 'window_days': _I(required=True),
     'disclosure_accepted': _B(required=True)})
PrepareBeneficiaryDesignationWithdrawal = _prepare_mutation(
    'PrepareBeneficiaryDesignationWithdrawal', services.prepare_designation_withdrawal, {})
PrepareBeneficiaryRemoval = _prepare_mutation('PrepareBeneficiaryRemoval', services.prepare_beneficiary_removal, {})
# From EVERY context of the owner (personal, business owner, employee, smart):
# it acts on the JWT user's own account and is signed with the personal key.
PrepareClaimCancel = _prepare_mutation('PrepareClaimCancel', services.prepare_claim_cancel, {},
                                       any_context=True)
# ADDITION: re-names the current beneficiary with a new window.
PrepareBeneficiaryWindowChange = _prepare_mutation(
    'PrepareBeneficiaryWindowChange',
    lambda viewer, window_days: services.prepare_window_change(viewer, window_days),
    {'window_days': _I(required=True)})
PrepareBeneficiaryAcceptance = _prepare_mutation(
    'PrepareBeneficiaryAcceptance', lambda viewer, designation_id: services.prepare_acceptance(viewer, designation_id),
    {'designation_id': _S(required=True)})
PrepareBeneficiaryClaim = _prepare_mutation(
    'PrepareBeneficiaryClaim', lambda viewer, designation_id: services.prepare_claim(viewer, designation_id),
    {'designation_id': _S(required=True)})
PrepareBeneficiaryClaimExecute = _prepare_mutation(
    'PrepareBeneficiaryClaimExecute',
    lambda viewer, designation_id: services.prepare_claim_execute(viewer, designation_id),
    {'designation_id': _S(required=True)})
PrepareInheritedWithdraw = _prepare_mutation('PrepareInheritedWithdraw', _inherited, {
    'inherited_account_id': _S(required=True), 'asset_keys': graphene.List(graphene.NonNull(graphene.String)),
    'destination': _S(required=True)})


class DeclineBeneficiaryDesignation(graphene.Mutation):
    """Server-only: records declined_at, tells the owner, sends no transaction."""
    class Arguments:
        designation_id = graphene.String(required=True)

    Output = SmartAccountSimpleResultType

    def mutate(self, info, designation_id):
        try:
            viewer = context.resolve_viewer(info)
            services.decline_designation(viewer, designation_id)
        except context.ContextError as exc:
            return SmartAccountSimpleResultType(success=False, error_code=exc.code, error_message=exc.message)
        except services.PrepareError as exc:
            return SmartAccountSimpleResultType(success=False, error_code=exc.code, error_message=exc.message)
        return SmartAccountSimpleResultType(success=True)


class Mutation(graphene.ObjectType):
    prepare_smart_account_subscribe = PrepareSmartAccountSubscribe.Field()
    prepare_smart_account_deposit = PrepareSmartAccountDeposit.Field()
    prepare_smart_account_move_everything = PrepareSmartAccountMoveEverything.Field()
    prepare_smart_account_withdraw = PrepareSmartAccountWithdraw.Field()
    prepare_smart_account_plan_change = PrepareSmartAccountPlanChange.Field()
    prepare_smart_account_cancel = PrepareSmartAccountCancel.Field()
    prepare_smart_account_undo_cancel = PrepareSmartAccountUndoCancel.Field()
    prepare_smart_account_send_rule = PrepareSmartAccountSendRule.Field()
    prepare_smart_account_payout_rule = PrepareSmartAccountPayoutRule.Field()
    prepare_smart_account_buy_rule = PrepareSmartAccountBuyRule.Field()
    prepare_smart_account_cancel_rule = PrepareSmartAccountCancelRule.Field()
    prepare_smart_account_trade = PrepareSmartAccountTrade.Field()
    prepare_beneficiary_designation = PrepareBeneficiaryDesignation.Field()
    prepare_beneficiary_designation_withdrawal = PrepareBeneficiaryDesignationWithdrawal.Field()
    prepare_beneficiary_removal = PrepareBeneficiaryRemoval.Field()
    prepare_claim_cancel = PrepareClaimCancel.Field()
    prepare_beneficiary_window_change = PrepareBeneficiaryWindowChange.Field()
    prepare_beneficiary_acceptance = PrepareBeneficiaryAcceptance.Field()
    decline_beneficiary_designation = DeclineBeneficiaryDesignation.Field()
    prepare_beneficiary_claim = PrepareBeneficiaryClaim.Field()
    prepare_beneficiary_claim_execute = PrepareBeneficiaryClaimExecute.Field()
    prepare_inherited_withdraw = PrepareInheritedWithdraw.Field()
