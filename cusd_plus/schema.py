# Confío Dollar+ (cUSD+) — GraphQL seam for the savings product.
#
# STATUS: schema-only stubs. The build behind these resolvers is gated on the
# whale deposit-intent signal (decision 68e9cd45); the app already renders
# from this exact shape via useAhorrosPortfolio, so when the backend lands the
# client swaps its memoized stub for these queries without reshaping.
#
# Contract for the real implementation (locked decisions):
# - net_apy_pct is SERVER-DERIVED: USDY oracle gross (RWADynamicOracle) minus
#   Confío's 15% share. Never hardcoded — rates float with US Treasuries.
# - balance_usd is the USD value of the user's accumulating shares. Share
#   counts are NEVER exposed anywhere in the API (decision A).
# - Account context comes from the JWT (get_jwt_business_context_with_validation
#   for business accounts) — never from client parameters.
# - Quoting is CLIENT-side (decision (b)): the app prices the Allbridge leg
#   with ported pool math; cusdPlusConvertParams supplies threshold/fee/kill
#   switch. `paused` maps to the amber state in ConvertAhorroScreen.

import graphene


class CusdPlusSummaryType(graphene.ObjectType):
    """Savings position for the active account (JWT context)."""
    balance_usd = graphene.Float(description="USD value of the position; share counts are never exposed")
    net_apy_pct = graphene.Float(description="Oracle gross minus Confío share; floats daily")
    earned_today_usd = graphene.Float()
    earned_month_usd = graphene.Float()
    stocks_enabled = graphene.Boolean(description="Server flag gating the Ondo Stocks surfaces (geofence-aware)")


class CusdPlusMovementType(graphene.ObjectType):
    """One row of savings history (deposits, withdrawals, stock buys/sells
    settling against cUSD+, and weekly yield summary rows — never per-day)."""
    id = graphene.ID()
    movement_type = graphene.String(description="deposit | withdraw | buy | sell | yield")
    title = graphene.String()
    amount_usd = graphene.Float(description="Signed: inflows to savings positive")
    created_at = graphene.DateTime()


class CusdPlusConvertParamsType(graphene.ObjectType):
    """Decision (b), 2026-07-04: the CLIENT prices the bridge leg with the
    ported Allbridge pool math (apps/src/services/allbridgeQuote.ts, validated
    against the official SDK); the server owns only these guard/fee knobs.
    Contract-side floors (minUsdyOut / receive minimums) remain the hard
    protection — these params shape UX, they don't secure funds."""
    spread_threshold_bps = graphene.Int(description="Guard: max total conversion cost in bps (remote config)")
    confio_fee_bps = graphene.Int(description="Confío conversion fee — open pricing decision, 0 until set")
    min_amount_usd = graphene.Float()
    paused = graphene.Boolean(description="Kill switch: pause all conversions regardless of cost")


class Query(graphene.ObjectType):
    cusd_plus_summary = graphene.Field(CusdPlusSummaryType)
    cusd_plus_movements = graphene.List(
        graphene.NonNull(CusdPlusMovementType),
        limit=graphene.Int(default_value=20),
        offset=graphene.Int(default_value=0),
    )
    cusd_plus_convert_params = graphene.Field(CusdPlusConvertParamsType)

    def resolve_cusd_plus_summary(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        # TODO(cusd+): position from the vault ledger for the JWT account;
        # net_apy_pct from the USDY oracle rate x (1 - CONFIO_YIELD_SHARE).
        return CusdPlusSummaryType(
            balance_usd=0.0,
            net_apy_pct=0.0,
            earned_today_usd=0.0,
            earned_month_usd=0.0,
            stocks_enabled=False,
        )

    def resolve_cusd_plus_movements(self, info, limit=20, offset=0):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        # TODO(cusd+): paginated ledger rows for the JWT account (newest
        # first); yield entries are weekly aggregates, never per-day spam.
        return []

    def resolve_cusd_plus_convert_params(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        from django.conf import settings
        # paused=True until the conversion rails ship — the client treats the
        # kill switch as authoritative, so no build can convert prematurely.
        return CusdPlusConvertParamsType(
            spread_threshold_bps=getattr(settings, 'CUSD_PLUS_SPREAD_THRESHOLD_BPS', 50),
            confio_fee_bps=getattr(settings, 'CUSD_PLUS_CONVERT_FEE_BPS', 0),
            min_amount_usd=getattr(settings, 'CUSD_PLUS_MIN_CONVERT_USD', 1.0),
            paused=getattr(settings, 'CUSD_PLUS_CONVERSIONS_PAUSED', True),
        )
