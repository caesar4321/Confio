# Confío Dollar+ (cUSD+) — GraphQL seam for the savings product.
#
# STATUS: live cUSD+ and Ondo Stocks query/mutation seam. Execution remains
# operationally fail-closed behind deployment/configuration flags; the schema
# itself is shared by the Daphne API and the mobile client.
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
import re
import secrets
from decimal import Decimal, InvalidOperation, ROUND_DOWN

import graphene
from django.utils import timezone

logger = logging.getLogger(__name__)

_GM_SYMBOL_RE = re.compile(r'^[A-Za-z0-9]{1,24}$')
_GM_ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
_GM_BYTES32_RE = re.compile(r'^0x[0-9a-fA-F]{64}$')
_SPONSOR_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9_-]{16,80}$')


def _stock_execution_ready():
    """Return True only when every server-controlled execution rail is wired."""
    from django.conf import settings

    return bool(
        getattr(settings, 'CUSD_PLUS_STOCK_TRADING_ENABLED', False)
        and getattr(settings, 'CUSD_PLUS_STOCK_ROUTER_ADDRESS', '')
        and getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
        and getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', '')
        and getattr(settings, 'CUSD_PLUS_GM_TRADE_FEE_BPS', 30) == 30
    )


def _stock_surfaces_enabled(user, request_meta) -> bool:
    """Issuer eligibility plus the global discovery kill switch."""
    from django.conf import settings

    return bool(
        getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False)
        and _stock_issuer_eligible(user, request_meta)
    )


def _stock_issuer_eligible(user, request_meta) -> bool:
    """Ondo's acquisition/redemption policy, independent of UI switches."""
    from .eligibility import ONDO_POLICY

    return ONDO_POLICY.evaluate(user, request_meta or {}).allowed


def _stock_buy_enabled(user, request_meta) -> bool:
    """All visibility and country policy gates for a new stock purchase."""
    from .eligibility import check_stock_buy_eligibility

    return (
        _stock_surfaces_enabled(user, request_meta)
        and check_stock_buy_eligibility(user, request_meta)
    )


def _acquire_gm_quote_lock(cache, lock_key, timeout=30):
    """Acquire an owner-safe quote lock and return its release callback.

    Production uses django-redis' token-owned Lua lock. LocMemCache has no
    distributed lock API, so tests/local development use a unique cache token
    and only remove the key while they still own it.
    """
    if hasattr(cache, 'lock'):
        lock = cache.lock(lock_key, timeout=timeout, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            return None

        def release():
            try:
                lock.release()
            except Exception:  # expired/reacquired locks are not ours to delete
                logger.warning('GM quote lock expired before release: %s', lock_key)

        return release

    token = secrets.token_urlsafe(24)
    if not cache.add(lock_key, token, timeout):
        return None

    def release():
        if cache.get(lock_key) == token:
            cache.delete(lock_key)

    return release


def _validated_gm_trade_request(symbol, side, notional_value, duration):
    from django.conf import settings

    symbol = (symbol or '').strip()
    side = (side or '').strip().lower()
    duration = (duration or '').strip().lower()
    if not _GM_SYMBOL_RE.fullmatch(symbol):
        raise ValueError('BAD_SYMBOL')
    if side not in ('buy', 'sell'):
        raise ValueError('BAD_SIDE')
    if duration not in ('short', 'long'):
        raise ValueError('BAD_DURATION')
    try:
        amount = Decimal(str(notional_value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('BAD_NOTIONAL') from exc
    if not amount.is_finite() or amount < Decimal('1'):
        raise ValueError('BAD_NOTIONAL')
    if amount > Decimal(str(getattr(settings, 'CUSD_PLUS_GM_MAX_TRADE_USD', 100_000))):
        raise ValueError('TRADE_TOO_LARGE')
    amount = amount.quantize(Decimal('0.000000000000000001'), rounding=ROUND_DOWN)
    return {
        'symbol': symbol,
        'side': side,
        'notional_value': format(amount, 'f'),
        'duration': duration,
    }


def _normalize_gm_quote(data, request, *, binding):
    from . import gm_api

    chain_id = str(data.get('chainId') or '')
    # Ondo documents this as the strings "0"/"1", but accepting the JSON
    # number 0 as an equivalent response avoids treating a valid buy as
    # missing merely because an upstream serializer changed representation.
    side_value = data.get('side')
    side = '' if side_value is None else str(side_value)
    asset = str(data.get('assetAddress') or '')
    quantity = int(data.get('tokenAmount') or 0)
    price = int(data.get('price') or 0)
    notional_wei = int(Decimal(request['notional_value']) * Decimal(10 ** 18))
    quote_cost = quantity * price // 10 ** 18
    if chain_id != '56' or side != ('0' if request['side'] == 'buy' else '1'):
        raise gm_api.GmApiError('BAD_ONDO_RESPONSE', 'Ondo returned a mismatched chain or side', 502)
    if str(data.get('symbol') or '') != request['symbol'] or not _GM_ADDRESS_RE.fullmatch(asset):
        raise gm_api.GmApiError('BAD_ONDO_RESPONSE', 'Ondo returned a mismatched asset', 502)
    # Ondo may round the signed token quantity a few wei above or below the
    # requested notional. Mirror the router's one-micro-USDT tolerance in
    # either direction, and settle at no less than the signed quote cost.
    if quantity <= 0 or price <= 0 or abs(notional_wei - quote_cost) > 10 ** 12:
        raise gm_api.GmApiError('BAD_ONDO_RESPONSE', 'Ondo returned inconsistent quote arithmetic', 502)
    notional_wei = max(notional_wei, quote_cost)

    result = {
        'success': True,
        'chain_id': chain_id,
        'symbol': request['symbol'],
        'ticker': str(data.get('ticker') or ''),
        'asset_address': asset,
        'side': side,
        'token_amount': str(quantity),
        'price': str(price),
        'notional_wei': str(notional_wei),
    }
    if binding:
        attestation_id = int(data.get('attestationId') or 0)
        expiration = int(data.get('expiration') or 0)
        user_id = str(data.get('userId') or '')
        signature = gm_api.decode_attestation_bytes(str(data.get('signature') or ''))
        additional = gm_api.decode_attestation_bytes(str(data.get('additionalData') or ''), size=32)
        if attestation_id <= 0 or expiration <= int(timezone.now().timestamp()):
            raise gm_api.GmApiError('BAD_ONDO_RESPONSE', 'Ondo returned an expired attestation', 502)
        if not _GM_BYTES32_RE.fullmatch(user_id) or len(bytes.fromhex(signature[2:])) != 65:
            raise gm_api.GmApiError('BAD_ONDO_RESPONSE', 'Ondo returned malformed authentication fields', 502)
        result.update({
            'attestation_id': str(attestation_id),
            'user_id': user_id,
            'expiration': float(expiration),
            'signature_hex': signature,
            'additional_data_hex': additional,
        })
    return result


def _gm_quote_error(exc):
    from .gm_api import GmApiError

    if isinstance(exc, GmApiError):
        logger.warning('Ondo GM quote rejected: %s', exc)
        return GmTradeQuoteType(success=False, error_code=exc.code, error_message=exc.message)
    code = str(exc) if isinstance(exc, ValueError) else 'QUOTE_UNAVAILABLE'
    if not isinstance(exc, ValueError):
        logger.exception('Ondo GM quote failed')
    return GmTradeQuoteType(success=False, error_code=code[:80], error_message='Quote unavailable')


def _sweepable_usdt_wei(user, bsc_address) -> int:
    """Exact sweepable amount for the summary, in BSC-USDT wei.

    Any failure degrades to 0 — mint NOTHING. The alternative is falling back
    to the displayed balance, which is exactly the stale/over-committed figure
    this field exists to replace.
    """
    if not bsc_address:
        return 0
    try:
        from . import vault as _v
        return _v.sweepable_usdt_wei(user, bsc_address)
    except Exception:  # noqa: BLE001
        logger.warning('sweepable usdt unavailable for %s — reporting 0', bsc_address)
        return 0


def _sweepable_usdt_usd(user, bsc_address) -> float:
    """Display-only compatibility projection of the exact wei amount."""
    return _sweepable_usdt_wei(user, bsc_address) / (10 ** 18)


class CusdPlusSummaryType(graphene.ObjectType):
    """Savings position for the active account (JWT context)."""
    balance_usd = graphene.Float(description="USD value of the position; share counts are never exposed")
    net_apy_pct = graphene.Float(description="Oracle gross minus Confío share; floats daily")
    gross_apy_pct = graphene.Float(description="USDY gross APY before Confío's share — for the transparency split (gross / fee / net)")
    earned_today_usd = graphene.Float()
    earned_month_usd = graphene.Float()
    sweepable_usdt_usd = graphene.Float(
        description='Raw USDT that may be auto-minted: a FRESH balance minus everything already committed (prepared sends, in-flight off-ramps, in-flight sagas). The client mints this, never the displayed balance.')
    sweepable_usdt_wei = graphene.String(
        description='Exact auto-mintable raw USDT in 18-decimal base units. Money-moving clients must use this string, never the Float projection.')
    savings_enabled = graphene.Boolean(description="Issuer geo-eligibility (Ondo): phone country AND request IP country, the same full set the mint gate enforces. Gates ENTRY only — exits are never gated")
    stocks_enabled = graphene.Boolean(description="Server flag gating the Ondo Stocks surfaces (geofence-aware AND dark-launch flag)")
    stocks_trading_enabled = graphene.Boolean(description="Binding GM attestations and router settlement are enabled")
    stocks_buy_enabled = graphene.Boolean(description="Trading is enabled and this request is Ondo-entry eligible")
    cusd_deposits_paused = graphene.Boolean(description="cUSD phase-out: when True the app stops promoting new cUSD ramp deposits (UX steering only; the ramp stays operational)")
    usdt_balance_usd = graphene.Float(description="Raw wallet USDT-BSC (pre-mint, or held as 'Confío Dollar' by geo-ineligible users) — display-grade, cached")
    usdt_balance_wei = graphene.String(description="Same balance in exact wei (string; 18dp) for MAX-send and mint math")
    confio_balance = graphene.Float(description="BEP-20 CONFIO held by the account (token count, not USD) — display-grade; 0 until the token address is configured")







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
    stock_router_address = graphene.String(description="Standalone ConfioStockRouter on BSC; null until deployed")
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


class GmTradeQuoteType(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error_code = graphene.String()
    error_message = graphene.String()
    attestation_id = graphene.String()
    user_id = graphene.String()
    chain_id = graphene.String()
    symbol = graphene.String()
    ticker = graphene.String()
    asset_address = graphene.String()
    side = graphene.String()
    token_amount = graphene.String()
    price = graphene.String()
    expiration = graphene.Float()
    signature_hex = graphene.String()
    additional_data_hex = graphene.String()
    notional_wei = graphene.String(description="Exact USDT notional supplied to GM and the router")


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


class GmCommunityAssetType(graphene.ObjectType):
    """Privacy-safe aggregate position. Wallets and per-asset holder counts
    stay on the staff dashboard, not in the client API."""
    symbol = graphene.String(required=True)
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    value_usd = graphene.Float(required=True)
    share_pct = graphene.Float(required=True)


class GmCommunityType(graphene.ObjectType):
    value_usd = graphene.Float(required=True)
    holder_wallets = graphene.Int(required=True)
    positions = graphene.Int(required=True)
    as_of_block = graphene.Int()
    updated_at = graphene.DateTime(required=True)
    assets = graphene.NonNull(
        graphene.List(graphene.NonNull(GmCommunityAssetType))
    )


GM_COMMUNITY_MIN_ASSET_HOLDERS = 3


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
    cusd_plus_convert_params = graphene.Field(CusdPlusConvertParamsType)
    stock_wallet_address = graphene.String(
        description="Active JWT account's BSC address for an explicit self-verification link",
    )
    cusd_plus_conversions_in_flight = graphene.List(
        graphene.NonNull(lambda: CusdPlusConversionType),
    )
    gm_market = graphene.Field(GmMarketType)
    gm_community = graphene.Field(
        GmCommunityType,
        description="Marked-to-market aggregate holdings for eligible users; never settlement volume",
    )
    gm_soft_quote = graphene.Field(
        GmTradeQuoteType,
        symbol=graphene.String(required=True),
        side=graphene.String(required=True),
        notional_value=graphene.String(required=True),
        duration=graphene.String(default_value='short'),
    )
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

    def resolve_stock_wallet_address(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        from users.jwt_context import get_jwt_business_context_with_validation
        ctx = get_jwt_business_context_with_validation(
            info, required_permission=None)
        if not ctx:
            return None
        if ctx.get('account_type') == 'business':
            # AccountDetailScreen enforces the same privacy boundary. Viewing
            # a balance does not automatically grant permission to reveal the
            # business's public address and its full on-chain history.
            if not get_jwt_business_context_with_validation(
                    info, required_permission='view_business_address'):
                return None
        return _active_bsc_address(info)

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

    def resolve_gm_community(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        if not _stock_surfaces_enabled(user, getattr(info.context, 'META', {})):
            return None
        from django.utils.dateparse import parse_datetime
        from . import gm_tvl

        snapshot = gm_tvl.snapshot()
        if snapshot is None:
            return None
        updated_at = parse_datetime(snapshot.get('updated_at', ''))
        if updated_at is None:
            # A malformed/legacy cache entry is unknown, not a fresh zero.
            return None
        # Do not turn an aggregate into a single-wallet position disclosure
        # while adoption is still small. Staff retain the full breakdown in
        # the admin dashboard; the public list begins at three holder wallets.
        public_assets = (
            asset for asset in snapshot.get('assets', [])
            if int(asset.get('holders', 0)) >= GM_COMMUNITY_MIN_ASSET_HOLDERS
        )
        assets = [
            {
                'symbol': asset['symbol'],
                'ticker': asset['ticker'],
                'name': _display_name(asset.get('name') or asset['ticker']),
                'value_usd': float(asset['value_usd']),
                'share_pct': float(asset['share_pct']),
            }
            for asset in list(public_assets)[:10]
        ]
        return GmCommunityType(
            value_usd=float(snapshot['value_usd']),
            holder_wallets=int(snapshot.get('holder_wallets', 0)),
            positions=int(snapshot.get('positions', 0)),
            as_of_block=snapshot.get('as_of_block'),
            updated_at=updated_at,
            assets=assets,
        )

    def resolve_gm_market(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        if not _stock_surfaces_enabled(user, getattr(info.context, 'META', {})):
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

    def resolve_gm_soft_quote(self, info, symbol, side, notional_value, duration='short'):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return GmTradeQuoteType(success=False, error_code='AUTH_REQUIRED')
        if _bsc_rate_limited(user.id, 'gm_soft_quote', 30):
            return GmTradeQuoteType(success=False, error_code='RATE_LIMITED')
        try:
            request = _validated_gm_trade_request(symbol, side, notional_value, duration)
            meta = getattr(info.context, 'META', {})
            # Ondo's issuer eligibility applies to acquisition AND redemption.
            # Confío's optional overlay is entry-only, so eligible holders in
            # an overlay-blocked country can still sell.
            if not _stock_issuer_eligible(user, meta):
                return GmTradeQuoteType(success=False, error_code='TRADE_NOT_AVAILABLE')
            if request['side'] == 'buy' and not _stock_buy_enabled(user, meta):
                return GmTradeQuoteType(success=False, error_code='TRADE_NOT_AVAILABLE')
            from . import gm_api
            data = gm_api.soft_attestation(**request)
            return GmTradeQuoteType(**_normalize_gm_quote(data, request, binding=False))
        except Exception as exc:  # noqa: BLE001
            return _gm_quote_error(exc)

    def resolve_gm_holdings(self, info):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        if not _stock_surfaces_enabled(user, getattr(info.context, 'META', {})):
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
        if not _stock_surfaces_enabled(user, getattr(info.context, 'META', {})):
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
            # Null distinguishes an upstream failure from a valid asset with
            # no candles yet. The list field is nullable by design so clients
            # can keep cached data or show an honest retry state.
            return None
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
        from .eligibility import ONDO_POLICY, check_stock_buy_eligibility
        from . import vault
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return None
        # The FULL set (phone AND IP), because a request exists here. Checking
        # phone alone told users behind a blocked IP that they could save while
        # the relay refused them, so their deposits stranded. Same answer the
        # mint gate will give.
        request_meta = getattr(info.context, 'META', {})
        eligible = ONDO_POLICY.evaluate(user, request_meta).allowed
        stocks_enabled = (
            eligible and getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False)
        )
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
        sweepable_wei_int = _sweepable_usdt_wei(user, bsc_address)
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
            sweepable_usdt_usd=sweepable_wei_int / (10 ** 18),
            sweepable_usdt_wei=str(sweepable_wei_int),
            # Discovery is visible only when the ops switch and issuer geo
            # policy both allow it.
            stocks_enabled=stocks_enabled,
            # UI capability only. Eligible holders can still reach the sell
            # execution endpoint if the discovery switch is later darkened;
            # Ondo-ineligible jurisdictions remain blocked from redemption.
            stocks_trading_enabled=(stocks_enabled and _stock_execution_ready()),
            stocks_buy_enabled=(
                stocks_enabled
                and check_stock_buy_eligibility(user, request_meta)
                and _stock_execution_ready()
            ),
            cusd_deposits_paused=getattr(settings, 'CUSD_DEPOSITS_PAUSED', True),
            usdt_balance_usd=usdt_wei_int / (10 ** 18),
            usdt_balance_wei=str(usdt_wei_int),
            confio_balance=confio_wei_int / (10 ** 18),
        )

    def resolve_cusd_plus_conversions_in_flight(self, info):
        from conversion.models import Conversion
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return []
        scope = _actor_filter(info)
        if scope is None:
            return []
        lookup = {'is_deleted': False, 'conversion_type__in': Conversion.SAVINGS_TYPES,
                  'status__in': Conversion.IN_FLIGHT_STATUSES}
        if scope['actor_type'] == 'business':
            lookup['actor_business_id'] = scope['actor_business_id']
        else:
            lookup['actor_user'] = user
        return [_serialize(c) for c in Conversion.objects.filter(**lookup)[:20]]

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
            # Display mirror only; the deployed router's fixed 30 bps is
            # authoritative and the sponsor policy requires exact parity.
            gm_trade_fee_bps=getattr(settings, 'CUSD_PLUS_GM_TRADE_FEE_BPS', 0),
            stock_router_address=getattr(settings, 'CUSD_PLUS_STOCK_ROUTER_ADDRESS', None) or None,
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
    # WIRE names are deliberately unchanged across the model merge so the
    # shipped app keeps working without a coordinated release.
    return CusdPlusConversionType(
        conversion_id=str(conv.internal_id),
        direction=conv.conversion_type,
        amount_usd=float(conv.from_amount),
        quoted_receive_usd=float(conv.to_amount),
        status=conv.status,
        src_tx_id=conv.from_transaction_hash or '',
        dest_tx_hash=conv.to_transaction_hash or '',
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
        from conversion.models import Conversion
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

        conv = Conversion.objects.create(
            actor_user=user if scope['actor_type'] == 'user' else None,
            actor_business_id=scope.get('actor_business_id'),
            actor_type=scope['actor_type'],
            actor_display_name=getattr(user, 'username', '') or '',
            conversion_type=direction,
            from_amount=amount_usd,
            to_amount=quoted_receive_usd,
            quoted_cost_pct=quoted_cost_pct,
            user_bsc_address=user_bsc_address,
            actor_address=user_algo_address,
            status='CREATED',
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
        from conversion.models import Conversion
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
        lookup['conversion_type__in'] = Conversion.SAVINGS_TYPES
        conv = Conversion.objects.filter(**lookup).first()
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
            conv.from_transaction_hash = tx_ref or conv.from_transaction_hash
            conv.src_committed_at = now
            update += ['from_transaction_hash', 'src_committed_at']
        elif new_status == 'COMPLETED':
            conv.to_transaction_hash = tx_ref or conv.to_transaction_hash
            conv.completed_at = now
            update += ['to_transaction_hash', 'completed_at']
            # Balance just changed on chain — drop the fresh-read cache so
            # the next summary shows the new position, not a 30s-old one.
            from . import vault
            vault.invalidate_position(conv.user_bsc_address)
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
    # `get` followed by `set` loses increments when two Daphne workers race.
    # `add`/`incr` map to atomic operations in the production Redis backend,
    # so purchaser-attestation and sponsor limits remain real under retries.
    if cache.add(key, 1, 60):
        return False
    try:
        return cache.incr(key) > per_minute
    except ValueError:
        # The key may expire between add() and incr(). Re-create it as the
        # first request in a fresh window; failing closed here would turn a
        # harmless expiry race into a user-visible minute-long outage.
        cache.set(key, 1, 60)
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

        # Business accounts: this relay MOVES MONEY, so it clears the same
        # permission the sponsored rail requires. Without it the legacy path
        # was a hole straight through SponsorBscBatch's check — an employee
        # holding a business signing key could relay a USDT transfer that the
        # sponsored rail would have refused (audit 2026-08-03 [P1] #9).
        from users.jwt_context import get_jwt_business_context_with_validation
        _ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if _ctx and _ctx.get('account_type') == 'business':
            if not get_jwt_business_context_with_validation(
                    info, required_permission='send_funds'):
                return SubmitBscTransaction(success=False, error='permission_denied')

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

        # JWT-bound signer, checked for EVERY relayed tx — not just redeems.
        # The destination allowlist alone says nothing about WHOSE money moves:
        # USDT.transfer is an allowlisted destination, so any key the caller
        # holds could spend any address's balance through here. Same rule the
        # sponsored rail enforces via the intent signature (audit [P1] #9).
        active_addr = (_active_bsc_address(info) or '').lower()
        if not active_addr:
            return SubmitBscTransaction(success=False, error='no_bsc_address')
        try:
            from eth_account import Account as _EthAccount
            tx_signer = _EthAccount.recover_transaction(raw).lower()
        except Exception:
            return SubmitBscTransaction(success=False, error='unrecoverable_signer')
        if tx_signer != active_addr:
            logger.warning(
                'BSC relay refused: signer %s is not the active account address %s (user %s)',
                tx_signer, active_addr, user.id,
            )
            return SubmitBscTransaction(success=False, error='signer_not_active_account')

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
        # Set only when this tx IS a vault mint that passed the geo gate; the
        # post-broadcast history write keys off it.
        mint_amount_wei = None
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
                # tx_signer was recovered and bound to the active account above.
                if not _redeem_recipient_allowed(user, recipient, tx_signer):
                    logger.warning(
                        'redeemToUsdt recipient %s rejected for user %s (signer %s)',
                        recipient, user.id, tx_signer,
                    )
                    return SubmitBscTransaction(success=False, error='redeem_recipient_not_allowed')
            # Mint geo-gate (2026-07-30): since ramps deliver raw USDT to
            # everyone, THIS is where geo-eligibility is enforced — phone
            # country + Cloudflare IP country. Mint only; redeem above and
            # raw USDT transfers stay ungated (exits are never gated).
            if data_hex.startswith(_SEL_SUBSCRIBE_AND_MINT):
                if len(data_hex) != 8 + 192:
                    return SubmitBscTransaction(success=False, error='bad_calldata')
                from .eligibility import check_savings_mint_eligibility
                if not check_savings_mint_eligibility(user, getattr(info.context, 'META', {})):
                    # Close any saga waiting on this mint: it can never happen
                    # for this holder, and DEST_ARRIVED would retry forever.
                    from .tasks import mark_saga_delivered_as_usdt
                    mark_saga_delivered_as_usdt(_active_bsc_address(info) or '')
                    return SubmitBscTransaction(success=False, error='mint_not_available')
                # subscribeAndMint(uint256 usdtAmount, uint256 minUsdyOut,
                # address recipient) — first word, from calldata we validated,
                # never from the client. Recorded after broadcast.
                mint_amount_wei = int(data_hex[8:72], 16)
                from .vault import is_safe_mint_amount
                if not is_safe_mint_amount(mint_amount_wei):
                    # The money stays raw USDT and remains spendable. Close a
                    # bridge saga if one owns this arrival so old clients do
                    # not retry the same unsafe mint on every foreground.
                    from .tasks import mark_saga_delivered_as_usdt
                    mark_saga_delivered_as_usdt(
                        _active_bsc_address(info) or '', mint_amount_wei)
                    return SubmitBscTransaction(
                        success=False, error='mint_below_redeemable_minimum')

        from .tasks import _rpc
        try:
            tx_hash = _rpc('eth_sendRawTransaction', [raw])
            if mint_amount_wei is not None:
                # The gate allowed it and it is on the wire: NOW the history
                # row exists. Opening it before the gate is what stranded
                # deposits at "pendiente" forever.
                from .tasks import record_savings_mint
                acct = _active_account(info)
                record_savings_mint(
                    user=user,
                    business=getattr(acct, 'business', None) if acct else None,
                    actor_type=('business' if acct is not None
                                and acct.account_type == 'business' else 'user'),
                    display_name=getattr(acct, 'display_name', '') if acct else '',
                    amount_wei=mint_amount_wei, tx_hash=tx_hash,
                    bsc_address=_active_bsc_address(info) or '',
                )
            if is_autoconvert:
                # Ledger row = this outbound BNB is a Confío-recorded convert.
                # Outbound native transfers absent from this table are dust
                # extraction and disqualify the user from further subsidies.
                from decimal import Decimal

                from blockchain.models import PendingAutoSwap
                try:
                    wei = int.from_bytes(fields[4], 'big')
                    acct = _active_account(info)
                    if acct is None:
                        # The row is the ALLOWLIST for outbound native BNB, so
                        # a missing one makes a legitimate convert look like
                        # dust extraction. Never let that pass silently.
                        raise RuntimeError('no JWT account to attribute the convert to')
                    PendingAutoSwap.objects.create(
                        account=acct,
                        actor_user=user,
                        actor_type='user',
                        actor_address=acct.bsc_address or '',
                        asset_type='BNB',
                        # micro-BNB and BNB: the same units convention the
                        # ALGO/USDC rows use. Exact wei is not needed — the
                        # allowlist is keyed by tx hash, the value is context.
                        amount_micro=wei // 10 ** 12,
                        amount_decimal=Decimal(wei) / Decimal(10 ** 18),
                        source_tx_hash=tx_hash or '',
                        status='SUBMITTED',
                    )
                except Exception:  # noqa: BLE001 — ledger write must not fail the relay
                    logger.error(
                        'BNB auto-convert ledger write FAILED for %s — this outbound '
                        'BNB will look unledgered to the farming check', tx_hash,
                        exc_info=True)
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
        # Optional for wire compatibility with released clients. New clients
        # bind it into intentId and reuse it across transport/quote retries.
        request_id = graphene.String(required=False)

    success = graphene.Boolean()
    tx_hash = graphene.String()
    authorization_required = graphene.Boolean()
    error = graphene.String()
    # Tri-state (null ≠ false) — see SubmitBscSend.executed in send/schema.py.
    execution = graphene.String(
        description="Sponsor-observed execution: executed | reverted | noop; null=unknown")

    def mutate(self, info, calls, nonce, deadline, intent_signature,
               authorization=None, request_id=None):
        import time as _time

        from django.conf import settings

        from . import sponsor_7702

        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return SponsorBscBatch(success=False, error='auth_required')

        # Business accounts: this batch MOVES MONEY, so it must clear the same
        # permission the send rail requires (send/schema.py asks for
        # 'send_funds'). Without this the generic batch was a hole straight
        # through both that check and the owner-only ramp rule: _active_bsc_address
        # resolves the BUSINESS address for any employee's JWT (via
        # _active_account, which validates with required_permission=None), and
        # the policy's USDT.transfer recipient is deliberately unrestricted
        # ("exits are never gated" — true of GEOGRAPHY, not of authority). An
        # employee could redeem business shares and transfer the USDT out in
        # one batch. Personal contexts are unaffected: the permission check in
        # get_jwt_business_context_with_validation only applies to business ones.
        from users.jwt_context import get_jwt_business_context_with_validation
        _ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if _ctx and _ctx.get('account_type') == 'business':
            if not get_jwt_business_context_with_validation(
                    info, required_permission='send_funds'):
                return SponsorBscBatch(success=False, error='permission_denied')

        if not getattr(settings, 'CUSD_PLUS_7702_ENABLED', False):
            return SponsorBscBatch(success=False, error='disabled')
        if not sponsor_7702.delegate_address():
            return SponsorBscBatch(success=False, error='delegate_not_configured')
        # JWT-bound address: the intent must be signed by THIS account's
        # registered BSC key — never a client-supplied address.
        user_addr = _active_bsc_address(info)
        if not user_addr:
            return SponsorBscBatch(success=False, error='no_bsc_address')
        user_addr = user_addr.lower()

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
        request_id = (request_id or '').strip()
        if request_id and not _SPONSOR_REQUEST_ID_RE.fullmatch(request_id):
            return SponsorBscBatch(success=False, error='bad_request_id')

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
        mint_calls = [
            c for c in norm_calls
            if c['to'] == vault_l and c['data'][2:10] == _SEL_SUBSCRIBE_AND_MINT
        ]
        # One sponsored request represents one savings operation and creates
        # one history row. Allowing a second mint would both bypass an amount
        # check that inspected only the first call and under-report movement.
        if len(mint_calls) > 1:
            return SponsorBscBatch(success=False, error='multiple_mints_not_allowed')
        mint_call = mint_calls[0] if mint_calls else None
        mint_refusal_error = None
        mint_refusal_amount = None
        if mint_call is not None:
            if len(mint_call['data']) != 2 + 8 + 192:
                return SponsorBscBatch(success=False, error='bad_calldata')
            try:
                mint_amount_wei = int(mint_call['data'][10:74], 16)
            except ValueError:
                return SponsorBscBatch(success=False, error='bad_calldata')
            from .eligibility import check_savings_mint_eligibility
            if not check_savings_mint_eligibility(user, getattr(info.context, 'META', {})):
                mint_refusal_error = 'mint_not_available'
            # subscribeAndMint(uint256,uint256,address) first argument.
            # Enforce this server-side so an older or modified client cannot
            # create a position that rounds below Ondo's exact $1 exit floor.
            from .vault import is_safe_mint_amount
            if mint_refusal_error is None and not is_safe_mint_amount(mint_amount_wei):
                mint_refusal_error = 'mint_below_redeemable_minimum'
                mint_refusal_amount = mint_amount_wei

        chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
        # Set the instant a broadcast is attempted; nothing after that point
        # may be reported to the client as a definitive failure.
        broadcast_tx_hash = None
        try:
            sponsor_7702.validate_policy(norm_calls, user, user_addr)

            # The generic savings rail's kind (and thus the intentId the user
            # signed) is derived from the selectors; the client derives the
            # SAME value. source_id is omitted (no domain row here).
            kind = sponsor_7702.classify_calls_kind(norm_calls)
            if kind in ('stock_buy', 'stock_sell'):
                meta = getattr(info.context, 'META', {})
                if not _stock_issuer_eligible(user, meta):
                    return SponsorBscBatch(success=False, error='trade_not_available')
                if kind == 'stock_buy' and not _stock_buy_enabled(user, meta):
                    return SponsorBscBatch(success=False, error='trade_not_available')
            intent_id = sponsor_7702.intent_id_for(
                kind, client_request_id=request_id or None)
            digest = sponsor_7702.intent_digest(
                norm_calls, nonce_i, deadline_i, user_addr, chain_id, intent_id)
            signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
            if signer != user_addr:
                return SponsorBscBatch(success=False, error='bad_intent_signature')

            # A signed exact replay refers to a batch whose outcome is
            # already on record. Return it before re-evaluating today's entry
            # gate; otherwise a policy change could mutate a different live
            # saga even though this request already broadcast earlier.
            if request_id:
                from blockchain.models import SponsoredBatch
                existing = SponsoredBatch.objects.filter(
                    user=user, client_request_id=request_id,
                ).order_by('-id').first()
                if existing is not None:
                    exact_match = sponsor_7702.batch_matches_calls(
                        existing, kind, norm_calls)
                    stock_match = (
                        kind in ('stock_buy', 'stock_sell')
                        and existing.kind == kind
                        and sponsor_7702.batch_matches_stock_intent(
                            existing, norm_calls)
                    )
                    if (existing.user_bsc_address.lower() != user_addr
                            or not (exact_match or stock_match)):
                        return SponsorBscBatch(
                            success=False, error='idempotency_conflict')
                    return SponsorBscBatch(
                        success=True,
                        tx_hash=existing.tx_hash,
                        execution=sponsor_7702.batch_execution_hint(existing),
                    )

            # Refusal changes saga history, so it must happen only after the
            # calldata policy and the wallet's intent signature prove this is
            # the holder's request. Nothing is broadcast on this path.
            if mint_refusal_error is not None:
                from .tasks import mark_saga_delivered_as_usdt
                mark_saga_delivered_as_usdt(
                    user_addr, mint_refusal_amount,
                    refusal_source='sponsored')
                return SponsorBscBatch(success=False, error=mint_refusal_error)

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

            tx_hash, batch = sponsor_7702.send_sponsored_batch(
                user, user_addr, norm_calls, nonce_i, deadline_i,
                intent_signature, auth_dict, kind,
                client_request_id=request_id, intent_id=intent_id)
            broadcast_tx_hash = tx_hash  # past the point of no return
            if kind in ('stock_buy', 'stock_sell'):
                # Drop only fresh values. If the tx later reverts, the next
                # scan simply observes the unchanged chain; if it executes,
                # the client's receipt-triggered refetch sees the new state.
                from django.core.cache import cache as _cache
                from . import vault as _vault
                _vault.invalidate_position(user_addr)
                _cache.delete(f'gm_hold:{user_addr.lower()}')
            if mint_call is not None:
                # Gate passed and the batch is on the wire: record the mint as
                # history. subscribeAndMint(uint256 usdtAmount, ...) — first
                # word of calldata we validated, never a client-supplied value.
                from .tasks import record_savings_mint
                acct = _active_account(info)
                record_savings_mint(
                    user=user,
                    business=getattr(acct, 'business', None) if acct else None,
                    actor_type=('business' if acct is not None
                                and acct.account_type == 'business' else 'user'),
                    display_name=getattr(acct, 'display_name', '') if acct else '',
                    amount_wei=int(mint_call['data'][10:74], 16),
                    tx_hash=tx_hash, bsc_address=user_addr,
                )
        except sponsor_7702.ExistingSponsoredBatch as exc:
            existing = exc.batch
            same_address = existing.user_bsc_address.lower() == user_addr
            exact_match = (
                same_address
                and sponsor_7702.batch_matches_calls(existing, kind, norm_calls)
            )
            stock_match = (
                same_address
                and kind in ('stock_buy', 'stock_sell')
                and existing.kind == kind
                and sponsor_7702.batch_matches_stock_intent(existing, norm_calls)
            )
            if (exc.reason == 'client_request_id'
                    and not (exact_match or stock_match)):
                return SponsorBscBatch(success=False, error='idempotency_conflict')
            if not exact_match and not stock_match:
                return SponsorBscBatch(success=False, error='delegate_nonce_in_flight')
            return SponsorBscBatch(
                success=True,
                tx_hash=existing.tx_hash,
                execution=sponsor_7702.batch_execution_hint(existing),
            )
        except sponsor_7702.PolicyError as exc:
            return SponsorBscBatch(success=False, error=exc.code)
        except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
            logger.exception('7702 sponsored batch failed for user %s', user.id)
            if broadcast_tx_hash:
                # The transaction IS on the network and something AFTER the
                # broadcast blew up. Reporting failure here tells the client
                # nothing happened, and it may pay an already-funded provider
                # order a second time (round 3 [P1] #3). Hand back the hash
                # with an unknown execution instead: the client polls for the
                # receipt, exactly as it does when the sponsor didn't observe
                # one in time.
                logger.error('7702 post-broadcast failure for %s — returning unknown, not failure',
                             broadcast_tx_hash)
                return SponsorBscBatch(success=True, tx_hash=broadcast_tx_hash, execution=None)
            return SponsorBscBatch(success=False, error=str(exc)[:200])

        return SponsorBscBatch(success=True, tx_hash=tx_hash,
                               execution=getattr(batch, 'executed_early', None))


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
        from conversion.models import Conversion as _Conv
        awaited = set(_Conv.objects.filter(
            conversion_type='to_savings',
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


class PrepareGmTrade(graphene.Mutation):
    """Create one binding Ondo attestation for the JWT account.

    The client supplies an idempotency key so a lost HTTP response reuses the
    still-live attestation instead of consuming another purchaser limit.
    Settlement remains non-custodial: this returns signed quote data; only the
    user's subsequent EIP-712 batch signature can execute the router call.
    """

    class Arguments:
        request_id = graphene.String(required=True)
        symbol = graphene.String(required=True)
        side = graphene.String(required=True)
        notional_value = graphene.String(required=True)
        duration = graphene.String(default_value='short')

    quote = graphene.Field(GmTradeQuoteType)

    def mutate(self, info, request_id, symbol, side, notional_value, duration='short'):
        from django.conf import settings
        from django.core.cache import cache

        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='AUTH_REQUIRED'))
        request_id = (request_id or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='BAD_REQUEST_ID'))
        if not getattr(settings, 'CUSD_PLUS_STOCK_TRADING_ENABLED', False):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='TRADING_DISABLED'))
        if not getattr(settings, 'CUSD_PLUS_STOCK_ROUTER_ADDRESS', ''):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='ROUTER_NOT_CONFIGURED'))
        if (
            not getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
            or not getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', '')
        ):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='SPONSOR_NOT_CONFIGURED'))
        if getattr(settings, 'CUSD_PLUS_GM_TRADE_FEE_BPS', 30) != 30:
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='FEE_CONFIG_MISMATCH'))
        account = _active_account(info)
        if account is None or not account.bsc_address:
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='NO_BSC_ADDRESS'))

        from users.jwt_context import get_jwt_business_context_with_validation
        ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if ctx and ctx.get('account_type') == 'business':
            if not get_jwt_business_context_with_validation(info, required_permission='send_funds'):
                return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='PERMISSION_DENIED'))

        try:
            request = _validated_gm_trade_request(symbol, side, notional_value, duration)
        except Exception as exc:  # noqa: BLE001
            return PrepareGmTrade(quote=_gm_quote_error(exc))
        meta = getattr(info.context, 'META', {})
        if not _stock_issuer_eligible(user, meta):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='TRADE_NOT_AVAILABLE'))
        if request['side'] == 'buy':
            if not _stock_buy_enabled(user, meta):
                return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='TRADE_NOT_AVAILABLE'))

        cache_key = f'gm_firm_attestation:{user.id}:{account.id}:{request_id}'
        cached = cache.get(cache_key)
        if cached is not None:
            # The key is bound to the complete request, not merely the user.
            if cached.get('_request') != request:
                return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='IDEMPOTENCY_CONFLICT'))
            return PrepareGmTrade(quote=GmTradeQuoteType(**cached['quote']))
        if _bsc_rate_limited(user.id, 'gm_firm_quote', 6):
            return PrepareGmTrade(quote=GmTradeQuoteType(success=False, error_code='RATE_LIMITED'))

        # A binding attestation consumes the shared Ondo purchaser quota.
        # Serialize identical request IDs across Daphne workers so an HTTP
        # retry cannot mint two live attestations before either response is
        # cached. The short lease prevents a crashed worker from wedging the
        # request; the result cache below remains the idempotency authority.
        lock_key = f'{cache_key}:lock'
        release_lock = _acquire_gm_quote_lock(cache, lock_key, 30)
        if release_lock is None:
            cached = cache.get(cache_key)
            if cached is not None:
                if cached.get('_request') != request:
                    return PrepareGmTrade(
                        quote=GmTradeQuoteType(success=False, error_code='IDEMPOTENCY_CONFLICT'))
                return PrepareGmTrade(quote=GmTradeQuoteType(**cached['quote']))
            return PrepareGmTrade(
                quote=GmTradeQuoteType(success=False, error_code='QUOTE_IN_PROGRESS'))

        try:
            from . import gm_api
            data = gm_api.binding_attestation(**request)
            normalized = _normalize_gm_quote(data, request, binding=True)
            ttl = max(1, min(1800, int(normalized['expiration'] - timezone.now().timestamp())))
            cache.set(cache_key, {'_request': request, 'quote': normalized}, ttl)
            return PrepareGmTrade(quote=GmTradeQuoteType(**normalized))
        except Exception as exc:  # noqa: BLE001
            return PrepareGmTrade(quote=_gm_quote_error(exc))
        finally:
            release_lock()


class Mutation(graphene.ObjectType):
    start_cusd_plus_conversion = StartCusdPlusConversion.Field()
    advance_cusd_plus_conversion = AdvanceCusdPlusConversion.Field()
    submit_bsc_transaction = SubmitBscTransaction.Field()
    register_bsc_usdt_arrival = RegisterBscUsdtArrival.Field()
    sponsor_bsc_batch = SponsorBscBatch.Field()
    prepare_gm_trade = PrepareGmTrade.Field()
