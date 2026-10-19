"""GraphQL for crypto & metals (ConfioSwapRouter on PancakeSwap).

Every field here is a NEW top-level query, queried alone by the app: GraphQL
validation is all-or-nothing, so adding these to a shared query would break
that query against any server that predates them.
"""
from __future__ import annotations

import graphene
from django.conf import settings

from . import crypto_catalog


def _user(info):
    user = getattr(info.context, 'user', None)
    return user if user is not None and user.is_authenticated else None


def _meta(info):
    return getattr(info.context, 'META', {}) or {}


class CryptoAssetType(graphene.ObjectType):
    symbol = graphene.String(required=True)
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    address = graphene.String(required=True)
    decimals = graphene.Int(required=True)
    category = graphene.String(required=True, description="'crypto' or 'metal'")
    featured = graphene.Boolean(required=True)
    custody = graphene.String(required=True, description='binance_peg | tether_gold | wrapped_native | native')
    max_order_usd = graphene.Int(description='Per-order buy cap in USD for thin pools; null = no cap')
    price_usd = graphene.Float(description='Null until priced: unknown is not zero')
    day_change_pct = graphene.Float()
    sparkline_24h = graphene.List(graphene.NonNull(graphene.Float))


class CryptoMarketType(graphene.ObjectType):
    assets = graphene.List(graphene.NonNull(CryptoAssetType), required=True)
    updated_at = graphene.DateTime()


class CryptoQuoteType(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error_code = graphene.String()
    symbol = graphene.String()
    side = graphene.String()
    amount_in = graphene.String(description='buy: net USDT wei; sell: token base units')
    expected_out = graphene.String(description='buy: token base units; sell: USDT wei')
    route = graphene.String(description='Exact router `route` argument, 0x-hex')
    pool_fee_bps = graphene.Int(description='Sum of PancakeSwap pool fees along the route')
    price_impact_bps = graphene.Int(description='Execution vs the last snapshot price, null if unknown')


class CryptoHoldingType(graphene.ObjectType):
    """Everything a SELL needs, independent of cryptoMarket: a holder who
    became country-blocked (market hidden) or holds a delisted token must
    still be able to leave."""
    symbol = graphene.String(required=True)
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    address = graphene.String(required=True)
    custody = graphene.String(required=True)
    listed = graphene.Boolean(required=True, description='False = sell only (delisted or deferred)')
    category = graphene.String(required=True)
    units = graphene.String(required=True, description='Base units, exact')
    decimals = graphene.Int(required=True)
    value_usd = graphene.Float(description='Null when no price is known')
    day_change_pct = graphene.Float()


class CryptoCandleType(graphene.ObjectType):
    timestamp = graphene.Float(required=True, description='ms epoch')
    close = graphene.Float(required=True)


class CryptoCapabilitiesType(graphene.ObjectType):
    enabled = graphene.Boolean(required=True, description='Discovery (switch + country policy)')
    trading_enabled = graphene.Boolean(required=True)
    buy_enabled = graphene.Boolean(required=True)
    ack_required = graphene.Boolean(required=True)
    ack_version = graphene.Int(required=True)
    disclosure_title = graphene.String(required=True)
    disclosure_points = graphene.List(graphene.NonNull(graphene.String), required=True)
    funding_dollar = graphene.String(required=True, description="'cusd_plus' or 'cusd'")
    fee_bps = graphene.Int(description="cUSD's live conversion fee; null if unreadable")
    max_slippage_bps = graphene.Int(required=True)
    router_address = graphene.String()
    blocked_message = graphene.String()


def _pool_fee_bps(token) -> int:
    path = token.route_path
    if token.route_kind == crypto_catalog.ROUTE_V3:
        return sum(int(fee) for fee in path[1::2]) // 100
    return 25 * (len(path) - 1)


class Query(graphene.ObjectType):
    crypto_market = graphene.Field(CryptoMarketType)
    crypto_capabilities = graphene.Field(CryptoCapabilitiesType)
    crypto_holdings = graphene.List(
        graphene.NonNull(CryptoHoldingType),
        description='Null = unknown (scan failed, never scanned); [] = holds nothing',
    )
    crypto_ohlc = graphene.List(
        graphene.NonNull(CryptoCandleType),
        symbol=graphene.String(required=True),
        range=graphene.String(default_value='1D', description='1D | 1M | 3M | 6M | 1Y | MAX'),
        description='Display-only price history; null = upstream failed',
    )
    crypto_quote = graphene.Field(
        CryptoQuoteType,
        symbol=graphene.String(required=True),
        side=graphene.String(required=True),
        amount_in=graphene.String(required=True),
    )

    def resolve_crypto_market(self, info):
        from . import crypto_risk
        from .crypto_prices import market_rows

        user = _user(info)
        if user is None or not crypto_risk.surfaces_enabled(user, _meta(info)):
            return None
        rows = market_rows()
        updated = max((r['priced_at'] for r in rows if r['priced_at']), default=None)
        return CryptoMarketType(
            updated_at=updated,
            assets=[
                CryptoAssetType(
                    symbol=r['token'].symbol, ticker=r['token'].ticker, name=r['token'].name,
                    address=r['token'].address, decimals=r['token'].decimals,
                    category=r['token'].category, featured=r['token'].featured,
                    custody=r['token'].custody,
                    max_order_usd=r['token'].max_order_usd,
                    price_usd=float(r['price_usd']) if r['price_usd'] is not None else None,
                    day_change_pct=r['day_change_pct'],
                    sparkline_24h=r['sparkline'],
                )
                for r in rows
            ],
        )

    def resolve_crypto_capabilities(self, info):
        from . import crypto_risk
        from .crypto_policy import live_fee_bps
        from .eligibility import CRYPTO_POLICY, ONDO_POLICY

        user = _user(info)
        if user is None:
            return None
        meta = _meta(info)
        decision = CRYPTO_POLICY.evaluate(user, meta)
        try:
            fee = live_fee_bps()
        except Exception:  # noqa: BLE001 — unknown, the app hides the fee line
            fee = None
        # Ondo-eligible people hold Confío Dollar+; everyone else Confío Dollar.
        funding = 'cusd_plus' if ONDO_POLICY.evaluate(user, meta).allowed else 'cusd'
        return CryptoCapabilitiesType(
            enabled=crypto_risk.surfaces_enabled(user, meta),
            trading_enabled=crypto_risk.trading_ready(),
            buy_enabled=crypto_risk.buy_enabled(user, meta),
            ack_required=not crypto_risk.acknowledged(user),
            ack_version=crypto_risk.ACK_VERSION,
            disclosure_title=crypto_risk.DISCLOSURE_TITLE,
            disclosure_points=list(crypto_risk.DISCLOSURE_POINTS),
            funding_dollar=funding,
            fee_bps=fee,
            max_slippage_bps=int(getattr(settings, 'CRYPTO_MAX_SLIPPAGE_BPS', 100)),
            router_address=(getattr(settings, 'CRYPTO_SWAP_ROUTER_ADDRESS', '') or None),
            blocked_message=None if decision.allowed else decision.message,
        )

    def resolve_crypto_holdings(self, info):
        from .crypto_holdings import holdings_units
        from .crypto_prices import market_rows
        from .schema import _active_account

        user = _user(info)
        if user is None:
            return None
        account = _active_account(info)
        if account is None or not account.bsc_address:
            return []
        units = holdings_units(account.bsc_address)
        if units is None:
            return None
        rows = {r['token'].symbol: r for r in market_rows()}
        listed = {t.symbol for t in crypto_catalog.tokens()}
        out = []
        for token in crypto_catalog.tokens(include_unlisted=True):
            raw = units.get(token.symbol)
            if not raw:
                continue
            row = rows.get(token.symbol)
            price = row['price_usd'] if row else None
            if price is None and token.symbol not in listed:
                # Delisted/deferred tokens have no snapshot: price the few
                # held ones live (one quote) so a sell shows its value.
                from .crypto_prices import price_usd
                price = price_usd(token)
            value = None
            if price is not None:
                value = float(price) * raw / 10 ** token.decimals
            out.append(CryptoHoldingType(
                symbol=token.symbol, ticker=token.ticker, name=token.name,
                address=token.address, custody=token.custody, listed=token.symbol in listed,
                category=token.category, units=str(raw), decimals=token.decimals,
                value_usd=value, day_change_pct=row['day_change_pct'] if row else None,
            ))
        return out

    def resolve_crypto_ohlc(self, info, symbol, range='1D'):
        from . import crypto_chart

        user = _user(info)
        if user is None or range not in crypto_chart.RANGES:
            return []
        # Holders of a token keep its chart even when the market is hidden.
        token = crypto_catalog.by_symbol(symbol, include_unlisted=True)
        if token is None:
            return []
        try:
            candles = crypto_chart.ohlc(token, range)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception('crypto_ohlc upstream failed')
            return None
        return [CryptoCandleType(timestamp=float(c['timestamp']), close=c['close']) for c in candles]

    def resolve_crypto_quote(self, info, symbol, side, amount_in):
        from . import crypto_risk
        from .crypto_prices import latest_prices, quote_exact_in

        user = _user(info)
        if user is None:
            return CryptoQuoteType(success=False, error_code='AUTH_REQUIRED')
        if side not in ('buy', 'sell'):
            return CryptoQuoteType(success=False, error_code='BAD_SIDE')
        token = crypto_catalog.by_symbol(symbol, include_unlisted=(side == 'sell'))
        if token is None:
            return CryptoQuoteType(success=False, error_code='NOT_LISTED')
        if side == 'buy' and not crypto_risk.surfaces_enabled(user, _meta(info)):
            return CryptoQuoteType(success=False, error_code='NOT_AVAILABLE')
        try:
            amount = int(amount_in)
        except (TypeError, ValueError):
            return CryptoQuoteType(success=False, error_code='BAD_AMOUNT')
        if amount <= 0 or amount > 10 ** 30:
            return CryptoQuoteType(success=False, error_code='BAD_AMOUNT')
        try:
            out = quote_exact_in(token, side, amount)
        except Exception:  # noqa: BLE001
            return CryptoQuoteType(success=False, error_code='QUOTE_UNAVAILABLE')
        impact = None
        price = latest_prices().get(token.symbol)
        if price and out > 0:
            # USD in vs USD out at the snapshot price (includes pool fees).
            unit = 10 ** token.decimals
            if side == 'buy':
                usd_in, usd_out = amount / 1e18, float(price) * out / unit
            else:
                usd_in, usd_out = float(price) * amount / unit, out / 1e18
            if usd_in > 0:
                impact = max(0, round((usd_in - usd_out) / usd_in * 10_000))
        return CryptoQuoteType(
            success=True, symbol=token.symbol, side=side, amount_in=str(amount),
            expected_out=str(out), route='0x' + token.route_bytes(side).hex(),
            pool_fee_bps=_pool_fee_bps(token), price_impact_bps=impact,
        )


class AcknowledgeCryptoRisk(graphene.Mutation):
    class Arguments:
        version = graphene.Int(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    def mutate(self, info, version):
        from . import crypto_risk

        user = _user(info)
        if user is None:
            return AcknowledgeCryptoRisk(success=False, error='AUTH_REQUIRED')
        if version != crypto_risk.ACK_VERSION:
            return AcknowledgeCryptoRisk(success=False, error='OUTDATED_DISCLOSURE')
        crypto_risk.acknowledge(user)
        return AcknowledgeCryptoRisk(success=True)


class Mutation(graphene.ObjectType):
    acknowledge_crypto_risk = AcknowledgeCryptoRisk.Field()
