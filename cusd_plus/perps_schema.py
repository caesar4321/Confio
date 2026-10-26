"""GraphQL for Futuros (Hyperliquid perps).

Every field here is a NEW top-level query or mutation, queried alone by the
app: GraphQL validation is all-or-nothing, so adding these to a shared query
would break that query against any server that predates them.

Futuros is personal-account only: positions live on the member's own
address, signed by their own key. Every position-scoped call also checks
the position belongs to the JWT account's address.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

import graphene
from django.conf import settings

from .crypto_schema import _meta, _user

logger = logging.getLogger(__name__)


def _personal_wallet(info) -> str | None:
    from .schema import _active_account

    account = _active_account(info)
    if account is None or account.account_type != 'personal' or not account.bsc_address:
        return None
    return account.bsc_address.lower()


def _float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, ArithmeticError):
        return None


class PerpMarketType(graphene.ObjectType):
    coin = graphene.String(required=True, description="Hyperliquid name: 'BTC' or 'xyz:GOLD'")
    dex = graphene.String(required=True, description="'' = Hyperliquid core perps")
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    asset_class = graphene.String(required=True, description='crypto | stock | index | commodity | fx')
    asset_id = graphene.Int(required=True, description='Hyperliquid order asset id')
    sz_decimals = graphene.Int(required=True)
    max_leverage = graphene.Int(required=True, description="The venue's maximum; Confío sets no cap")
    only_isolated = graphene.Boolean(required=True)
    taker_fee_rate = graphene.Float(required=True)
    mark_px = graphene.Float(description='Null until priced: unknown is not zero')
    day_change_pct = graphene.Float()
    funding_rate = graphene.Float(description='Hourly funding rate (positive: longs pay shorts)')
    open_interest_usd = graphene.Float()
    day_volume_usd = graphene.Float()


class PerpsCapabilitiesType(graphene.ObjectType):
    enabled = graphene.Boolean(required=True, description='Discovery (switches + country policy)')
    trading_enabled = graphene.Boolean(required=True)
    open_enabled = graphene.Boolean(required=True, description='Opens and margin adds; closes stay open')
    ack_required = graphene.Boolean(required=True)
    ack_version = graphene.Int(required=True)
    disclosure_title = graphene.String(required=True)
    disclosure_points = graphene.List(graphene.NonNull(graphene.String), required=True)
    promotion_allowed = graphene.Boolean(
        required=True, description='False: no pushes, banners or assistant nudges about Futuros')
    funding_dollar = graphene.String(required=True, description="'cusd_plus' or 'cusd'")
    fee_bps = graphene.Int(description="cUSD's live conversion fee; null if unreadable")
    impact_warn_bps = graphene.Int(required=True)
    impact_max_bps = graphene.Int(required=True)
    slippage_bps = graphene.Int(required=True)
    min_margin_usd = graphene.Float(required=True)
    first_min_margin_usd = graphene.Float(required=True)
    new_account_charge_usd = graphene.Float(required=True)
    new_account = graphene.Boolean(description='The Hyperliquid account does not exist yet (first deposit '
                                               'pays the activation, higher minimum); null if unknown')
    blocked_message = graphene.String()


class PerpCandleType(graphene.ObjectType):
    timestamp = graphene.Float(required=True, description='ms epoch')
    close = graphene.Float(required=True)


class PerpCostsType(graphene.ObjectType):
    margin_usd = graphene.Float()
    exit_fee_usd = graphene.Float()
    bridge_cost_usd = graphene.Float()
    activation_usd = graphene.Float()
    credited_usd = graphene.Float()
    notional_usd = graphene.Float()
    open_fee_usd = graphene.Float()


def _costs_type(costs: dict | None) -> PerpCostsType | None:
    if not costs:
        return None
    return PerpCostsType(**{k: _float(v) for k, v in costs.items() if k in PerpCostsType._meta.fields})


class PerpPositionType(graphene.ObjectType):
    id = graphene.ID(required=True)
    coin = graphene.String(required=True)
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    asset_class = graphene.String(required=True)
    side = graphene.String(required=True, description='long | short')
    leverage = graphene.Int(required=True)
    margin_usd = graphene.Float(required=True)
    state = graphene.String(required=True)
    step_error = graphene.String()
    next_action = graphene.String(
        required=True,
        description='sign_open | wait_bridge | retry_bridge | open_order | manage | return | enter | wait_return | none')
    size = graphene.Float(description='Live signed size on Hyperliquid (null when none)')
    entry_px = graphene.Float()
    mark_px = graphene.Float()
    unrealized_pnl_usd = graphene.Float()
    return_on_equity = graphene.Float()
    liquidation_px = graphene.Float()
    margin_used_usd = graphene.Float()
    pending_margin_usd = graphene.Float(description='A top-up that arrived and waits to join the margin: '
                                                    'what it adds (the most the member signs for it)')
    protection_known = graphene.Boolean(description='The venue answered: take/stop below are the truth '
                                                    '(false: unknown, do not replace protection)')
    take_profit_px = graphene.Float(description='Live take-profit trigger on the venue, if any')
    stop_loss_px = graphene.Float(description='Live stop-loss trigger on the venue, if any')
    value_usd = graphene.Float(description="What this position's money is worth now, in its current step "
                                           '(null while the amount is not known yet)')
    position_value_usd = graphene.Float()
    funding_usd = graphene.Float(description='Since open (negative = paid)')
    realized_pnl_usd = graphene.Float()
    venue_fees_usd = graphene.Float()
    returned_usd = graphene.Float()
    put_in_usd = graphene.Float(description='Dollars put in (margin + top-ups), less top-ups that came back')
    result_usd = graphene.Float(description='Done: dollars back - dollars put in (all costs included)')
    liquidation = graphene.String()
    costs = graphene.Field(PerpCostsType)
    created_at = graphene.DateTime(required=True)
    opened_at = graphene.DateTime()
    closed_at = graphene.DateTime()
    done_at = graphene.DateTime()


def _next_action(position) -> str:
    state = position.state
    if state == 'quoted':
        return 'sign_open'
    if state == 'bridging':
        return 'wait_bridge'
    if state == 'refunded':
        return 'retry_bridge'
    if state == 'funded':
        return 'open_order'
    if state == 'open':
        if any(c.direction == 'add' and c.state == 'funded' for c in position.margin_changes.all()):
            return 'finish_margin'
        if any(c.direction == 'add' and c.state == 'bridging' for c in position.margin_changes.all()):
            return 'wait_bridge'
        return 'manage'
    if state in ('closed', 'liquidated', 'return_failed'):
        return 'return'
    if state == 'returning':
        return 'wait_return'
    if state == 'landed':
        return 'enter' if position.return_batch_id is None else 'wait_return'
    return 'none'


def _value_usd(position, live: dict | None, free_usd: Decimal) -> float | None:
    """One live position per member: its margin on the venue plus whatever is
    free on the account (released by a partial close, an unapplied top-up)."""
    from . import perps_flow

    flow = position.flow or {}
    # A top-up still with Relay is in no Hyperliquid balance yet.
    in_transit = sum((Decimal(c.amount_usd) for c in position.margin_changes.all()
                      if c.direction == 'add' and c.state == 'bridging'), Decimal(0))
    if position.state == 'open':
        used = (live or {}).get('marginUsed')
        # A top-up with Relay may already show on the venue: unknown, never counted twice.
        if used is None or in_transit > 0:
            return None
        return float(Decimal(str(used)) + free_usd)
    if position.state in ('funded', 'return_failed') or (
            position.state in ('closed', 'liquidated') and position.closed_at is not None):
        unapplied = sum((Decimal(str((c.flow or {}).get('credited') or '0'))
                         for c in position.margin_changes.all() if c.state == 'funded'), Decimal(0))
        return float(perps_flow.settled_equity(position) + unapplied + in_transit)
    if position.state == 'returning':
        out = (flow.get('return_pending') or {}).get('expected_out')
        return float(Decimal(int(out)) / Decimal(10 ** 18)) if out else None
    if position.state == 'landed':
        return float(Decimal(int(flow.get('landed_wei') or 0)) / Decimal(10 ** 18))
    if position.state == 'refunded':
        return float(Decimal(int(flow.get('refund_wei') or 0)) / Decimal(10 ** 18))
    return None


def _is_new_account(info) -> bool | None:
    from . import perps_flow

    wallet = _personal_wallet(info)
    if not wallet:
        return None
    try:
        return perps_flow._new_account(wallet)
    except perps_flow.FlowError:
        return None


def _triggers(position) -> tuple[float | None, float | None, bool]:
    from . import hyperliquid, perps_flow

    if position.state != 'open':
        return None, None, False
    try:
        orders = perps_flow.protections(position)
    except hyperliquid.HyperliquidError:
        return None, None, False
    tp = next((_float(o.get('triggerPx')) for o in orders if 'Take Profit' in str(o.get('orderType'))), None)
    sl = next((_float(o.get('triggerPx')) for o in orders if 'Stop' in str(o.get('orderType'))), None)
    return tp, sl, True


def _position_type(position, live: dict | None, contexts: dict, free_usd=Decimal(0)) -> PerpPositionType:
    from . import perps_catalog

    view = perps_catalog.view(position.market)
    ctx = contexts.get(position.market.coin) or {}
    put_in = Decimal(position.margin_usd) + sum(
        (Decimal(c.amount_usd) for c in position.margin_changes.all()
         if c.direction == 'add' and c.state not in ('quoted', 'failed', 'cancelled')), Decimal(0))
    result = None
    # Refunded top-ups came back too (net of the entry, as Comunidad counts them).
    from .perps_portfolio import _after_entry_fee
    refunded = sum((_after_entry_fee(Decimal(int((c.flow or {}).get('refund_wei') or 0)) / Decimal(10 ** 18))
                    for c in position.margin_changes.all() if c.direction == 'add' and c.state == 'refunded'),
                   Decimal(0))
    if position.state == 'done' and position.returned_usd is not None and position.open_batch_id:
        result = float(Decimal(position.returned_usd) + refunded - put_in)
    cum = ((live or {}).get('cumFunding') or {}).get('sinceOpen')
    triggers = _triggers(position)
    return PerpPositionType(
        id=position.id, coin=position.market.coin, ticker=view.ticker, name=view.name,
        asset_class=view.asset_class, side=position.side, leverage=position.leverage,
        margin_usd=float(position.margin_usd), state=position.state,
        step_error=position.step_error or None, next_action=_next_action(position),
        size=_float((live or {}).get('szi')), entry_px=_float((live or {}).get('entryPx') or position.entry_avg_px),
        mark_px=_float(ctx.get('mark_px')),
        unrealized_pnl_usd=_float((live or {}).get('unrealizedPnl')),
        return_on_equity=_float((live or {}).get('returnOnEquity')),
        liquidation_px=_float((live or {}).get('liquidationPx')),
        margin_used_usd=_float((live or {}).get('marginUsed')),
        value_usd=_value_usd(position, live, free_usd),
        take_profit_px=triggers[0], stop_loss_px=triggers[1], protection_known=triggers[2],
        pending_margin_usd=next((float(Decimal(str((c.flow or {}).get('credited') or '0')))
                                 for c in sorted(position.margin_changes.all(), key=lambda c: c.id)
                                 if c.direction == 'add' and c.state == 'funded'), None),
        position_value_usd=_float((live or {}).get('positionValue')),
        # Hyperliquid reports funding paid as positive; members read "paid" as negative.
        funding_usd=(-float(cum) if cum is not None else _float(position.funding)),
        realized_pnl_usd=_float(position.realized_pnl), venue_fees_usd=_float(position.venue_fees),
        returned_usd=_float(position.returned_usd), result_usd=result, put_in_usd=float(put_in - refunded),
        liquidation=position.liquidation or None, costs=_costs_type((position.flow or {}).get('costs')),
        created_at=position.created_at, opened_at=position.opened_at, closed_at=position.closed_at,
        done_at=position.done_at,
    )


class PerpStepType(graphene.ObjectType):
    purpose = graphene.String(required=True)
    action_json = graphene.String(required=True, description='Sign exactly this (fill "nonce" if null)')


_RELAY_QUOTE_DOC = ("Relay's raw signed quote behind this plan: the app proves the order (its id is the "
                    "hash of its terms, signed by Relay's solver) and signs only for that order")


class PerpPlanType(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String()
    relay_quote_json = graphene.String(description=_RELAY_QUOTE_DOC)
    steps = graphene.List(graphene.NonNull(PerpStepType))
    replan = graphene.Boolean(description='Ask for the plan again after these steps')
    impact_bps = graphene.Int()
    impact_warn = graphene.Boolean()
    avg_px = graphene.Float()
    size = graphene.Float()
    liquidation_px = graphene.Float()
    # Return leg (Relay): sign the nonce mapping, then the sendAsset.
    mapping_typed_json = graphene.String()
    send_action_json = graphene.String()
    return_usd = graphene.Float(description='USDT expected at the BSC address')
    return_min_usd = graphene.Float()


class PerpBatchPlanType(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String()
    relay_quote_json = graphene.String(description=_RELAY_QUOTE_DOC)
    position_id = graphene.ID()
    calls_json = graphene.String(description='[{to,value,data}] — sign exactly these')
    request_id = graphene.String()
    kind = graphene.String(description='Intent kind the batch is signed as')
    costs = graphene.Field(PerpCostsType)
    deadline = graphene.Int()


class Query(graphene.ObjectType):
    perps_capabilities = graphene.Field(PerpsCapabilitiesType)
    perps_markets = graphene.List(
        graphene.NonNull(PerpMarketType),
        description='Openable markets; null when Futuros is not available to this person',
    )
    perps_candles = graphene.List(
        graphene.NonNull(PerpCandleType), coin=graphene.String(required=True),
        range=graphene.String(default_value='1D', description='1D | 1W | 1M | 3M | 1Y'),
        description='Display-only price history; null = upstream failed',
    )
    perps_positions = graphene.List(
        graphene.NonNull(PerpPositionType),
        include_done=graphene.Boolean(default_value=False),
        description='Null = unknown (Hyperliquid unreadable); [] = none',
    )

    def resolve_perps_capabilities(self, info):
        from . import perps_flow, perps_risk
        from .crypto_policy import live_fee_bps
        from .eligibility import ONDO_POLICY, PERPS_POLICY, perps_promotion_blocked

        user = _user(info)
        if user is None:
            return None
        meta = _meta(info)
        try:
            decision = PERPS_POLICY.evaluate(user, meta)
        except Exception:  # noqa: BLE001 — refused, same as perps_risk.country_allowed
            decision = None
        try:
            fee = live_fee_bps()
        except Exception:  # noqa: BLE001 — unknown, the app hides the fee line
            fee = None
        funding = 'cusd_plus' if ONDO_POLICY.evaluate(user, meta).allowed else 'cusd'
        enabled = perps_risk.surfaces_enabled(user, meta) and _personal_wallet(info) is not None
        return PerpsCapabilitiesType(
            enabled=enabled,
            trading_enabled=perps_risk.trading_ready(),
            open_enabled=enabled and perps_risk.open_enabled(user, meta),
            ack_required=not perps_risk.acknowledged(user),
            ack_version=perps_risk.ACK_VERSION,
            disclosure_title=perps_risk.DISCLOSURE_TITLE,
            disclosure_points=list(perps_risk.DISCLOSURE_POINTS),
            promotion_allowed=enabled and not perps_promotion_blocked(user),
            funding_dollar=funding,
            fee_bps=fee,
            impact_warn_bps=int(getattr(settings, 'PERPS_IMPACT_WARN_BPS', 100)),
            impact_max_bps=int(getattr(settings, 'PERPS_IMPACT_MAX_BPS', 300)),
            slippage_bps=int(getattr(settings, 'PERPS_SLIPPAGE_BPS', 50)),
            min_margin_usd=float(perps_flow.MIN_MARGIN_USD),
            first_min_margin_usd=float(perps_flow.FIRST_MIN_MARGIN_USD),
            new_account_charge_usd=float(perps_flow.NEW_ACCOUNT_CHARGE_USD),
            new_account=_is_new_account(info) if enabled else None,
            blocked_message=(
                None if decision is not None and decision.allowed
                else decision.message if decision is not None
                else 'No pudimos confirmar tu país. Intenta de nuevo en unos minutos.'),
        )

    def resolve_perps_markets(self, info):
        from . import perps_catalog, perps_market_data, perps_risk

        user = _user(info)
        if user is None or not perps_risk.surfaces_enabled(user, _meta(info)):
            return None
        markets = perps_catalog.markets()
        ctx = perps_market_data.all_contexts(m.dex for m in markets)
        out = []
        for m in markets:
            c = ctx.get(m.coin)
            out.append(PerpMarketType(
                coin=m.coin, dex=m.dex, ticker=m.ticker, name=m.name, asset_class=m.asset_class,
                asset_id=m.asset_id, sz_decimals=m.sz_decimals, max_leverage=m.max_leverage,
                only_isolated=m.only_isolated, taker_fee_rate=float(m.taker_fee_rate),
                mark_px=_float((c or {}).get('mark_px')),
                day_change_pct=perps_market_data.day_change_pct(c),
                funding_rate=_float((c or {}).get('funding')),
                open_interest_usd=_float((c or {}).get('open_interest_usd')),
                day_volume_usd=_float((c or {}).get('day_volume_usd')),
            ))
        return out

    def resolve_perps_candles(self, info, coin, range='1D'):
        from . import hyperliquid, perps_catalog, perps_market_data

        user = _user(info)
        if user is None or range not in perps_market_data.RANGES or perps_catalog.by_coin(coin) is None:
            return []
        try:
            rows = perps_market_data.candles(coin, range)
        except hyperliquid.HyperliquidError:
            logger.warning('perps candles upstream failed for %s', coin)
            return None
        return [PerpCandleType(timestamp=float(r['timestamp']), close=r['close']) for r in rows]

    def resolve_perps_positions(self, info, include_done=False):
        from blockchain.models import PerpPosition

        from . import hyperliquid, perps_flow, perps_market_data

        user = _user(info)
        wallet = _personal_wallet(info) if user else None
        if user is None or wallet is None:
            return []
        rows = list(PerpPosition.objects.filter(user=user, wallet=wallet)
                    # A quote is not a position yet (an unsigned one left by a killed
                    # app is replaced by the next quote, or lapses).
                    .exclude(state__in=('cancelled', 'quoted')).select_related('market')
                    .prefetch_related('margin_changes').order_by('-created_at'))
        if not include_done:
            rows = [p for p in rows if p.state not in PerpPosition.TERMINAL_STATES]
        live_by_coin, free_by_dex = {}, {}
        dexes = {p.market.dex for p in rows if p.state in ('open', 'funded', 'bridging', 'closed', 'liquidated')}
        try:
            # Core too: with one live position per member, free USDC is its money.
            for dex in sorted(dexes | ({''} if dexes else set())):
                state = hyperliquid.clearinghouse_state(wallet, dex)
                free_by_dex[dex] = Decimal(str(state.get('withdrawable') or '0'))
                for entry in state['assetPositions']:
                    pos = entry.get('position') or {}
                    if pos.get('coin'):
                        live_by_coin[pos['coin']] = pos
        except hyperliquid.HyperliquidError:
            logger.warning('perps positions: Hyperliquid unreadable for %s', wallet)
            return None
        # In-flight rows move here too, so the app sees the next step at once.
        for position in rows:
            if position.state in ('bridging', 'open', 'returning', 'refunded'):
                try:
                    perps_flow.reconcile_position(position)
                except Exception:  # noqa: BLE001 — display read; the task reconciles too
                    logger.warning('perps inline reconcile failed for %s', position.id, exc_info=True)
        contexts = perps_market_data.all_contexts(p.market.dex for p in rows)
        return [_position_type(p, live_by_coin.get(p.market.coin) if p.state == 'open' else None, contexts,
                               free_usd=(free_by_dex.get('', Decimal(0))
                                         + (free_by_dex.get(p.market.dex, Decimal(0)) if p.market.dex else 0)))
                for p in rows]


def _flow_error(exc) -> str:
    from . import perps_flow, perps_relay

    if isinstance(exc, perps_flow.FlowError):
        return exc.code
    if isinstance(exc, perps_relay.RelayError):
        return 'relay_unavailable'
    return 'unavailable'


def _owned(info, position_id):
    """The JWT account must own the position (multi-account isolation)."""
    from blockchain.models import PerpPosition

    wallet = _personal_wallet(info)
    user = _user(info)
    if user is None or wallet is None:
        return False
    try:
        pk = int(position_id)
    except (TypeError, ValueError):
        return False
    return PerpPosition.objects.filter(pk=pk, user=user, wallet=wallet).exists()


def _batch_plan(result: dict) -> PerpBatchPlanType:
    return PerpBatchPlanType(
        success=True, position_id=result['position'].id, calls_json=json.dumps(result['calls']),
        request_id=result['request_id'], kind=result['kind'], costs=_costs_type(result.get('costs')),
        deadline=result.get('deadline'),
        relay_quote_json=json.dumps(result['relay_quote']) if result.get('relay_quote') else None)


class PerpsPrepareOpen(graphene.Mutation):
    class Arguments:
        coin = graphene.String(required=True)
        side = graphene.String(required=True)
        leverage = graphene.Int(required=True)
        margin_usd = graphene.String(required=True, description='Decimal string, dollars')

    Output = PerpBatchPlanType

    def mutate(self, info, coin, side, leverage, margin_usd):
        from . import perps_flow, perps_relay

        user = _user(info)
        wallet = _personal_wallet(info) if user else None
        if user is None or wallet is None:
            return PerpBatchPlanType(success=False, error='not_available')
        try:
            return _batch_plan(perps_flow.prepare_open(user, wallet, _meta(info), coin, side, leverage, margin_usd))
        except (perps_flow.FlowError, perps_relay.RelayError) as exc:
            return PerpBatchPlanType(success=False, error=_flow_error(exc))
        except Exception:  # noqa: BLE001
            logger.exception('perps prepare open failed')
            return PerpBatchPlanType(success=False, error='unavailable')


class PerpsPrepareMarginAdd(graphene.Mutation):
    class Arguments:
        position_id = graphene.ID(required=True)
        amount_usd = graphene.String(required=True)

    Output = PerpBatchPlanType

    def mutate(self, info, position_id, amount_usd):
        from . import perps_flow, perps_relay

        user = _user(info)
        if not _owned(info, position_id):
            return PerpBatchPlanType(success=False, error='position_not_found')
        try:
            return _batch_plan(perps_flow.prepare_margin_add(
                user, _personal_wallet(info), _meta(info), position_id, amount_usd))
        except (perps_flow.FlowError, perps_relay.RelayError) as exc:
            return PerpBatchPlanType(success=False, error=_flow_error(exc))
        except Exception:  # noqa: BLE001
            logger.exception('perps prepare margin add failed')
            return PerpBatchPlanType(success=False, error='unavailable')


class PerpsPrepareBridgeRetry(graphene.Mutation):
    class Arguments:
        position_id = graphene.ID(required=True)

    Output = PerpBatchPlanType

    def mutate(self, info, position_id):
        from . import perps_flow, perps_relay

        if not _owned(info, position_id):
            return PerpBatchPlanType(success=False, error='position_not_found')
        try:
            return _batch_plan(perps_flow.prepare_bridge_retry(_user(info), position_id))
        except (perps_flow.FlowError, perps_relay.RelayError) as exc:
            return PerpBatchPlanType(success=False, error=_flow_error(exc))
        except Exception:  # noqa: BLE001
            logger.exception('perps prepare retry failed')
            return PerpBatchPlanType(success=False, error='unavailable')


class PerpsPrepareEntry(graphene.Mutation):
    """The ordinary entry for proceeds that landed on BSC."""
    class Arguments:
        position_id = graphene.ID(required=True)

    Output = PerpBatchPlanType

    def mutate(self, info, position_id):
        from . import perps_flow

        if not _owned(info, position_id):
            return PerpBatchPlanType(success=False, error='position_not_found')
        try:
            result = perps_flow.entry_plan(_user(info), _meta(info), position_id)
        except perps_flow.FlowError as exc:
            return PerpBatchPlanType(success=False, error=exc.code)
        except Exception:  # noqa: BLE001
            logger.exception('perps entry plan failed')
            return PerpBatchPlanType(success=False, error='unavailable')
        return PerpBatchPlanType(success=True, position_id=result['position'].id,
                                 calls_json=json.dumps(result['calls']), request_id=result['request_id'],
                                 kind=result['kind'])


def _plan_type(result: dict) -> PerpPlanType:
    relay = result.get('relay') or {}
    return PerpPlanType(
        success=True,
        steps=[PerpStepType(purpose=s['purpose'], action_json=json.dumps(s['action'])) for s in result.get('steps', [])],
        replan=result.get('replan'), impact_bps=result.get('impact_bps'), impact_warn=result.get('impact_warn'),
        avg_px=_float(result.get('avg_px')), size=_float(result.get('size')),
        liquidation_px=_float(result.get('liquidation_px')),
        mapping_typed_json=json.dumps(result['mapping_typed']) if result.get('mapping_typed') else None,
        send_action_json=json.dumps(result['send_action']) if result.get('send_action') else None,
        relay_quote_json=json.dumps(result['relay_quote']) if result.get('relay_quote') else None,
        return_usd=(int(relay['expected_out']) / 10 ** 18) if relay.get('expected_out') else None,
        return_min_usd=(int(relay['minimum_out']) / 10 ** 18) if relay.get('minimum_out') else None,
    )


class PerpsPlan(graphene.Mutation):
    """The Hyperliquid steps for a stage: open | close | tpsl | margin | return."""
    class Arguments:
        position_id = graphene.ID(required=True)
        stage = graphene.String(required=True)
        take_profit_px = graphene.String()
        stop_loss_px = graphene.String()

    Output = PerpPlanType

    def mutate(self, info, position_id, stage, take_profit_px=None, stop_loss_px=None):
        from . import perps_flow, perps_relay

        user = _user(info)
        if not _owned(info, position_id):
            return PerpPlanType(success=False, error='position_not_found')
        try:
            if stage == 'open':
                result = perps_flow.open_plan(user, position_id, meta=_meta(info))
            elif stage == 'close':
                result = perps_flow.close_plan(user, position_id)
            elif stage == 'tpsl':
                result = perps_flow.tpsl_plan(user, position_id, take_profit_px, stop_loss_px)
            elif stage == 'return':
                result = perps_flow.return_plan(user, position_id)
            elif stage == 'margin':
                result = perps_flow.margin_plan(user, position_id)
            else:
                return PerpPlanType(success=False, error='bad_stage')
        except (perps_flow.FlowError, perps_relay.RelayError) as exc:
            return PerpPlanType(success=False, error=_flow_error(exc))
        except Exception:  # noqa: BLE001
            logger.exception('perps plan %s failed', stage)
            return PerpPlanType(success=False, error='unavailable')
        return _plan_type(result)


class PerpSignatureInput(graphene.InputObjectType):
    r = graphene.String(required=True)
    s = graphene.String(required=True)
    v = graphene.Int(required=True)


class PerpsSubmitAction(graphene.Mutation):
    class Arguments:
        position_id = graphene.ID(required=True)
        purpose = graphene.String(required=True)
        action_json = graphene.String(required=True)
        nonce = graphene.String(required=True)
        signature = PerpSignatureInput(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    state = graphene.String()

    def mutate(self, info, position_id, purpose, action_json, nonce, signature):
        from . import perps_flow

        if not _owned(info, position_id):
            return PerpsSubmitAction(success=False, error='position_not_found')
        try:
            result = perps_flow.submit_action(
                _user(info), position_id, purpose, action_json, int(nonce),
                {'r': signature.r, 's': signature.s, 'v': signature.v}, meta=_meta(info))
        except perps_flow.FlowError as exc:
            return PerpsSubmitAction(success=False, error=exc.code)
        except (TypeError, ValueError):
            return PerpsSubmitAction(success=False, error='bad_action')
        except Exception:  # noqa: BLE001
            logger.exception('perps submit action failed')
            return PerpsSubmitAction(success=False, error='unavailable')
        return PerpsSubmitAction(success=True, state=result['position'].state)


class PerpsSubmitReturn(graphene.Mutation):
    class Arguments:
        position_id = graphene.ID(required=True)
        mapping_signature = PerpSignatureInput(required=True)
        send_signature = PerpSignatureInput(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    state = graphene.String()

    def mutate(self, info, position_id, mapping_signature, send_signature):
        from . import perps_flow

        if not _owned(info, position_id):
            return PerpsSubmitReturn(success=False, error='position_not_found')
        sig = lambda s: {'r': s.r, 's': s.s, 'v': s.v}  # noqa: E731
        try:
            result = perps_flow.submit_return(_user(info), position_id, sig(mapping_signature), sig(send_signature))
        except perps_flow.FlowError as exc:
            return PerpsSubmitReturn(success=False, error=exc.code)
        except Exception:  # noqa: BLE001
            logger.exception('perps submit return failed')
            return PerpsSubmitReturn(success=False, error='unavailable')
        return PerpsSubmitReturn(success=True, state=result['position'].state)


class PerpsReleaseRefund(graphene.Mutation):
    """Keep the USDT Relay refunded: it returns to Confío dollars through
    the ordinary sweep."""
    class Arguments:
        position_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    def mutate(self, info, position_id):
        from . import perps_flow

        if not _owned(info, position_id):
            return PerpsReleaseRefund(success=False, error='position_not_found')
        try:
            perps_flow.release_refund(_user(info), position_id)
        except perps_flow.FlowError as exc:
            return PerpsReleaseRefund(success=False, error=exc.code)
        return PerpsReleaseRefund(success=True)


class PerpsCancelQuote(graphene.Mutation):
    """Drop an open quote the member never signed."""
    class Arguments:
        position_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    def mutate(self, info, position_id):
        from blockchain.models import PerpPosition

        if not _owned(info, position_id):
            return PerpsCancelQuote(success=False)
        PerpPosition.objects.filter(pk=position_id, user=_user(info), state='quoted').update(state='cancelled')
        return PerpsCancelQuote(success=True)


class AcknowledgePerpsRisk(graphene.Mutation):
    class Arguments:
        version = graphene.Int(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    def mutate(self, info, version):
        from . import perps_risk

        user = _user(info)
        if user is None:
            return AcknowledgePerpsRisk(success=False, error='AUTH_REQUIRED')
        if version != perps_risk.ACK_VERSION:
            return AcknowledgePerpsRisk(success=False, error='OUTDATED_DISCLOSURE')
        perps_risk.acknowledge(user)
        return AcknowledgePerpsRisk(success=True)


class Mutation(graphene.ObjectType):
    acknowledge_perps_risk = AcknowledgePerpsRisk.Field()
    perps_prepare_open = PerpsPrepareOpen.Field()
    perps_prepare_margin_add = PerpsPrepareMarginAdd.Field()
    perps_prepare_bridge_retry = PerpsPrepareBridgeRetry.Field()
    perps_prepare_entry = PerpsPrepareEntry.Field()
    perps_plan = PerpsPlan.Field()
    perps_submit_action = PerpsSubmitAction.Field()
    perps_submit_return = PerpsSubmitReturn.Field()
    perps_cancel_quote = PerpsCancelQuote.Field()
    perps_release_refund = PerpsReleaseRefund.Field()
