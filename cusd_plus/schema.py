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

import logging

import graphene
from django.utils import timezone

logger = logging.getLogger(__name__)


class CusdPlusSummaryType(graphene.ObjectType):
    """Savings position for the active account (JWT context)."""
    balance_usd = graphene.Float(description="USD value of the position; share counts are never exposed")
    net_apy_pct = graphene.Float(description="Oracle gross minus Confío share; floats daily")
    gross_apy_pct = graphene.Float(description="USDY gross APY before Confío's share — for the transparency split (gross / fee / net)")
    earned_today_usd = graphene.Float()
    earned_month_usd = graphene.Float()
    savings_enabled = graphene.Boolean(description="Issuer geo-eligibility (Ondo) by phone country; gates ENTRY only — exits are never gated")
    stocks_enabled = graphene.Boolean(description="Server flag gating the Ondo Stocks surfaces (geofence-aware AND dark-launch flag)")
    cusd_deposits_paused = graphene.Boolean(description="cUSD phase-out: when True the app stops promoting new cUSD ramp deposits (UX steering only; the ramp stays operational)")
    usdt_balance_usd = graphene.Float(description="Raw wallet USDT-BSC (pre-mint, or held as 'Confío Dollar' by geo-ineligible users) — display-grade, cached")
    usdt_balance_wei = graphene.String(description="Same balance in exact wei (string; 18dp) for MAX-send and mint math")
    confio_balance = graphene.Float(description="BEP-20 CONFIO held by the account (token count, not USD) — display-grade; 0 until the token address is configured")


class CusdPlusMovementType(graphene.ObjectType):
    """One row of savings history — Recargar/Retirar (conversions) plus the
    money rails that settle in cUSD+/USDT (send, receive, payment, payroll).
    Yield is passive and automatic: it shows up as balance growth, never as
    a row."""
    id = graphene.ID()
    movement_type = graphene.String(
        description="deposit | withdraw | send | receive | payment | payroll")
    title = graphene.String()
    amount_usd = graphene.Float(description="Signed: inflows to savings positive")
    created_at = graphene.DateTime()
    tx_hash = graphene.String(description="BSC transaction hash, '' when the row predates hash capture")
    source_type = graphene.String(
        description="Rail that produced this row (conversion | send | payment | payroll), "
                    "null for externally-scanned inbound deposits which have no source record")
    source_id = graphene.String(description="Primary key / internal id of the source row, null when source_type is null")


# reference is written as '<rail>:<id>[:<leg>]' by the confirm tasks, or
# 'scan_cusdp:<txhash>:<logIndex>' by the inbound scanner (external deposit —
# no source row exists, so it stays unlinked). Parsing here keeps the raw
# idempotency string server-side; the client only ever sees the resolved pair.
_MOVEMENT_SOURCE_RAILS = {
    'conversion': 'conversion',
    'send_transaction': 'send',
    'payment_transaction': 'payment',
    'payroll_item': 'payroll',
}


def _movement_source(reference):
    """('conversion', '<id>') for rail rows, (None, None) for scanner rows."""
    prefix, _, rest = (reference or '').partition(':')
    rail = _MOVEMENT_SOURCE_RAILS.get(prefix)
    if rail is None or not rest:
        return None, None
    # Strip the ':out'/':in' leg suffix; ids themselves never contain ':'.
    return rail, rest.split(':', 1)[0] or None


def _movement_type(m):
    source_type, source_id = _movement_source(m.reference)
    return CusdPlusMovementType(
        id=str(m.id),
        movement_type=m.movement_type,
        title=m.title,
        amount_usd=float(m.amount_usd),
        created_at=m.created_at,
        tx_hash=m.tx_hash or '',
        source_type=source_type,
        source_id=source_id,
    )


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
    vault_address = graphene.String(description="cUSD+ vault (proxy) on BSC — client targets this for leg C (subscribeAndMint/redeem)")
    # BNB auto-convert (mis-deposited BNB → USDT, the BSC mirror of the
    # ALGO→USDC auto-swap). Wei values travel as strings: they overflow
    # GraphQL Int and Float loses integer precision.
    bnb_auto_convert_enabled = graphene.Boolean(description="Master gate for the client-signed BNB→USDT auto-convert")
    pancake_router = graphene.String(description="PancakeSwap V2 router the swap targets (also relay-allowlisted, selector-guarded)")
    bnb_auto_convert_min_swap_wei = graphene.String(description="Skip swaps smaller than this (wei, as string)")
    bnb_auto_convert_keep_wei = graphene.String(description="BNB to leave at the address (live gas-dust target, wei as string; '0' once 7702 sponsorship is on)")
    bnb_auto_convert_slippage_bps = graphene.Int(description="Slippage floor applied to the getAmountsOut quote")
    # EIP-7702 sponsored batches (successor to gas dusting): when enabled,
    # the client signs one intent per action and the sponsor pays all gas.
    sponsored_7702_enabled = graphene.Boolean(description="Master gate for sponsor-paid type-4 batches")
    batch_delegate_address = graphene.String(description="ConfioBatchDelegate the EOA designates via 7702")
    bsc_send_enabled = graphene.Boolean(description="send/bsc_flow.py master gate — full-dollar sends (cUSD+ redeemed server-side when wallet USDT doesn't cover)")


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


class GmHoldingType(graphene.ObjectType):
    """One tokenized-stock position of the JWT account. Units are fine to
    expose for stocks (market convention) — the never-expose-share-counts
    rule is specific to cUSD+ (decision A)."""
    symbol = graphene.String(description="GM token symbol, e.g. TSLAon")
    ticker = graphene.String()
    name = graphene.String()
    units = graphene.Float()
    value_usd = graphene.Float(description="units × cached GM display price — display only, never settlement")
    day_change_pct = graphene.Float()


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
    cusd_plus_movement = graphene.Field(
        CusdPlusMovementType,
        id=graphene.ID(required=True),
        description="One ledger row for the JWT account — backs the movement detail screen",
    )
    cusd_plus_convert_params = graphene.Field(CusdPlusConvertParamsType)
    cusd_plus_conversions_in_flight = graphene.List(
        graphene.NonNull(lambda: CusdPlusConversionType),
    )
    gm_market = graphene.Field(GmMarketType)
    gm_holdings = graphene.List(
        graphene.NonNull(GmHoldingType),
        description="The JWT account's tokenized-stock positions (Multicall3 universe scan — chain is the registry)",
    )
    gm_ohlc = graphene.List(
        graphene.NonNull(GmCandleType),
        symbol=graphene.String(required=True),
        range=graphene.String(default_value='3M', description="1D | 1M | 3M | 6M | 1Y | MAX"),
    )
    bsc_rpc = graphene.Field(
        lambda: BscRpcResult,
        method=graphene.String(required=True),
        params=graphene.String(required=True, description="JSON-encoded params array"),
        description="Read-only BSC RPC proxy (allowlisted methods) — keeps user IPs off public nodes",
    )

    def resolve_bsc_rpc(self, info, method, params):
        import json as _json
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return BscRpcResult(error='auth_required')
        if method not in BSC_READ_METHODS:
            return BscRpcResult(error='method_not_allowed')
        if _bsc_rate_limited(user.id, 'read', 120):
            return BscRpcResult(error='rate_limited')
        try:
            parsed = _json.loads(params)
            if not isinstance(parsed, list) or len(_json.dumps(parsed)) > 50_000:
                return BscRpcResult(error='bad_params')
        except Exception:
            return BscRpcResult(error='bad_params')
        from .tasks import _rpc
        try:
            return BscRpcResult(result=_json.dumps(_rpc(method, parsed)))
        except Exception as exc:  # noqa: BLE001
            return BscRpcResult(error=str(exc)[:200])

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
        # v2 = card-safe set (Julian, 2026-07-08): white-glyph logos sit on a
        # single dark slate chip — the version that FIXED the invisible-logo
        # problem. (v3's per-ticker colored chips read as wrong-brand and
        # were rejected.) Prefix bumps double as cache-busts.
        logos_prefix = getattr(settings, 'GM_LOGOS_S3_PREFIX', 'stock-logos/v2/')

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

    def resolve_gm_holdings(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        account = _active_account(info)
        if account is None or not account.bsc_address:
            return []
        from . import gm_api
        from .gm_holdings import holdings_units
        units_by_symbol = holdings_units(account.bsc_address)
        if units_by_symbol is None:
            # Scan failed with no last-known — unknown is NOT an empty
            # portfolio; same contract as gmMarket: client keeps its cache.
            return None
        if not units_by_symbol:
            return []
        try:
            market = gm_api.all_market()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('gm_holdings market fetch failed')
            return None
        by_symbol = {
            (item.get('primaryMarket') or {}).get('symbol'): item
            for item in market
        }
        holdings = []
        for symbol, units in units_by_symbol.items():
            item = by_symbol.get(symbol)
            pm = (item or {}).get('primaryMarket') or {}
            if pm.get('price') is None:
                # No live price (halt/delist edge) — surfacing a made-up value
                # is worse than a brief gap; ops sees the log.
                import logging
                logging.getLogger(__name__).warning('gm_holdings: no live price for %s', symbol)
                continue
            um = (item or {}).get('underlyingMarket') or {}
            ticker = um.get('ticker') or symbol.removesuffix('on')
            holdings.append(GmHoldingType(
                symbol=symbol,
                ticker=ticker,
                name=_display_name(um.get('name') or ticker),
                units=units,
                value_usd=units * float(pm['price']),
                day_change_pct=float(pm.get('priceChangePct24h') or 0),
            ))
        holdings.sort(key=lambda h: h.value_usd, reverse=True)
        return holdings

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
        from . import vault
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        eligible = is_ondo_eligible(user)
        # Real position: shares × pPlus, read live from the deployed vault
        # for the JWT account's bsc_address (0 until PP whitelisting + a
        # first mint; the ledger for earned_today/month lands with leg C).
        bsc_address = _active_bsc_address(info)
        balance_usd = vault.position_usd(bsc_address) if bsc_address else 0.0
        # Raw wallet USDT: money that landed but hasn't minted (or never will,
        # for geo-ineligible users — their "Confío Dollar"). One cached read
        # serves both fields; the client re-reads balanceOf live before any
        # exact-amount send, so 30s staleness here is display-only.
        usdt_wei_int = vault.usdt_balance_raw(bsc_address) if bsc_address else 0
        # BEP-20 CONFIO (token count) for the send screen. Never blocks the
        # summary: an RPC hiccup shows 0 here while the dollar fields keep
        # their own cache fallbacks.
        confio_wei_int = 0
        confio_token = getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', None)
        if bsc_address and confio_token:
            try:
                confio_wei_int = vault.erc20_balance_raw(confio_token, bsc_address)
            except Exception:  # noqa: BLE001
                confio_wei_int = 0
        # SERVER-DERIVED live: the oracle's on-chain daily rate compounded
        # over a year (gross) and at the vault's kept share (net) — floats
        # with US Treasuries, never hardcoded. Falls back to last-known,
        # then CUSD_PLUS_NET_APY_PCT (default 0.0) if the chain is out.
        gross_apy, net_apy = vault.apy_split()
        # "Hoy ≈": the ESTIMATED day's yield at the current balance — rate ×
        # balance, both already in hand. A rate statement, not an accounting
        # one (the app labels it ≈): it is exactly right as an estimate for
        # every flow pattern, including a mint from 5 minutes ago, which is
        # why it replaced the snapshot/cost-basis machinery (2026-07-31).
        # Inverting net APY recovers daily·kept exactly (apy_split builds
        # net = (1+daily·kept)^365−1). Honest-zero fallback: no rate or no
        # balance -> 0.0 -> the ticker line hides.
        daily_net = (1.0 + net_apy / 100.0) ** (1.0 / 365.0) - 1.0
        earned_today = balance_usd * daily_net
        return CusdPlusSummaryType(
            balance_usd=balance_usd,
            net_apy_pct=net_apy,
            gross_apy_pct=gross_apy,
            earned_today_usd=earned_today,
            # Monthly needs real history (ledger) — honest 0 until that
            # lands as a considered follow-up; the ticker renders Hoy alone.
            earned_month_usd=0.0,
            savings_enabled=eligible,
            # Dark until the demand signal (decision 2dcfada5) AND geo-eligible.
            stocks_enabled=eligible and getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False),
            cusd_deposits_paused=getattr(settings, 'CUSD_DEPOSITS_PAUSED', True),
            usdt_balance_usd=usdt_wei_int / (10 ** 18),
            usdt_balance_wei=str(usdt_wei_int),
            confio_balance=confio_wei_int / (10 ** 18),
        )

    def resolve_cusd_plus_movements(self, info, limit=20, offset=0):
        """Paginated ledger rows for the JWT account, newest first — the
        display ledger behind SavingsScreen's Movimientos (CusdPlusMovement:
        rows written by confirm tasks/scanner, idempotent on reference)."""
        from .models import CusdPlusMovement
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        account = _active_account(info)
        if account is None:
            return []
        limit = max(1, min(int(limit or 20), 100))
        offset = max(0, int(offset or 0))
        rows = CusdPlusMovement.objects.filter(account=account)[offset:offset + limit]
        return [_movement_type(m) for m in rows]

    def resolve_cusd_plus_movement(self, info, id):
        """One ledger row, scoped to the JWT account — backs the movement
        detail screen. Isolated from cusdPlusMovements on purpose: the hub's
        portfolio query must never gain fields that would fail it wholesale
        against a server that predates them."""
        from .models import CusdPlusMovement
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        account = _active_account(info)
        if account is None:
            return None
        m = CusdPlusMovement.objects.filter(account=account, id=id).first()
        return _movement_type(m) if m is not None else None

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
        # Live gas reserve (gas-price aware, RPC-failure safe internally):
        # when 7702 is off, the auto-convert leaves this much BNB behind so
        # the user's next SELF-SIGNED leg has gas (user-funded; the dust
        # rail was removed 2026-07-30).
        from .tasks import _bnb_gas_reserve_wei as _live_gas_reserve_wei
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
            vault_address=getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', None),
            bnb_auto_convert_enabled=getattr(settings, 'CUSD_PLUS_BNB_AUTOCONVERT_ENABLED', False),
            pancake_router=getattr(settings, 'CUSD_PLUS_PANCAKE_ROUTER', None),
            bnb_auto_convert_min_swap_wei=str(getattr(
                settings, 'CUSD_PLUS_BNB_AUTOCONVERT_MIN_SWAP_WEI', 3_000_000_000_000_000)),
            # Under 7702 sponsorship no BNB is needed at the user address —
            # the auto-convert can sweep everything.
            bnb_auto_convert_keep_wei=(
                '0' if getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
                else str(_live_gas_reserve_wei())),
            bnb_auto_convert_slippage_bps=getattr(
                settings, 'CUSD_PLUS_BNB_AUTOCONVERT_SLIPPAGE_BPS', 100),
            sponsored_7702_enabled=getattr(settings, 'CUSD_PLUS_7702_ENABLED', False),
            batch_delegate_address=getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', None) or None,
            bsc_send_enabled=getattr(settings, 'BSC_SEND_ENABLED', False),
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


def _active_account(info):
    """Resolve the JWT account row (never a client-supplied id)."""
    from users.jwt_context import get_jwt_business_context_with_validation
    from users.models import Account
    ctx = get_jwt_business_context_with_validation(info, required_permission=None)
    if not ctx:
        return None
    idx = ctx.get('account_index', 0)
    if ctx['account_type'] == 'business' and ctx.get('business_id'):
        return Account.objects.filter(
            business_id=ctx['business_id'], account_type='business', account_index=idx,
        ).first()
    return Account.objects.filter(
        user=info.context.user, account_type='personal', account_index=idx,
    ).first()


def _active_bsc_address(info):
    """Resolve the JWT account's bsc_address (never a client-supplied id)."""
    acc = _active_account(info)
    return (acc.bsc_address or None) if acc else None


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
        from .unified import sync_unified_from_cusd_plus_conversion
        sync_unified_from_cusd_plus_conversion(conv)
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
            # Balance just changed on chain — drop the fresh-read cache so
            # the next summary shows the new position, not a 30s-old one.
            from . import vault
            vault.invalidate_position(conv.user_bsc_address)
            # Display-ledger row (Movimientos). Idempotent on the
            # conversion reference: replays/retries of this mutation can
            # never duplicate. Signed amounts: into savings positive.
            try:
                from users.models import Account
                from .models import CusdPlusMovement
                account = Account.objects.filter(
                    bsc_address__iexact=conv.user_bsc_address,
                    deleted_at__isnull=True,
                ).first()
                if account is not None:
                    into_savings = conv.direction == 'to_savings'
                    CusdPlusMovement.objects.get_or_create(
                        reference=f'conversion:{conv.internal_id}',
                        defaults={
                            'account': account,
                            'movement_type': 'deposit' if into_savings else 'withdraw',
                            'title': 'Ahorraste' if into_savings else 'Retiraste',
                            'amount_usd': (conv.quoted_receive_usd
                                           if into_savings else -conv.quoted_receive_usd),
                            'tx_hash': conv.dest_tx_hash or '',
                        },
                    )
            except Exception:  # noqa: BLE001 — ledger must not fail the mint report
                import logging
                logging.getLogger(__name__).exception(
                    'movement write failed for conversion %s', conv.internal_id)
        conv.save(update_fields=update)
        from .unified import sync_unified_from_cusd_plus_conversion
        sync_unified_from_cusd_plus_conversion(conv)
        return AdvanceCusdPlusConversion(conversion=_serialize(conv), success=True, errors=None)


# ── BSC relay: client signs, SERVER injects (cUSD parity) ───────────────
# The RN client never talks to a public BSC RPC: reads go through bscRpc
# (allowlisted methods) and signed transactions through SubmitBscTransaction
# (decoded + destination-allowlisted). User IPs stay off third-party nodes,
# the server sees submissions the moment they happen, and retry/gas-bump
# logic can live in one place. Custody unchanged: the server only relays
# bytes the user already signed.

BSC_READ_METHODS = {
    'eth_getTransactionCount', 'eth_gasPrice', 'eth_estimateGas',
    'eth_call', 'eth_getBalance', 'eth_getTransactionReceipt',
    'eth_blockNumber', 'eth_chainId',
    # 7702 delegation probe (is the EOA already designating our delegate?)
    'eth_getCode',
}


def _bsc_rate_limited(user_id, kind: str, per_minute: int) -> bool:
    from django.core.cache import cache
    key = f'bsc_relay_{kind}_{user_id}'
    count = cache.get(key, 0)
    if count >= per_minute:
        return True
    cache.set(key, count + 1, 60)
    return False


class BscRpcResult(graphene.ObjectType):
    result = graphene.String(description="JSON-encoded RPC result")
    error = graphene.String()


# Shared with the 7702 batch policy — one implementation of the Guardarian
# lookup and the redeem-recipient rule for BOTH rails (parity is structural,
# not copied). Kept importable under the old name for existing tests.
from .sponsor_7702 import (  # noqa: E402
    SEL_SUBSCRIBE_AND_MINT as _SEL_SUBSCRIBE_AND_MINT,
    _guardarian_savings_deposit_address,
    redeem_recipient_allowed as _redeem_recipient_allowed,
)


class SubmitBscTransaction(graphene.Mutation):
    """Relay a CLIENT-SIGNED BSC transaction to the node (the EVM analogue
    of submitSponsoredGroup). Decodes the raw tx and only relays legacy
    EIP-155 txns on our chain whose `to` is an allowlisted Confío-flow
    contract — the relay can't be used as an open broadcast proxy."""
    class Arguments:
        raw_tx = graphene.String(required=True)

    success = graphene.Boolean()
    tx_hash = graphene.String()
    error = graphene.String()

    def mutate(self, info, raw_tx):
        from django.conf import settings
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return SubmitBscTransaction(success=False, error='auth_required')
        if _bsc_rate_limited(user.id, 'submit', 10):
            return SubmitBscTransaction(success=False, error='rate_limited')

        raw = (raw_tx or '').strip()
        if not raw.startswith('0x') or len(raw) > 100_000:
            return SubmitBscTransaction(success=False, error='bad_raw_tx')

        # Decode: legacy tx = rlp[nonce, gasPrice, gas, to, value, data, v, r, s]
        try:
            import rlp
            fields = rlp.decode(bytes.fromhex(raw[2:]))
            if len(fields) != 9:
                return SubmitBscTransaction(success=False, error='not_legacy_tx')
            to_addr = '0x' + fields[3].hex().lower()
            v = int.from_bytes(fields[6], 'big')
            chain_id = (v - 35) // 2
        except Exception:
            return SubmitBscTransaction(success=False, error='undecodable_tx')

        if chain_id != int(getattr(settings, 'BSC_CHAIN_ID', 56)):
            return SubmitBscTransaction(success=False, error='wrong_chain')
        allowed = {
            (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower(),
            '0x55d398326f99059ff775485246999027b3197955',  # USDT (approve leg)
        }
        allowed |= {a.lower() for a in getattr(settings, 'BSC_RELAY_EXTRA_ALLOWED', [])}

        # PancakeSwap router: relayable ONLY for the BNB→USDT auto-convert
        # (swapExactETHForTokens), never as a general swap venue — a selector
        # guard, unlike the destination-only checks above, because the router
        # exposes arbitrary token swaps we don't want this relay to carry.
        router = (getattr(settings, 'CUSD_PLUS_PANCAKE_ROUTER', '') or '').lower()
        SWAP_EXACT_ETH_FOR_TOKENS = '7ff36ab5'  # swapExactETHForTokens(uint256,address[],address,uint256)
        is_autoconvert = False
        if router and to_addr == router:
            if not getattr(settings, 'CUSD_PLUS_BNB_AUTOCONVERT_ENABLED', False):
                return SubmitBscTransaction(success=False, error='destination_not_allowed')
            data_hex = fields[5].hex()
            if not data_hex.startswith(SWAP_EXACT_ETH_FOR_TOKENS):
                return SubmitBscTransaction(success=False, error='selector_not_allowed')
            is_autoconvert = True
        elif to_addr not in allowed:
            return SubmitBscTransaction(success=False, error='destination_not_allowed')

        # redeemToUsdt recipient guard: the vault pays out to whatever address
        # sits in calldata, so a tampered client could redirect a redeem the
        # user is biometrically approving. Relay it only when the recipient is
        # the signer's own address (self-redeem) or the user's LIVE Guardarian
        # sell deposit address, re-fetched server-side — mirror of the
        # Algorand rails where the destination never exists client-side.
        vault_addr = (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
        REDEEM_TO_USDT_SELECTOR = 'f4794519'  # redeemToUsdt(uint256,uint256,address)
        if vault_addr and to_addr == vault_addr:
            data_hex = fields[5].hex()
            if data_hex.startswith(REDEEM_TO_USDT_SELECTOR):
                if len(data_hex) < 8 + 192:
                    return SubmitBscTransaction(success=False, error='bad_redeem_calldata')
                recipient = '0x' + data_hex[8 + 128:8 + 192][-40:].lower()
                try:
                    from eth_account import Account as _EthAccount
                    signer = _EthAccount.recover_transaction(raw).lower()
                except Exception:
                    return SubmitBscTransaction(success=False, error='unrecoverable_signer')
                if not _redeem_recipient_allowed(user, recipient, signer):
                    logger.warning(
                        'redeemToUsdt recipient %s rejected for user %s (signer %s)',
                        recipient, user.id, signer,
                    )
                    return SubmitBscTransaction(success=False, error='redeem_recipient_not_allowed')
            # Mint geo-gate (2026-07-30): since ramps deliver raw USDT to
            # everyone, THIS is where geo-eligibility is enforced — phone
            # country + Cloudflare IP country. Mint only; redeem above and
            # raw USDT transfers stay ungated (exits are never gated).
            if data_hex.startswith(_SEL_SUBSCRIBE_AND_MINT):
                from .eligibility import check_savings_mint_eligibility
                if not check_savings_mint_eligibility(user, getattr(info.context, 'META', {})):
                    return SubmitBscTransaction(success=False, error='mint_not_available')

        from .tasks import _rpc
        try:
            tx_hash = _rpc('eth_sendRawTransaction', [raw])
            if is_autoconvert:
                # Ledger row = this outbound BNB is a Confío-recorded convert.
                # Outbound native transfers absent from this table are dust
                # extraction and disqualify the user from further subsidies.
                from .models import BnbAutoConvert
                try:
                    BnbAutoConvert.objects.create(
                        user=user,
                        value_wei=str(int.from_bytes(fields[4], 'big')),
                        tx_hash=tx_hash or '',
                    )
                except Exception:  # noqa: BLE001 — ledger write must not fail the relay
                    logger.exception('BnbAutoConvert ledger write failed for %s', tx_hash)
            # Balance caches (vault position + wallet USDT) just changed for
            # vault/USDT-touching relays — drop the fresh-read keys so the
            # next summary re-reads the chain instead of showing a 30s-stale
            # figure right after a send.
            try:
                from . import vault as _vault
                _addr = _active_bsc_address(info)
                if _addr:
                    _vault.invalidate_position(_addr)
            except Exception:  # noqa: BLE001 — cache hygiene must not fail the relay
                pass
            return SubmitBscTransaction(success=True, tx_hash=tx_hash)
        except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
            return SubmitBscTransaction(success=False, error=str(exc)[:200])


class BscCallInput(graphene.InputObjectType):
    """One call of a 7702 sponsored batch."""
    to = graphene.String(required=True)
    value_wei = graphene.String(required=True, description="Must be '0' under current policy")
    data = graphene.String(required=True, description="0x-prefixed calldata")


class BscAuthorizationInput(graphene.InputObjectType):
    """A signed EIP-7702 authorization tuple (client-signed, first use only)."""
    chain_id = graphene.Int(required=True)
    address = graphene.String(required=True, description="The delegate contract being designated")
    nonce = graphene.String(required=True, description="The EOA's account nonce at signing")
    y_parity = graphene.Int(required=True)
    r = graphene.String(required=True)
    s = graphene.String(required=True)


class SponsorBscBatch(graphene.Mutation):
    """Execute a user-signed call batch as a SPONSOR-PAID type-4 (EIP-7702)
    transaction — the successor to gas dusting. The client signs an EIP-712
    intent over the exact calls (and, on first use, a 7702 authorization
    designating ConfioBatchDelegate at its EOA); the server validates both
    against the vault-flow policy, simulates, and broadcasts from the KMS
    sponsor. The user's address never needs BNB. Custody unchanged: the
    delegate on-chain re-verifies the user's signature, so the sponsor can
    only execute what the user signed."""
    class Arguments:
        calls = graphene.List(graphene.NonNull(BscCallInput), required=True)
        nonce = graphene.String(required=True, description="Delegate intent nonce (nonces())")
        deadline = graphene.String(required=True, description="Unix seconds")
        intent_signature = graphene.String(required=True, description="65-byte r‖s‖v hex")
        authorization = BscAuthorizationInput(required=False)

    success = graphene.Boolean()
    tx_hash = graphene.String()
    authorization_required = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, calls, nonce, deadline, intent_signature, authorization=None):
        import time as _time

        from django.conf import settings
        from django.core.cache import cache

        from . import sponsor_7702

        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return SponsorBscBatch(success=False, error='auth_required')
        if not getattr(settings, 'CUSD_PLUS_7702_ENABLED', False):
            return SponsorBscBatch(success=False, error='disabled')
        if not sponsor_7702.delegate_address():
            return SponsorBscBatch(success=False, error='delegate_not_configured')
        if _bsc_rate_limited(user.id, 'sponsor7702', 5):
            return SponsorBscBatch(success=False, error='rate_limited')

        # JWT-bound address: the intent must be signed by THIS account's
        # registered BSC key — never a client-supplied address.
        user_addr = _active_bsc_address(info)
        if not user_addr:
            return SponsorBscBatch(success=False, error='no_bsc_address')
        user_addr = user_addr.lower()

        # Per-address cooldown + daily cap (dust-rail discipline).
        rl_key = f'cusd_plus_7702_cooldown_{user_addr}'
        if cache.get(rl_key):
            return SponsorBscBatch(success=False, error='rate_limited')
        day_key = f'cusd_plus_7702_day_{user_addr}'
        day_count = cache.get(day_key, 0)
        if day_count >= int(getattr(settings, 'CUSD_PLUS_7702_MAX_PER_DAY', 20)):
            logger.warning('7702 daily cap hit for %s', user_addr)
            return SponsorBscBatch(success=False, error='daily_cap')

        # Normalize + structural caps.
        if not calls or len(calls) > 4:
            return SponsorBscBatch(success=False, error='bad_batch_size')
        try:
            norm_calls = [{
                'to': (c.to or '').lower(),
                'value': str(int(c.value_wei)),
                'data': (c.data or '').lower(),
            } for c in calls]
            nonce_i = int(nonce)
            deadline_i = int(deadline)
        except (TypeError, ValueError):
            return SponsorBscBatch(success=False, error='bad_params')

        now = int(_time.time())
        if not (now + 60 <= deadline_i <= now + 1800):
            return SponsorBscBatch(success=False, error='bad_deadline')

        # Mint geo-gate (2026-07-30): ramps deliver raw USDT to everyone, so
        # geo-eligibility (phone + Cloudflare IP country) is enforced HERE on
        # any batch carrying a vault subscribeAndMint. Lives outside
        # validate_policy on purpose — the policy is a pure calldata check
        # (tests call it directly) and has no request context. Redeems and
        # approvals pass untouched: exits are never gated.
        vault_l = (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
        if any(
            c['to'] == vault_l and c['data'][2:10] == _SEL_SUBSCRIBE_AND_MINT
            for c in norm_calls
        ):
            from .eligibility import check_savings_mint_eligibility
            if not check_savings_mint_eligibility(user, getattr(info.context, 'META', {})):
                return SponsorBscBatch(success=False, error='mint_not_available')

        chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
        try:
            sponsor_7702.validate_policy(norm_calls, user, user_addr)

            # The generic savings rail's kind (and thus the intentId the user
            # signed) is derived from the selectors; the client derives the
            # SAME value. source_id is omitted (no domain row here).
            kind = 'redeem' if any(
                c['data'][2:10] == sponsor_7702.SEL_REDEEM_TO_USDT for c in norm_calls
            ) else 'subscribe'
            intent_id = sponsor_7702.intent_id_for(kind)
            digest = sponsor_7702.intent_digest(
                norm_calls, nonce_i, deadline_i, user_addr, chain_id, intent_id)
            signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
            if signer != user_addr:
                return SponsorBscBatch(success=False, error='bad_intent_signature')

            # Delegation state decides whether an authorization must ride
            # along. The server's view is authoritative — the client's
            # eth_getCode probe is advisory only.
            auth_dict = None
            if not sponsor_7702.is_delegated(user_addr):
                if authorization is None:
                    return SponsorBscBatch(
                        success=False, authorization_required=True,
                        error='authorization_required')
                def _hex(x):
                    x = (x or '').lower()
                    return x if x.startswith('0x') else '0x' + x
                auth_dict = {
                    'chain_id': int(authorization.chain_id),
                    'address': (authorization.address or '').lower(),
                    'nonce': str(int(authorization.nonce)),
                    'y_parity': int(authorization.y_parity),
                    'r': _hex(authorization.r),
                    's': _hex(authorization.s),
                }
                # chainId 0 would be a wildcard valid on EVERY chain —
                # refuse it even though the tuple is user-signed.
                if auth_dict['chain_id'] != chain_id:
                    return SponsorBscBatch(success=False, error='bad_auth_chain')
                if auth_dict['address'] != sponsor_7702.delegate_address():
                    return SponsorBscBatch(success=False, error='bad_auth_delegate')
                authority = sponsor_7702.recover_authorization_authority(auth_dict)
                if authority != user_addr:
                    return SponsorBscBatch(success=False, error='bad_auth_signature')
                live_nonce = int(sponsor_7702._rpc(
                    'eth_getTransactionCount', [user_addr, 'pending']), 16)
                if int(auth_dict['nonce']) != live_nonce:
                    # Signed against a stale account nonce (a legacy tx or
                    # emergency exit landed since) — applying it would
                    # silently no-op. Client refetches and re-signs.
                    return SponsorBscBatch(
                        success=False, authorization_required=True,
                        error='stale_auth_nonce')

            tx_hash, _batch = sponsor_7702.send_sponsored_batch(
                user, user_addr, norm_calls, nonce_i, deadline_i,
                intent_signature, auth_dict, kind)
        except sponsor_7702.PolicyError as exc:
            return SponsorBscBatch(success=False, error=exc.code)
        except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
            logger.exception('7702 sponsored batch failed for user %s', user.id)
            return SponsorBscBatch(success=False, error=str(exc)[:200])

        cache.set(rl_key, 1, 30)  # 30s per-address cooldown
        cache.set(day_key, day_count + 1, 24 * 3600)
        return SponsorBscBatch(success=True, tx_hash=tx_hash)


class RegisterBscUsdtArrival(graphene.Mutation):
    """Foreground fast-path for monitor_bridge_arrivals: record a specific
    tx's USDT arrival NOW instead of waiting for the next beat scan.

    The BNB auto-convert calls this right after its swap receipt so the
    whole BNB→USDT→cUSD+ chain finishes in ONE foreground session (the
    Algorand auto-swap's one-shot UX, minus EVM's missing atomicity):
    swap → this mutation → resumeSavingsMints picks up the fresh row.

    Grants no new capability: it parses the SAME chain truth with the SAME
    guards (registered addresses, deposit floor, in-flight protection) into
    the SAME idempotent recorder the beat scanner uses — only sooner. If it
    fails, the beat scan records the arrival minutes later as before.
    """
    class Arguments:
        tx_hash = graphene.String(required=True)

    success = graphene.Boolean()
    recorded = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, tx_hash):
        import re
        from decimal import Decimal, ROUND_DOWN

        from django.conf import settings

        from .models import CusdPlusConversion
        from .tasks import (
            _rpc, _registered_bsc_addresses, _record_inbound_deposit,
            USDT_BSC, TRANSFER_TOPIC,
        )

        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return RegisterBscUsdtArrival(success=False, error='auth_required')
        if _bsc_rate_limited(user.id, 'register_arrival', 6):
            return RegisterBscUsdtArrival(success=False, error='rate_limited')
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}', (tx_hash or '').strip()):
            return RegisterBscUsdtArrival(success=False, error='bad_tx_hash')
        tx_hash = tx_hash.strip().lower()

        try:
            receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
        except Exception as exc:  # noqa: BLE001
            return RegisterBscUsdtArrival(success=False, error=str(exc)[:200])
        if not receipt:
            return RegisterBscUsdtArrival(success=False, error='not_mined')
        if receipt.get('status') != '0x1':
            return RegisterBscUsdtArrival(success=False, error='tx_reverted')

        registered = _registered_bsc_addresses()
        # Mirror the beat scanner's in-flight protection: while a bridge
        # delivery is awaited at an address, foreground recording could
        # consume USDT a delayed delivery still needs — leave to the beat.
        awaited = set(CusdPlusConversion.objects.filter(
            direction='to_savings',
            status__in=('SRC_COMMITTED', 'STUCK'),
            is_deleted=False,
        ).exclude(user_bsc_address='').values_list('user_bsc_address', flat=True))
        awaited = {a.lower() for a in awaited}

        min_deposit = Decimal(str(getattr(settings, 'CUSD_PLUS_MIN_EXTERNAL_DEPOSIT_USD', 1)))
        now = timezone.now()
        recorded = False
        for log in receipt.get('logs', []):
            if (log.get('address') or '').lower() != USDT_BSC.lower():
                continue
            topics = log.get('topics') or []
            if len(topics) < 3 or topics[0] != TRANSFER_TOPIC:
                continue
            to_addr = ('0x' + topics[2][-40:]).lower()
            account_id = registered.get(to_addr)
            if account_id is None or to_addr in awaited:
                continue
            amount_usd = (Decimal(int(log['data'], 16)) / Decimal(10 ** 18)).quantize(
                Decimal('0.000001'), rounding=ROUND_DOWN)
            if amount_usd < min_deposit:
                continue
            _record_inbound_deposit(
                account_id=account_id,
                to_addr=to_addr,
                amount_usd=amount_usd,
                tx_ref=f"{tx_hash}:{int(log.get('logIndex', '0x0'), 16)}",
                tx_hash=tx_hash,
                source='external_deposit',
                now=now,
            )
            recorded = True
        return RegisterBscUsdtArrival(success=True, recorded=recorded)


class Mutation(graphene.ObjectType):
    start_cusd_plus_conversion = StartCusdPlusConversion.Field()
    advance_cusd_plus_conversion = AdvanceCusdPlusConversion.Field()
    submit_bsc_transaction = SubmitBscTransaction.Field()
    register_bsc_usdt_arrival = RegisterBscUsdtArrival.Field()
    sponsor_bsc_batch = SponsorBscBatch.Field()
