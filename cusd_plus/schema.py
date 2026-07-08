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
from django.utils import timezone


class CusdPlusSummaryType(graphene.ObjectType):
    """Savings position for the active account (JWT context)."""
    balance_usd = graphene.Float(description="USD value of the position; share counts are never exposed")
    net_apy_pct = graphene.Float(description="Oracle gross minus Confío share; floats daily")
    earned_today_usd = graphene.Float()
    earned_month_usd = graphene.Float()
    savings_enabled = graphene.Boolean(description="Issuer geo-eligibility (Ondo) by phone country; gates ENTRY only — exits are never gated")
    stocks_enabled = graphene.Boolean(description="Server flag gating the Ondo Stocks surfaces (geofence-aware AND dark-launch flag)")


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
    gm_trade_fee_bps = graphene.Int(description="Stock trade fee for quote display; the router's on-chain stockFeeBps is authoritative")


# ── Ondo Stocks (GM) market data — server proxy of api.gm.ondo.finance ──
# Display data only (chain-first): execution prices come from attestation
# quotes at trade time; nothing money-touching reads these fields.

class GmAssetType(graphene.ObjectType):
    symbol = graphene.String(description="GM token symbol, e.g. TSLAon — the on-chain/trading id")
    ticker = graphene.String(description="Underlying ticker, e.g. TSLA — the display id")
    name = graphene.String()
    price_usd = graphene.Float()
    day_change_pct = graphene.Float()
    off_hours = graphene.Boolean(description="Tradable on weekends/holidays (per-asset, per Ondo)")
    sparkline24h = graphene.List(graphene.Float, description="Downsampled 24h price series for charts")
    logo_url = graphene.String(description="Served from OUR S3 mirror — the app never hotlinks third parties")


class GmMarketType(graphene.ObjectType):
    session = graphene.String(description="core | extended | off-hours | closed")
    assets = graphene.List(graphene.NonNull(GmAssetType))


class GmCandleType(graphene.ObjectType):
    timestamp = graphene.Float(description="ms epoch")
    open = graphene.Float()
    high = graphene.Float()
    low = graphene.Float()
    close = graphene.Float()


_NAME_NOISE = (
    ' Common Stock', ' Class A', ' Class B', ' Class C', ', Inc.', ' Inc.',
    ' Corporation', ' Corp.', ' Holdings', ' Ltd.', ' PLC', ' N.V.', ' S.A.',
)


def _display_name(raw: str) -> str:
    name = raw or ''
    for noise in _NAME_NOISE:
        name = name.replace(noise, '')
    return name.strip(' ,')


def _sparkline(history: list, points: int = 24) -> list:
    if not history:
        return []
    step = max(1, len(history) // points)
    series = [float(h['price']) for h in history[::step]]
    last = float(history[-1]['price'])
    if not series or series[-1] != last:
        series.append(last)
    return series


class Query(graphene.ObjectType):
    cusd_plus_summary = graphene.Field(CusdPlusSummaryType)
    cusd_plus_movements = graphene.List(
        graphene.NonNull(CusdPlusMovementType),
        limit=graphene.Int(default_value=20),
        offset=graphene.Int(default_value=0),
    )
    cusd_plus_convert_params = graphene.Field(CusdPlusConvertParamsType)
    cusd_plus_conversions_in_flight = graphene.List(
        graphene.NonNull(lambda: CusdPlusConversionType),
    )
    gm_market = graphene.Field(GmMarketType)
    gm_ohlc = graphene.List(
        graphene.NonNull(GmCandleType),
        symbol=graphene.String(required=True),
        range=graphene.String(default_value='3M', description="1D | 1M | 3M | 6M | 1Y | MAX"),
    )

    def resolve_gm_market(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        from . import gm_api
        try:
            market = gm_api.all_market()
            session = gm_api.session_from_status(gm_api.market_status())
        except Exception:
            import logging
            logging.getLogger(__name__).exception('gm_market upstream failed')
            return None  # client keeps its last cache; never a fake price
        from django.conf import settings
        from security.s3_utils import public_s3_url
        logos_bucket = getattr(settings, 'AWS_PUBLICATIONS_BUCKET', None)
        # Raw FMP mirrors (Julian, 2026-07-08: baked chips looked worse than
        # the ~50 white-glyph logos they fixed — reverted). Prefix bumps
        # double as cache-busts if a processed set ever returns.
        logos_prefix = getattr(settings, 'GM_LOGOS_S3_PREFIX', 'stock-logos/')

        ranked = []  # (market cap, asset) — famous names first
        for item in market:
            pm = item.get('primaryMarket') or {}
            um = item.get('underlyingMarket') or {}
            if not pm.get('symbol') or pm.get('price') is None:
                continue
            ticker = um.get('ticker') or pm['symbol'].removesuffix('on')
            asset = GmAssetType(
                symbol=pm['symbol'],
                ticker=ticker,
                name=_display_name(um.get('name') or um.get('ticker') or ''),
                price_usd=float(pm['price']),
                day_change_pct=float(pm.get('priceChangePct24h') or 0),
                off_hours='offhours' in (pm.get('tradableSessions') or []),
                sparkline24h=_sparkline(pm.get('priceHistory24h') or []),
                logo_url=public_s3_url(f'{logos_prefix}{ticker}.png', bucket=logos_bucket)
                if logos_bucket else None,
            )
            ranked.append((float(um.get('marketCap') or 0), asset))
        # Discovery order = market cap descending: with 438 assets the list
        # must open on household names (AAPL, NVDA, SPY…), not alphabet soup.
        # The client still floats the user's HELD positions above everything.
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return GmMarketType(session=session, assets=[a for _, a in ranked])

    def resolve_gm_ohlc(self, info, symbol, range='3M'):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        from . import gm_api
        if range not in gm_api.OHLC_RANGES:
            return []
        # symbol comes from our own gmMarket payload, but sanitize anyway
        symbol = ''.join(c for c in symbol if c.isalnum())[:24]
        try:
            candles = gm_api.ohlc(symbol, range)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('gm_ohlc upstream failed')
            return []
        return [
            GmCandleType(
                timestamp=float(c['timestamp']),
                open=float(c['open']),
                high=float(c['high']),
                low=float(c['low']),
                close=float(c['close']),
            )
            for c in candles
        ]

    def resolve_cusd_plus_summary(self, info):
        from django.conf import settings
        from .eligibility import is_ondo_eligible
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        eligible = is_ondo_eligible(user)
        # TODO(cusd+): position from the vault ledger for the JWT account;
        # net_apy_pct from the USDY oracle rate x (1 - CONFIO_YIELD_SHARE).
        return CusdPlusSummaryType(
            balance_usd=0.0,
            net_apy_pct=0.0,
            earned_today_usd=0.0,
            earned_month_usd=0.0,
            savings_enabled=eligible,
            # Dark until the demand signal (decision 2dcfada5) AND geo-eligible.
            stocks_enabled=eligible and getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False),
        )

    def resolve_cusd_plus_movements(self, info, limit=20, offset=0):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        # TODO(cusd+): paginated ledger rows for the JWT account (newest
        # first); yield entries are weekly aggregates, never per-day spam.
        return []

    def resolve_cusd_plus_conversions_in_flight(self, info):
        from .models import CusdPlusConversion
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        scope = _actor_filter(info)
        if scope is None:
            return []
        lookup = {'is_deleted': False, 'status__in': CusdPlusConversion.IN_FLIGHT_STATUSES}
        if scope['actor_type'] == 'business':
            lookup['actor_business_id'] = scope['actor_business_id']
        else:
            lookup['actor_user'] = user
        return [_serialize(c) for c in CusdPlusConversion.objects.filter(**lookup)[:20]]

    def resolve_cusd_plus_convert_params(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        from django.conf import settings
        # paused=True until the conversion rails ship — the client treats the
        # kill switch as authoritative, so no build can convert prematurely.
        return CusdPlusConvertParamsType(
            # 100bps ceiling: guard stops catastrophes, not conversions —
            # within 1% the user sees the quoted cost and decides
            spread_threshold_bps=getattr(settings, 'CUSD_PLUS_SPREAD_THRESHOLD_BPS', 100),
            confio_fee_bps=getattr(settings, 'CUSD_PLUS_CONVERT_FEE_BPS', 0),
            min_amount_usd=getattr(settings, 'CUSD_PLUS_MIN_CONVERT_USD', 1.0),
            paused=getattr(settings, 'CUSD_PLUS_CONVERSIONS_PAUSED', True),
            # Launch config, set together with router.setStockFeeBps once
            # Ondo's GM fee schedule is known — open pricing decision.
            gm_trade_fee_bps=getattr(settings, 'CUSD_PLUS_GM_TRADE_FEE_BPS', 0),
        )


# ── Conversion saga (server = observer; client signs every leg) ─────────

class CusdPlusConversionType(graphene.ObjectType):
    """One client-driven conversion saga row (ORCHESTRATION.md). The client
    uses inFlight rows to resume the next leg on foreground."""
    conversion_id = graphene.ID()
    direction = graphene.String()
    amount_usd = graphene.Float()
    quoted_receive_usd = graphene.Float()
    status = graphene.String()
    src_tx_id = graphene.String()
    dest_tx_hash = graphene.String()
    user_bsc_address = graphene.String()
    created_at = graphene.DateTime()


def _serialize(conv):
    return CusdPlusConversionType(
        conversion_id=str(conv.internal_id),
        direction=conv.direction,
        amount_usd=float(conv.amount_usd),
        quoted_receive_usd=float(conv.quoted_receive_usd),
        status=conv.status,
        src_tx_id=conv.src_tx_id,
        dest_tx_hash=conv.dest_tx_hash,
        user_bsc_address=conv.user_bsc_address,
        created_at=conv.created_at,
    )


def _actor_filter(info):
    """JWT-derived actor scoping (house rule: never client account ids)."""
    from users.jwt_context import get_jwt_business_context_with_validation
    jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
    if not jwt_context:
        return None
    if jwt_context['account_type'] == 'business' and jwt_context.get('business_id'):
        return {'actor_business_id': jwt_context['business_id'], 'actor_type': 'business'}
    return {'actor_user': info.context.user, 'actor_type': 'user'}


class StartCusdPlusConversion(graphene.Mutation):
    """Record an accepted quote. Nothing on chain yet — ABANDONED if the
    user never signs (24h sweep)."""
    class Arguments:
        direction = graphene.String(required=True)
        amount_usd = graphene.Float(required=True)
        quoted_receive_usd = graphene.Float(required=True)
        quoted_cost_pct = graphene.Float(required=True)
        user_bsc_address = graphene.String(default_value='')
        user_algo_address = graphene.String(default_value='')

    conversion = graphene.Field(CusdPlusConversionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    def mutate(self, info, direction, amount_usd, quoted_receive_usd,
               quoted_cost_pct, user_bsc_address='', user_algo_address=''):
        from .models import CusdPlusConversion
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return StartCusdPlusConversion(success=False, errors=['auth required'])
        if direction not in ('to_savings', 'from_savings'):
            return StartCusdPlusConversion(success=False, errors=['bad direction'])
        # Issuer geo-gate: entries only. from_savings must always work —
        # a user who becomes ineligible can still exit their position.
        if direction == 'to_savings':
            from .eligibility import is_ondo_eligible, INELIGIBLE_MESSAGE
            if not is_ondo_eligible(user):
                return StartCusdPlusConversion(success=False, errors=[INELIGIBLE_MESSAGE])
        if amount_usd <= 0 or quoted_receive_usd <= 0:
            return StartCusdPlusConversion(success=False, errors=['bad amount'])
        scope = _actor_filter(info)
        if scope is None:
            return StartCusdPlusConversion(success=False, errors=['no access'])

        conv = CusdPlusConversion.objects.create(
            actor_user=user if scope['actor_type'] == 'user' else None,
            actor_business_id=scope.get('actor_business_id'),
            actor_type=scope['actor_type'],
            actor_display_name=getattr(user, 'username', '') or '',
            direction=direction,
            amount_usd=amount_usd,
            quoted_receive_usd=quoted_receive_usd,
            quoted_cost_pct=quoted_cost_pct,
            user_bsc_address=user_bsc_address,
            user_algo_address=user_algo_address,
        )
        return StartCusdPlusConversion(conversion=_serialize(conv), success=True, errors=None)


class AdvanceCusdPlusConversion(graphene.Mutation):
    """Client reports a leg it signed. Transitions are monotonic and
    validated; the bridge poller independently verifies SRC_COMMITTED ->
    DEST_ARRIVED, so a lying client cannot fake delivery."""
    class Arguments:
        conversion_id = graphene.ID(required=True)
        new_status = graphene.String(required=True)
        tx_ref = graphene.String(default_value='')

    conversion = graphene.Field(CusdPlusConversionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    # Client may only claim these (poller/sweeper own the rest).
    CLIENT_STATUSES = {'SRC_COMMITTED', 'COMPLETED'}

    def mutate(self, info, conversion_id, new_status, tx_ref=''):
        from .models import CusdPlusConversion
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return AdvanceCusdPlusConversion(success=False, errors=['auth required'])
        scope = _actor_filter(info)
        if scope is None:
            return AdvanceCusdPlusConversion(success=False, errors=['no access'])
        if new_status not in AdvanceCusdPlusConversion.CLIENT_STATUSES:
            return AdvanceCusdPlusConversion(success=False, errors=['status not client-reportable'])

        lookup = {'internal_id': conversion_id, 'is_deleted': False}
        if scope['actor_type'] == 'business':
            lookup['actor_business_id'] = scope['actor_business_id']
        else:
            lookup['actor_user'] = user
        conv = CusdPlusConversion.objects.filter(**lookup).first()
        if conv is None:
            return AdvanceCusdPlusConversion(success=False, errors=['not found'])
        if not conv.can_transition(new_status):
            return AdvanceCusdPlusConversion(
                success=False, errors=[f'illegal transition {conv.status} -> {new_status}'],
            )

        conv.status = new_status
        now = timezone.now()
        update = ['status', 'updated_at']
        if new_status == 'SRC_COMMITTED':
            conv.src_tx_id = tx_ref or conv.src_tx_id
            conv.src_committed_at = now
            update += ['src_tx_id', 'src_committed_at']
        elif new_status == 'COMPLETED':
            conv.dest_tx_hash = tx_ref or conv.dest_tx_hash
            conv.completed_at = now
            update += ['dest_tx_hash', 'completed_at']
        conv.save(update_fields=update)
        return AdvanceCusdPlusConversion(conversion=_serialize(conv), success=True, errors=None)


class Mutation(graphene.ObjectType):
    start_cusd_plus_conversion = StartCusdPlusConversion.Field()
    advance_cusd_plus_conversion = AdvanceCusdPlusConversion.Field()
