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


class MonthTotalsType(graphene.ObjectType):
    income_usd = graphene.String(required=True, description='Entró: income, sales, payroll received, bonuses')
    spending_usd = graphene.String(required=True, description='Salió: people, merchants, payroll paid, donations')
    top_ups_usd = graphene.String(required=True)
    withdrawals_usd = graphene.String(required=True)
    savings_net_usd = graphene.String(required=True, description='+ moved into savings, - withdrawn from savings')
    investment_net_usd = graphene.String(required=True, description='+ bought, - sold')
    movement_count = graphene.Int(required=True, description='Entró + Salió movements only')


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
    )


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
