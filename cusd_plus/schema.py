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
# - Quotes are per-conversion, computed against the live route (bridge leg +
#   InstantManager on BSC) with the remote-config spread guard; `paused` maps
#   to the amber market-conditions state in ConvertAhorroScreen.

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


class CusdPlusQuoteType(graphene.ObjectType):
    """Conversion quote (cUSD <-> cUSD+). Amounts in USD."""
    direction = graphene.String(description="to_savings | from_savings")
    amount_usd = graphene.Float()
    cost_pct = graphene.Float()
    cost_usd = graphene.Float()
    receive_usd = graphene.Float()
    paused = graphene.Boolean(description="Spread guard tripped; client shows the amber paused state")


class Query(graphene.ObjectType):
    cusd_plus_summary = graphene.Field(CusdPlusSummaryType)
    cusd_plus_movements = graphene.List(
        graphene.NonNull(CusdPlusMovementType),
        limit=graphene.Int(default_value=20),
        offset=graphene.Int(default_value=0),
    )
    cusd_plus_quote = graphene.Field(
        CusdPlusQuoteType,
        amount_usd=graphene.Float(required=True),
        direction=graphene.String(default_value='to_savings'),
    )

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

    def resolve_cusd_plus_quote(self, info, amount_usd, direction='to_savings'):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        # TODO(cusd+): live quote against the actual route (bridge leg +
        # InstantManager) with the remote-config spread threshold; until the
        # rails exist this quote reports the route as paused so no client can
        # act on a fabricated price.
        return CusdPlusQuoteType(
            direction=direction,
            amount_usd=amount_usd,
            cost_pct=0.0,
            cost_usd=0.0,
            receive_usd=0.0,
            paused=True,
        )
