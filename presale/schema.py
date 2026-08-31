import logging

import graphene
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from graphql import GraphQLError

from .models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings, PresaleWaitlist
from users.models import Account

logger = logging.getLogger(__name__)


class PresalePhaseType(DjangoObjectType):
    total_raised = graphene.Decimal()
    total_participants = graphene.Int()
    tokens_sold = graphene.Decimal()
    progress_percentage = graphene.Float()
    vision_points = graphene.List(graphene.String)
    status = graphene.String()
    
    class Meta:
        model = PresalePhase
        fields = '__all__'
    
    def resolve_status(self, info):
        return self.status
    
    def resolve_total_raised(self, info):
        return self.total_raised
    
    def resolve_total_participants(self, info):
        return self.total_participants
    
    def resolve_tokens_sold(self, info):
        return self.tokens_sold
    
    def resolve_progress_percentage(self, info):
        return float(self.progress_percentage)


class PresalePurchaseType(DjangoObjectType):
    class Meta:
        model = PresalePurchase
        fields = '__all__'


class PresaleStatsType(DjangoObjectType):
    class Meta:
        model = PresaleStats
        fields = '__all__'


class UserPresaleLimitType(DjangoObjectType):
    class Meta:
        model = UserPresaleLimit
        fields = '__all__'


class PresaleOnchainInfo(graphene.ObjectType):
    purchased = graphene.Float()
    claimed = graphene.Float()
    claimable = graphene.Float()
    locked = graphene.Boolean()


class PresaleTelegramGroupType(graphene.ObjectType):
    enabled = graphene.Boolean()
    url = graphene.String()


class PresaleCurveStatsType(graphene.ObjectType):
    """The continuous-curve presale story in one object: a moving price
    between locked endpoints, recaudado-axis progress with absolute
    milestones (never a % of the full sale), and social proof."""
    current_price = graphene.Decimal()
    start_price = graphene.Decimal()
    final_price = graphene.Decimal()
    total_raised_usd = graphene.Decimal()
    next_milestone_usd = graphene.Decimal()
    participants = graphene.Int()


class PresaleQueries(graphene.ObjectType):
    """Queries for presale data"""
    
    is_presale_active = graphene.Boolean()
    is_presale_claims_unlocked = graphene.Boolean()
    confio_current_price = graphene.Decimal(
        description="Live CONFIO price from the BSC presale curve (cached ~60s); "
                    "falls back to the last phase price when the vault is unreachable"
    )
    presale_curve_stats = graphene.Field(
        PresaleCurveStatsType,
        description="Moving curve price + recaudado milestones for the presale screens"
    )
    presale_chain = graphene.String(
        description="Which chain the purchase flow runs on: 'algorand' (legacy) or 'bsc'"
    )
    active_presale_phase = graphene.Field(PresalePhaseType)
    all_presale_phases = graphene.List(PresalePhaseType)
    presale_phase = graphene.Field(
        PresalePhaseType,
        phase_number=graphene.Int(required=True)
    )
    my_presale_purchases = graphene.List(PresalePurchaseType)
    my_presale_limit = graphene.Field(
        UserPresaleLimitType,
        phase_number=graphene.Int(required=True)
    )
    my_presale_onchain_info = graphene.Field(PresaleOnchainInfo)
    presale_telegram_group = graphene.Field(PresaleTelegramGroupType)
    
    def resolve_is_presale_active(self, info):
        """Check if presale is globally enabled - no login required for this check"""
        settings = PresaleSettings.get_settings()
        return settings.is_presale_active

    def resolve_confio_current_price(self, info):
        """Moving curve price for holdings valuation - no login required"""
        from .price_utils import get_confio_current_price
        return get_confio_current_price()

    def resolve_presale_chain(self, info):
        """Purchase-flow chain switch - no login required"""
        from django.conf import settings as dj_settings
        # Which rail THIS client should use. Only a build that ships the BSC
        # mutations asks (and can act on) this — an old build never queries
        # the field and keeps using the WebSocket, which stays open. So the
        # answer is simply "is the BSC rail live", not a global cutover.
        if (getattr(dj_settings, 'PRESALE_BSC_ENABLED', False)
                and getattr(dj_settings, 'BSC_PRESALE_VAULT_ADDRESS', None)):
            return 'bsc'
        return 'algorand'

    def resolve_presale_curve_stats(self, info):
        """Curve stats for the presale screens - no login required"""
        from .price_utils import get_presale_curve_stats
        stats = get_presale_curve_stats()
        return PresaleCurveStatsType(
            current_price=stats['current_price'],
            start_price=stats['start_price'],
            final_price=stats['final_price'],
            total_raised_usd=stats['total_raised_usd'],
            next_milestone_usd=stats['next_milestone_usd'],
            participants=stats['participants'],
        )

    def resolve_is_presale_claims_unlocked(self, info):
        """Check if presale claims are globally unlocked - no login required for this check"""
        settings = PresaleSettings.get_settings()
        return settings.is_presale_claims_unlocked

    @login_required
    def resolve_presale_telegram_group(self, info):
        """Return Telegram group config for presale participants"""
        settings = PresaleSettings.get_settings()
        return PresaleTelegramGroupType(
            enabled=settings.telegram_group_enabled,
            url=settings.telegram_group_url if settings.telegram_group_enabled else ''
        )
    
    @login_required
    def resolve_active_presale_phase(self, info):
        """Get the currently active presale phase"""
        # First check if presale is globally enabled
        settings = PresaleSettings.get_settings()
        if not settings.is_presale_active:
            return None
        return PresalePhase.objects.filter(status='active').first()
    
    @login_required
    def resolve_all_presale_phases(self, info):
        """Get all presale phases"""
        return PresalePhase.objects.all().order_by('phase_number')
    
    @login_required
    def resolve_presale_phase(self, info, phase_number):
        """Get a specific presale phase by number"""
        try:
            return PresalePhase.objects.get(phase_number=phase_number)
        except PresalePhase.DoesNotExist:
            return None
    
    @login_required
    def resolve_my_presale_purchases(self, info):
        """Get user's presale purchases"""
        user = info.context.user
        return PresalePurchase.objects.filter(user=user).select_related('phase')
    
    @login_required
    def resolve_my_presale_limit(self, info, phase_number):
        """Get user's purchase limit for a phase"""
        user = info.context.user
        try:
            phase = PresalePhase.objects.get(phase_number=phase_number)
            limit, _ = UserPresaleLimit.objects.get_or_create(
                user=user,
                phase=phase
            )
            return limit
        except PresalePhase.DoesNotExist:
            return None

    @login_required
    def resolve_my_presale_onchain_info(self, info):
        return presale_onchain_info(info.context.user)


def presale_onchain_info(user):
    """Purchased / claimed / claimable, read from the chain that actually
    pays: BSC.

    $CONFIO exists only on BSC, so the Algorand presale app's local state
    is NOT the answer — reading it would show a claimable balance on a
    rail whose claim path never opens (presale/ws_consumers
    ALGORAND_CLAIMS_NEVER_OPEN), and would double-count a buyer whose
    allocation has already been carried over by creditMigrated.

    Before a user enrolls a BSC address, the honest answer is the DB: they
    own what they bought, and nothing is claimable yet because their
    allocation cannot be assigned on-chain until they update the app.

    Takes a user, not a ResolveInfo: the CONFIO breakdown in users/schema
    needs the same numbers, and reaching through the decorated resolver
    would have coupled it to graphql_jwt's arg inspection.
    """
    from decimal import Decimal

    from django.conf import settings as dj_settings

    from users.models import Account
    from .models import PresalePurchase

    def _db_owned() -> float:
        # Aggregate in the DB: a user with a long purchase history would
        # otherwise pull every row into Python for a sum (Codex audit
        # 2026-08-02, P2).
        from django.db.models import Sum
        total = PresalePurchase.objects.filter(
            user=user, status='completed',
        ).aggregate(s=Sum('confio_amount'))['s']
        return float(total or 0)

    try:
        vault = (getattr(dj_settings, 'BSC_PRESALE_VAULT_ADDRESS', '') or '').lower()
        account = Account.objects.filter(
            user=user, account_type='personal', deleted_at__isnull=True).first()
        bsc_address = (getattr(account, 'bsc_address', None) or '').lower()

        if not vault or not bsc_address:
            # Not enrolled (or vault unset): show what they own, locked.
            return PresaleOnchainInfo(
                purchased=_db_owned(), claimed=0.0, claimable=0.0, locked=True)

        from eth_utils import keccak

        from .bsc_flow import _addr_word, _eth_call

        def call(sig: str) -> int:
            return _eth_call(vault, '0x' + keccak(text=sig)[:4].hex() + _addr_word(bsc_address))

        from django.core.cache import cache

        cache_key = f'presale:onchain_info:{bsc_address}'
        try:
            purchased = call('purchased(address)') / 10 ** 18
            claimed = call('claimed(address)') / 10 ** 18
            claimable = call('claimableOf(address)') / 10 ** 18
            unlocked = bool(_eth_call(vault, '0x' + keccak(text='claimsUnlocked()')[:4].hex()))
            # Keep the last GOOD read: an RPC blip used to report
            # claimable=0, which the app renders as "nothing to claim" and
            # disables the button — hiding real funds instead of showing a
            # transient error (Codex audit 2026-08-02, P2).
            cache.set(cache_key, (purchased, claimed, claimable, unlocked), 24 * 3600)
        except Exception:
            logger.warning('[PRESALE] onchain read failed for %s; serving last known', bsc_address)
            last = cache.get(cache_key)
            if last is None:
                raise
            purchased, claimed, claimable, unlocked = last

        # A migration credit that hasn't been assigned on-chain yet still
        # belongs to the user — show the DB figure so nobody thinks their
        # purchase vanished while the Safe batch is pending.
        return PresaleOnchainInfo(
            purchased=max(purchased, _db_owned()),
            claimed=claimed,
            claimable=claimable,
            locked=not unlocked,
        )
    except Exception:
        logger.exception('[PRESALE] onchain info read failed for user %s', getattr(user, 'id', None))
        return PresaleOnchainInfo(
            purchased=_db_owned(), claimed=0.0, claimable=0.0, locked=True)


class BscPresaleCallType(graphene.ObjectType):
    """One call of the sponsored 7702 buy batch (server-built; the client
    signs exactly these and nothing else)."""
    to = graphene.String()
    value_wei = graphene.String()
    data = graphene.String()


class BscPresaleAuthorizationInput(graphene.InputObjectType):
    """A signed EIP-7702 authorization tuple (first use only) — same shape
    as cusd_plus's BscAuthorizationInput, defined locally to keep the
    presale schema import-independent."""
    chain_id = graphene.Int(required=True)
    address = graphene.String(required=True)
    nonce = graphene.String(required=True)
    y_parity = graphene.Int(required=True)
    r = graphene.String(required=True)
    s = graphene.String(required=True)


class PrepareBscPresalePurchase(graphene.Mutation):
    """Step 1 of the BSC presale buy: full eligibility gate + on-chain quote
    + purchase record. Returns the exact [approve, buy] batch the client
    must sign as one EIP-712 intent (ConfioBatchDelegate.execute)."""

    class Arguments:
        amount_usd = graphene.Decimal(required=True)
        accepted_terms = graphene.Boolean(required=True)
        not_us_attestation = graphene.Boolean(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    purchase_id = graphene.String()
    calls = graphene.List(BscPresaleCallType)
    confio_amount = graphene.String()
    cost = graphene.String()
    max_payment = graphene.String()
    confio_fee = graphene.String()
    avg_price = graphene.String()
    funding_source = graphene.String(
        description="'cusd_direct' or 'cusd_plus_via_cusd' (fee-free internal "
                    "savings unwrap inside the atomic buy batch when needed)")
    intent_id = graphene.String()  # bytes32 the client binds into its signature
    # Signing params the SERVER read, so the device makes zero chain calls on
    # the happy path (see bsc_flow.execution_params for why that's safe).
    delegate_nonce = graphene.String()
    is_delegated = graphene.Boolean()
    account_nonce = graphene.String(description="EOA nonce for the 7702 authorization; only meaningful when isDelegated is false")
    delegate_address = graphene.String()

    @login_required
    def mutate(self, info, amount_usd, accepted_terms, not_us_attestation):
        from django.conf import settings as dj_settings

        from cusd_plus.schema import _active_account, _bsc_rate_limited
        from security.request_utils import extract_client_ip_from_meta

        from . import bsc_flow

        user = info.context.user
        if not getattr(dj_settings, 'PRESALE_BSC_ENABLED', False):
            return PrepareBscPresalePurchase(success=False, error='bsc_presale_disabled')
        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return PrepareBscPresalePurchase(success=False, error='disabled')
        if _bsc_rate_limited(user.id, 'presale_prepare', 10):
            return PrepareBscPresalePurchase(success=False, error='rate_limited')

        account = _active_account(info)
        if not account or account.account_type != 'personal':
            return PrepareBscPresalePurchase(success=False, error='personal_account_required')

        meta = getattr(info.context, 'META', {}) or {}
        res = bsc_flow.prepare_purchase(
            user, account, amount_usd,
            accepted_terms=bool(accepted_terms),
            not_us_attestation=bool(not_us_attestation),
            client_ip=extract_client_ip_from_meta(meta),
            ip_country_hint=meta.get('HTTP_CF_IPCOUNTRY'),
            user_agent=meta.get('HTTP_USER_AGENT', ''),
        )
        if not res.get('success'):
            return PrepareBscPresalePurchase(success=False, error=res.get('error'))
        return PrepareBscPresalePurchase(
            success=True,
            purchase_id=res['purchase_id'],
            calls=[BscPresaleCallType(to=c['to'], value_wei=c['value'], data=c['data'])
                   for c in res['calls']],
            confio_amount=res['confio_amount'],
            cost=res['cost'],
            max_payment=res['max_payment'],
            confio_fee=res.get('confio_fee'),
            avg_price=res['avg_price'],
            funding_source=res.get('funding_source'),
            intent_id=res['intent_id'],
            delegate_nonce=res.get('delegate_nonce'),
            is_delegated=res.get('is_delegated'),
            account_nonce=res.get('account_nonce'),
            delegate_address=res.get('delegate_address'),
        )


class SubmitBscPresalePurchase(graphene.Mutation):
    """Step 2: the user's signature over the server-stored batch. The server
    recomputes the digest from what IT stored — a client cannot substitute
    calldata — re-checks geo, then broadcasts from the KMS sponsor."""

    class Arguments:
        purchase_id = graphene.String(required=True)
        nonce = graphene.String(required=True, description="Delegate intent nonce (nonces())")
        deadline = graphene.String(required=True, description="Unix seconds")
        intent_signature = graphene.String(required=True, description="65-byte r‖s‖v hex")
        authorization = BscPresaleAuthorizationInput(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    # Present on the two RETRYABLE failures so the client re-signs without
    # reading the chain itself.
    delegate_nonce = graphene.String()
    is_delegated = graphene.Boolean()
    account_nonce = graphene.String()
    transaction_hash = graphene.String()
    # See SubmitBscSend.execution in send/schema.py.
    execution = graphene.String(
        description="Sponsor-observed execution: executed | reverted | noop; null=unknown")

    @login_required
    def mutate(self, info, purchase_id, nonce, deadline, intent_signature, authorization=None):
        from django.conf import settings as dj_settings

        from cusd_plus.schema import _bsc_rate_limited
        from security.request_utils import extract_client_ip_from_meta

        from . import bsc_flow
        from .models import PresalePurchase

        user = info.context.user
        if not getattr(dj_settings, 'PRESALE_BSC_ENABLED', False):
            return SubmitBscPresalePurchase(success=False, error='bsc_presale_disabled')
        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return SubmitBscPresalePurchase(success=False, error='disabled')
        if _bsc_rate_limited(user.id, 'presale_submit', 5):
            return SubmitBscPresalePurchase(success=False, error='rate_limited')

        purchase = PresalePurchase.objects.filter(
            internal_id=purchase_id, user=user).first()
        if not purchase:
            return SubmitBscPresalePurchase(success=False, error='purchase_not_found')

        try:
            nonce_i = int(nonce)
            deadline_i = int(deadline)
        except (TypeError, ValueError):
            return SubmitBscPresalePurchase(success=False, error='bad_params')

        meta = getattr(info.context, 'META', {}) or {}
        res = bsc_flow.submit_purchase(
            user, purchase, nonce_i, deadline_i, intent_signature,
            authorization=authorization,
            client_ip=extract_client_ip_from_meta(meta),
            ip_country_hint=meta.get('HTTP_CF_IPCOUNTRY'),
        )
        return SubmitBscPresalePurchase(
            success=bool(res.get('success')),
            error=res.get('error'),
            authorization_required=bool(res.get('authorization_required')),
            delegate_nonce=res.get('delegate_nonce'),
            is_delegated=res.get('is_delegated'),
            account_nonce=res.get('account_nonce'),
            transaction_hash=res.get('transaction_hash'),
            execution=res.get('execution'),
        )


class PurchasePresaleTokens(graphene.Mutation):
    """Mutation to purchase CONFIO tokens during presale"""

    class Arguments:
        cusd_amount = graphene.Decimal(required=True)
        phase_number = graphene.Int(required=False)

    success = graphene.Boolean()
    message = graphene.String()
    purchase = graphene.Field(PresalePurchaseType)

    @login_required
    def mutate(self, info, cusd_amount, phase_number=None):
        # The presale purchase flow is implemented over WebSocket for a fully
        # sponsored, two-step (prepare/submit) UX similar to Pay/Send/Conversion.
        # Use ws endpoint /ws/presale_session to prepare and submit transactions.
        raise GraphQLError("Use WebSocket /ws/presale_session for presale purchases (prepare + submit)")


class JoinPresaleWaitlist(graphene.Mutation):
    """Mutation to join the presale waitlist"""

    class Arguments:
        pass

    success = graphene.Boolean()
    message = graphene.String()
    already_joined = graphene.Boolean()

    @login_required
    def mutate(self, info):
        user = info.context.user
        
        from .geo_utils import check_presale_eligibility
        from security.request_utils import extract_client_ip_from_meta
        request = info.context
        client_ip = extract_client_ip_from_meta(getattr(request, 'META', None))
        ip_country_hint = (getattr(request, 'META', None) or {}).get('HTTP_CF_IPCOUNTRY')
        is_eligible, error_msg = check_presale_eligibility(user, client_ip=client_ip, ip_country_hint=ip_country_hint)
        if not is_eligible:
            return JoinPresaleWaitlist(
                success=False,
                message=error_msg,
                already_joined=False
            )

        # Check if user already joined
        existing = PresaleWaitlist.objects.filter(user=user).first()
        if existing:
            return JoinPresaleWaitlist(
                success=True,
                message="Ya estás en la lista de espera. Te notificaremos cuando la preventa esté disponible.",
                already_joined=True
            )

        # Create new waitlist entry
        PresaleWaitlist.objects.create(user=user)

        return JoinPresaleWaitlist(
            success=True,
            message="¡Te has unido a la lista de espera! Te notificaremos cuando la preventa esté disponible.",
            already_joined=False
        )


class PresaleMutations(graphene.ObjectType):
    """Mutations for presale operations"""
    purchase_presale_tokens = PurchasePresaleTokens.Field()
    join_presale_waitlist = JoinPresaleWaitlist.Field()
    prepare_bsc_presale_purchase = PrepareBscPresalePurchase.Field()
    submit_bsc_presale_purchase = SubmitBscPresalePurchase.Field()
