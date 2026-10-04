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
    category = graphene.String(required=True, description="food|transport|home|family|work|other|uncategorized")
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


class MonthSummaryQuery(graphene.ObjectType):
    month_summary = graphene.Field(
        MonthSummaryType,
        year=graphene.Int(required=True),
        month=graphene.Int(required=True),
        timezone=graphene.String(description='Device IANA timezone; falls back to the phone country'),
        description='Month cash-flow summary for the active (JWT) account. Null for employees.',
    )

    def resolve_month_summary(self, info, year, month, timezone=None):
        from django.utils import timezone as dj_tz
        from users.cashflow import resolve_timezone, summarize
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
            # Employees never see the month view (design scope rules); only
            # the Account owner of the business does.
            if not business_id or not Account.objects.filter(
                    user=user, business_id=business_id, account_type='business',
                    deleted_at__isnull=True).exists():
                return None
        account = jwt_account(user, jwt_context)
        if account is None:
            return None
        tz = resolve_timezone(timezone, getattr(user, 'phone_country', None))
        now = dj_tz.now()
        local_now = now.astimezone(tz)
        if (int(year), int(month)) > (local_now.year, local_now.month):
            return None  # no future months
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
