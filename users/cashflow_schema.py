"""GraphQL for the month summary ("Tu mes").

Isolated on purpose (one new query, no new fields on shared types): an
unknown field fails the WHOLE shared query on older servers, so the app asks
for this in its own request (see feedback-isolate-new-graphql-fields).
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

import graphene
from graphql import GraphQLError

from users.cashflow import SummaryUnavailable

logger = logging.getLogger(__name__)


def _usd(value):
    return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')


class CategoryAmountType(graphene.ObjectType):
    category = graphene.String(required=True, description="food|transport|home|bills|family|shopping|health|education|leisure|debt|work|other|uncategorized")
    amount_usd = graphene.String(required=True)


class MonthTotalsType(graphene.ObjectType):
    income_usd = graphene.String(required=True, description='Entró: income, sales, payroll received, bonuses')
    spending_usd = graphene.String(required=True, description='Salió: people, merchants, payroll paid, donations')
    top_ups_usd = graphene.String(required=True)
    withdrawals_usd = graphene.String(required=True)
    savings_net_usd = graphene.String(required=True, description='+ moved into savings, - withdrawn from savings')
    investment_net_usd = graphene.String(required=True, description='+ bought, - sold')
    movement_count = graphene.Int(required=True, description='Entró + Salió movements only')
    spending_by_category = graphene.List(
        graphene.NonNull(CategoryAmountType), required=True,
        description='Salió split by category, largest first, uncategorized always last')


class MonthCounterpartyType(graphene.ObjectType):
    key = graphene.String(required=True)
    name = graphene.String(required=True)
    received_usd = graphene.String(required=True)
    sent_usd = graphene.String(required=True)


class MonthSummaryType(graphene.ObjectType):
    year = graphene.Int(required=True)
    month = graphene.Int(required=True)
    timezone = graphene.String(required=True)
    current = graphene.Field(MonthTotalsType, required=True)
    previous = graphene.Field(MonthTotalsType, required=True)
    previous_is_partial = graphene.Boolean(
        required=True, description='True: same period of the previous month; False: the full previous month')
    counterparties = graphene.List(graphene.NonNull(MonthCounterpartyType), required=True)


def _totals(t):
    return MonthTotalsType(
        income_usd=_usd(t.income), spending_usd=_usd(t.spending),
        top_ups_usd=_usd(t.top_ups), withdrawals_usd=_usd(t.withdrawals),
        savings_net_usd=_usd(t.savings_net), investment_net_usd=_usd(t.investment_net),
        movement_count=t.movement_count,
        spending_by_category=_categories(t.spending_by_category),
    )


def _categories(by_category):
    named = sorted(((k, v) for k, v in by_category.items() if k != 'uncategorized'),
                   key=lambda kv: kv[1], reverse=True)
    if 'uncategorized' in by_category:
        named.append(('uncategorized', by_category['uncategorized']))
    return [CategoryAmountType(category=k, amount_usd=_usd(v)) for k, v in named]


class MonthMovementType(graphene.ObjectType):
    id = graphene.ID(required=True, description='Unified ledger row id (use for categorizeMovement)')
    kind = graphene.String(required=True)
    direction = graphene.String(required=True)
    amount_usd = graphene.String(required=True)
    category = graphene.String()
    counterparty_key = graphene.String()
    counterparty_name = graphene.String()
    date = graphene.DateTime(required=True)


def _summary_context(info, year, month, timezone):
    """(user, account, account_type, business_id, tz) for the month views, or
    None: owners only (employees never see the month), no future months."""
    from django.utils import timezone as dj_tz
    from users.cashflow import resolve_timezone
    from users.graphql_views import jwt_account
    from users.jwt_context import get_jwt_business_context_with_validation
    from users.models import Account

    user = info.context.user
    if not user or not user.is_authenticated:
        return None
    if not (1 <= int(month) <= 12) or not (2020 <= int(year) <= 2100):
        return None
    jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_transactions')
    if not jwt_context:
        return None
    account_type = jwt_context['account_type']
    business_id = jwt_context.get('business_id')
    if account_type == 'business':
        if not business_id or not Account.objects.filter(
                user=user, business_id=business_id, account_type='business',
                deleted_at__isnull=True).exists():
            return None
    account = jwt_account(user, jwt_context)
    if account is None:
        return None
    tz = resolve_timezone(timezone, getattr(user, 'phone_country', None))
    local_now = dj_tz.now().astimezone(tz)
    if (int(year), int(month)) > (local_now.year, local_now.month):
        return None
    return user, account, account_type, business_id, tz


class RecurringPaymentType(graphene.ObjectType):
    counterparty_key = graphene.String(required=True)
    name = graphene.String(required=True)
    expected_day = graphene.Int(required=True, description="Day of the viewed month (clamped to its length)")
    expected_amount_usd = graphene.String(required=True, description='Median monthly sum (an estimate)')
    category = graphene.String(description="The user's category for this counterparty, if any")


class MonthInsightsType(graphene.ObjectType):
    recurring = graphene.List(graphene.NonNull(RecurringPaymentType), required=True,
                              description='Habitual payments: seen in 2 of the 3 previous months, sorted by day')
    previous_month_spending_usd = graphene.String(
        required=True, description="The FULL previous month's Salió (pace caption and eligibility)")


class SavingsDayType(graphene.ObjectType):
    date = graphene.Date(required=True)
    usd = graphene.String(required=True, description='That day\'s accrual (6 decimals; bars are relative)')


class SavingsEarnedType(graphene.ObjectType):
    earned_usd = graphene.String(required=True, description='Estimate (daily accrual), 2 decimals')
    daily = graphene.List(graphene.NonNull(SavingsDayType), required=True,
                          description='Completed days only, oldest first')


class ProtectionValueType(graphene.ObjectType):
    currency = graphene.String(required=True, description='Local currency, e.g. BOB')
    basis = graphene.String(required=True, description="'purchase' (paid in Confío) | 'month_start' (value on the 1st)")
    state = graphene.String(required=True, description="'gained' (≥ US$1) | 'stable' (less, or reversed: never shown as a loss)")
    source = graphene.String(required=True, description='Rate source for "today" (binance_p2p)')
    protected_usd = graphene.String(required=True, description='Dollars bought in Confío still held (R13 replay, capped)')
    paid_local = graphene.String(required=True, description='purchase: what was paid; month_start: value on the 1st')
    today_local = graphene.String(required=True, description="Those dollars at today's Binance P2P rate")
    gain_local = graphene.String(required=True)
    avg_rate = graphene.String(required=True, description='purchase: average paid per USD; month_start: rate on the 1st')
    today_rate = graphene.String(required=True, description='Binance P2P local per USD (2 decimals)')
    quoted_at = graphene.String(required=True, description='ISO time the "today" rate was fetched')
    start_date = graphene.String(description="month_start: the baseline day (ISO date), usually the 1st")


class StockMoverType(graphene.ObjectType):
    ticker = graphene.String(required=True)
    name = graphene.String(required=True)
    change_pct = graphene.String(required=True, description='Price change over the viewed month, 2 decimals')


class StockMonthType(graphene.ObjectType):
    state = graphene.String(required=True, description="'gain' | 'value_only' (history incomplete: no month "
                                                       "gain) | 'settling' (a trade not final yet: today's value "
                                                       "only, ask again in seconds) | 'none' (no stocks this month)")
    can_buy = graphene.Boolean(required=True, description="'none' only: the invitation may offer a purchase "
                                                          "(false on every other state)")
    value_usd = graphene.String(required=True, description='Value at the end of the month (today on the current month)')
    value_start_usd = graphene.String(description='gain: value on the 1st')
    bought_usd = graphene.String(description='gain: Confío purchases this month (exact settlements, fees included)')
    sold_usd = graphene.String(description='gain: Confío sales this month (exact settlements)')
    gain_usd = graphene.String(description='gain: value_usd − value_start_usd − bought_usd + sold_usd')
    gain_pct = graphene.String(description='gain: over (value_start_usd + bought_usd), 2 decimals')
    top_mover = graphene.Field(StockMoverType, description='Held position whose price moved most this month')
    holdings = graphene.Int(required=True, description='Positions held at the end of the month')


class MonthSummaryQuery(graphene.ObjectType):
    month_summary = graphene.Field(
        MonthSummaryType,
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        timezone=graphene.String(description='Device IANA timezone; falls back to the phone country'),
        description='Month cash-flow summary for the active (JWT) account. Null for employees.',
    )

    month_movements = graphene.List(
        graphene.NonNull(MonthMovementType),
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        timezone=graphene.String(),
        filter_by=graphene.String(required=True,
                                  description='income | spending | category | uncategorized | counterparty | counterparties | own_money'),
        value=graphene.String(description='category key, or counterparty key'),
        description='The movements behind one number of monthSummary, newest first. Empty for employees.',
    )

    month_insights = graphene.Field(
        MonthInsightsType,
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        timezone=graphene.String(),
        description='Tu mes insights (habitual payments, full previous month Salió). Own query: '
                    'an older server without it fails only this request. Null for employees.',
    )

    savings_earned = graphene.Field(
        SavingsEarnedType,
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        description='"Tu ahorro ganó": cUSD+ earnings for a UTC month from daily snapshots. Null when '
                    'any needed snapshot is missing (never a fake zero). Own query. Null for employees.',
    )

    protection_value = graphene.Field(
        ProtectionValueType,
        timezone=graphene.String(description='Device IANA timezone; falls back to the phone country'),
        include_stable=graphene.Boolean(default_value=False,
                                        description="Return 'stable' results too. Off by default: an app that "
                                                    "doesn't know `state` would draw a stable result as a loss."),
        description='"Tu dólar te protegió" for the active personal account (current month, Binance P2P '
                    'today). Null whenever anything is unknown (fail closed). Own query.',
    )

    stock_month = graphene.Field(
        StockMonthType,
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        timezone=graphene.String(),
        description='"Tus acciones" in Tu mes: the month\'s gain net of Confío buys and sells. Null whenever '
                    'anything is unknown (fail closed) or stocks are not offered. Own query.',
    )

    def resolve_stock_month(self, info, year, month, timezone=None):
        from django.utils import timezone as dj_tz
        from cusd_plus.eligibility import stock_buy_overlay_allows
        from cusd_plus.schema import _stock_execution_ready, _stock_surfaces_enabled
        from cusd_plus.stock_month import stock_month
        from users.cashflow import month_window
        context = _summary_context(info, year, month, timezone)
        if context is None:
            return None
        user, account, _account_type, _business_id, tz = context
        meta = getattr(info.context, 'META', {})
        if not _stock_surfaces_enabled(user, meta):
            return None
        start, end = month_window(int(year), int(month), tz)
        try:
            result = stock_month(account.bsc_address or '', start, end, dj_tz.now())
        except Exception:  # noqa: BLE001 — an unknown hides the card, never a guess
            logger.warning('stock month unavailable for account %s', account.id, exc_info=True)
            return None
        if result is None:
            return None
        # Surfaces (issuer policy + kill switch) passed above; the buy overlay
        # and the execution rails are left (_stock_buy_enabled would re-run the
        # issuer policy). Same gates as stocksBuyEnabled: never invite to buy
        # while trading is off. The overlay is not free (phone + IP): last.
        can_buy = (result.state == 'none' and _stock_execution_ready()
                   and stock_buy_overlay_allows(user, meta))
        if result.state == 'none' and not can_buy:
            return None                      # nothing to show and nothing to offer
        # Dollars and percents alike: 2 decimals, half up.
        opt = lambda v: None if v is None else _usd(v)  # noqa: E731
        top = result.top
        gain, gain_pct = result.gain, result.gain_pct
        if gain is not None and None not in (result.value_start, result.bought, result.sold):
            # From the cents shown, so "¿Cómo lo calculamos?" adds up to the cent
            # and the percent never disagrees with the dollars beside it.
            cents = lambda v: v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # noqa: E731
            gain = (cents(result.value_end) - cents(result.value_start)
                    - cents(result.bought) + cents(result.sold))
            base = cents(result.value_start) + cents(result.bought)
            gain_pct = gain / base * 100 if base > 0 else None
        return StockMonthType(
            state=result.state, can_buy=can_buy, value_usd=_usd(result.value_end),
            value_start_usd=opt(result.value_start), bought_usd=opt(result.bought), sold_usd=opt(result.sold),
            gain_usd=opt(gain), gain_pct=opt(gain_pct), holdings=result.holdings,
            top_mover=StockMoverType(ticker=top.ticker, name=top.name, change_pct=_usd(top.change_pct)) if top else None)

    def resolve_protection_value(self, info, timezone=None, include_stable=False):
        from django.utils import timezone as dj_tz
        from users.cashflow import resolve_timezone
        from users.protection import protection_value
        user = info.context.user
        if not user or not user.is_authenticated:
            return None
        # The user's LOCAL month (a UTC month would already be next month on
        # the last evening in La Paz or Caracas).
        local = dj_tz.now().astimezone(resolve_timezone(timezone, getattr(user, 'phone_country', None)))
        context = _summary_context(info, local.year, local.month, timezone)
        if context is None:
            return None
        user, account, account_type, business_id, _tz = context
        try:
            p = protection_value(user, account, account_type, business_id, local.year, local.month)
        except Exception:  # noqa: BLE001 — an unknown hides the card, never a guess
            logger.warning('protection value unavailable for account %s', account.id, exc_info=True)
            return None
        if p is None or (p.state == 'stable' and not include_stable):
            return None
        two = lambda v: format(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')  # noqa: E731
        return ProtectionValueType(
            currency=p.currency, basis=p.basis, state=p.state, source='binance_p2p', protected_usd=_usd(p.protected_usd), paid_local=two(p.paid_local),
            today_local=two(p.today_local), gain_local=two(p.gain_local), avg_rate=two(p.avg_rate),
            today_rate=two(p.today_rate), quoted_at=p.quoted_at, start_date=p.start_date)

    def resolve_savings_earned(self, info, year, month):
        from cusd_plus.savings_snapshots import savings_earned
        context = _summary_context(info, year, month, None)
        if context is None:
            return None
        _user, account, _account_type, _business_id, _tz = context
        if not account.bsc_address:
            return None                      # savings never activated on this account
        result = savings_earned(account.id, int(year), int(month))
        if result is None:
            return None
        total, daily = result
        return SavingsEarnedType(
            earned_usd=_usd(total),
            daily=[SavingsDayType(date=d, usd=format(v.quantize(Decimal('0.000001')), 'f')) for d, v in daily])

    def resolve_month_insights(self, info, year, month, timezone=None):
        from users.cashflow import month_insights
        context = _summary_context(info, year, month, timezone)
        if context is None:
            return None
        user, account, account_type, business_id, tz = context
        try:
            result = month_insights(user, account, account_type, business_id, int(year), int(month), tz)
        except SummaryUnavailable as exc:
            # Never "no habitual payments" from data we couldn't read.
            logger.error('month insights unavailable for account %s: %s', account.id, exc)
            raise GraphQLError('El resumen del mes no está disponible.') from exc
        return MonthInsightsType(
            recurring=[RecurringPaymentType(
                counterparty_key=r.counterparty_key, name=r.name, expected_day=r.expected_day,
                expected_amount_usd=_usd(r.expected_amount), category=r.category) for r in result.recurring],
            previous_month_spending_usd=_usd(result.previous_month_spending))

    def resolve_month_movements(self, info, year, month, filter_by, timezone=None, value=None):
        from users.cashflow import month_movements
        context = _summary_context(info, year, month, timezone)
        if context is None:
            return []
        user, account, account_type, business_id, tz = context
        try:
            movements = month_movements(user, account, account_type, business_id, int(year), int(month), tz,
                                        filter_by, value)
        except SummaryUnavailable as exc:
            logger.error('month movements unavailable for account %s: %s', account.id, exc)
            raise GraphQLError('El resumen del mes no está disponible.') from exc
        return [MonthMovementType(
            id=m.row_id, kind=m.kind, direction=m.direction, amount_usd=_usd(m.amount), category=m.category,
            counterparty_key=m.counterparty_key, counterparty_name=m.counterparty_name or None, date=m.when)
            for m in movements]

    def resolve_month_summary(self, info, year, month, timezone=None):
        from django.utils import timezone as dj_tz
        from users.cashflow import summarize

        # Employees never see the month view (design scope rules); only the
        # Account owner of a business does.
        context = _summary_context(info, year, month, timezone)
        if context is None:
            return None
        user, account, account_type, business_id, tz = context
        now = dj_tz.now()
        try:
            result = summarize(user, account, account_type, business_id, int(year), int(month), tz, now=now)
        except SummaryUnavailable as exc:
            # Bad monetary evidence: fail visibly (the app shows "Reintentar"),
            # never a confident but wrong month.
            logger.error('month summary unavailable for account %s: %s', account.id, exc)
            raise GraphQLError('El resumen del mes no está disponible.') from exc
        return MonthSummaryType(
            year=result.year, month=result.month, timezone=str(tz),
            current=_totals(result.current), previous=_totals(result.previous),
            previous_is_partial=result.previous_is_partial,
            counterparties=[
                MonthCounterpartyType(key=c.key, name=c.name or '',
                                      received_usd=_usd(c.received), sent_usd=_usd(c.sent))
                for c in result.counterparties
            ],
        )


# ---- spending categories: success-screen chips and later edits (T3) ----

def _label_context(info):
    """(user, account, account_type, business_id) when the caller may label
    this account's spending: the owner, or (business) an employee with
    view_analytics (eng R3/R4), enforced here as well as in the UI."""
    from users.graphql_views import jwt_account
    from users.jwt_context import get_jwt_business_context_with_validation
    user = info.context.user
    if not user or not user.is_authenticated:
        return None
    jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_analytics')
    if not jwt_context:
        return None
    account = jwt_account(user, jwt_context)
    if account is None:
        return None
    return user, account, jwt_context['account_type'], jwt_context.get('business_id')


def _labelable(info, movement_id, internal_id):
    """(context, row, movement) for a spending movement of this account."""
    from users.cashflow import SPENDING_KINDS, resolve_movement
    context = _label_context(info)
    if context is None:
        return None, None, None
    user, account, account_type, business_id = context
    row, movement = resolve_movement(user, account, account_type, business_id,
                                     movement_id=movement_id, internal_id=internal_id)
    if row is None or movement is None or movement.kind not in SPENDING_KINDS:
        return context, None, None
    return context, row, movement


class CategoryPromptType(graphene.ObjectType):
    should_ask = graphene.Boolean(required=True)
    category = graphene.String(description='Current category if already labeled (override or counterparty rule)')
    counterparty_name = graphene.String()


class CategoryPromptQuery(graphene.ObjectType):
    category_prompt = graphene.Field(
        CategoryPromptType, movement_id=graphene.ID(), internal_id=graphene.String(),
        description='Should the success screen ask "¿Qué fue este pago?" for this payment?')

    def resolve_category_prompt(self, info, movement_id=None, internal_id=None):
        from users.models_cashflow import CounterpartyPromptState
        context, row, movement = _labelable(info, movement_id, internal_id)
        if movement is None:
            return CategoryPromptType(should_ask=False)
        if movement.category or not movement.counterparty_key:
            return CategoryPromptType(should_ask=False, category=movement.category,
                                      counterparty_name=movement.counterparty_name or None)
        account = context[1]
        state = CounterpartyPromptState.objects.filter(
            account=account, counterparty_key=movement.counterparty_key).first()
        return CategoryPromptType(should_ask=not (state and state.exhausted),
                                  counterparty_name=movement.counterparty_name or None)


class CategorizeMovement(graphene.Mutation):
    """Label a spending movement. apply_to='counterparty' labels every past
    and future payment to that counterparty (rule, R20); 'movement' labels
    only this one (override)."""

    class Arguments:
        category = graphene.String(required=True)
        apply_to = graphene.String(required=True, description='counterparty | movement')
        movement_id = graphene.ID()
        internal_id = graphene.String()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    category = graphene.String()

    @classmethod
    def mutate(cls, root, info, category, apply_to, movement_id=None, internal_id=None):
        from users.models_cashflow import CATEGORY_KEYS, CounterpartyRule, MovementOverride
        if category not in CATEGORY_KEYS or apply_to not in ('counterparty', 'movement'):
            return cls(success=False, error='invalid_input')
        context, row, movement = _labelable(info, movement_id, internal_id)
        if context is None:
            return cls(success=False, error='not_allowed')
        if movement is None:
            return cls(success=False, error='not_found')
        user, account = context[0], context[1]
        if apply_to == 'counterparty':
            if not movement.counterparty_key:
                return cls(success=False, error='no_counterparty')
            CounterpartyRule.objects.update_or_create(
                account=account, counterparty_key=movement.counterparty_key,
                defaults={'category': category, 'created_by': user})
        else:
            MovementOverride.objects.update_or_create(
                account=account, movement=row, defaults={'category': category, 'created_by': user})
        return cls(success=True, category=category)


class RecordCategoryPrompt(graphene.Mutation):
    """'Ahora no' = skipped (stops after 2), left without answering =
    dismissed (stops after 3), per counterparty (design D11)."""

    class Arguments:
        outcome = graphene.String(required=True, description='skipped | dismissed')
        movement_id = graphene.ID()
        internal_id = graphene.String()

    success = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, outcome, movement_id=None, internal_id=None):
        from django.db.models import F
        from users.models_cashflow import CounterpartyPromptState
        if outcome not in ('skipped', 'dismissed'):
            return cls(success=False)
        context, row, movement = _labelable(info, movement_id, internal_id)
        if movement is None or not movement.counterparty_key:
            return cls(success=False)
        state, _ = CounterpartyPromptState.objects.get_or_create(
            account=context[1], counterparty_key=movement.counterparty_key)
        field = 'skip_count' if outcome == 'skipped' else 'dismiss_count'
        CounterpartyPromptState.objects.filter(pk=state.pk).update(**{field: F(field) + 1})
        return cls(success=True)


class CategoryMutations(graphene.ObjectType):
    categorize_movement = CategorizeMovement.Field()
    record_category_prompt = RecordCategoryPrompt.Field()
