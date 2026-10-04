"""Personal-account APIs for sandbox onboarding. No caller-supplied user IDs."""
import graphene
from graphql import GraphQLError

from .stereum_client import StereumError
from .stereum_customers import access, onboard, onboarding_status
from .stereum_service import execute
from . import stereum_qr_schema


def personal_user(info):
    user = info.context.user
    access(user)
    from users.jwt_context import get_jwt_business_context_with_validation
    context = get_jwt_business_context_with_validation(info)
    if not context or context.get('account_type') != 'personal':
        raise StereumError('Stereum customer onboarding requires a personal account context.')
    return user


class StereumCustomerResult(graphene.ObjectType):
    status = graphene.String(required=True)
    error = graphene.String()


class StereumCustomerInput(graphene.InputObjectType):
    state_of_residence = graphene.String(required=True)
    economic_activity = graphene.String(required=True)
    source_of_funds = graphene.String(required=True)
    destination_of_funds = graphene.String(required=True)
    income_level = graphene.String(required=True)
    surname1 = graphene.String()
    surname2 = graphene.String()
    complement_number = graphene.String()


class OnboardStereumCustomer(graphene.Mutation):
    class Arguments:
        details = StereumCustomerInput(required=True)
        consent = graphene.Boolean(required=True)

    Output = StereumCustomerResult

    @staticmethod
    def mutate(root, info, details, consent):
        try:
            record = onboard(personal_user(info), dict(details), consent=consent)
            return StereumCustomerResult(status=record.status, error=record.error)
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class StereumQuoteResult(graphene.ObjectType):
    request_id = graphene.UUID(required=True)
    status = graphene.String(required=True)
    error = graphene.String()
    quote = graphene.JSONString()


class CreateStereumCustomerQuote(graphene.Mutation):
    class Arguments:
        request_id = graphene.UUID(required=True)
        side = graphene.String(required=True)
        amount = graphene.String(required=True)
        currency = graphene.String(default_value='USDT')

    Output = StereumQuoteResult

    @staticmethod
    def mutate(root, info, request_id, side, amount, currency='USDT'):
        try:
            record = execute(personal_user(info), 'customer_quote',
                {'side': side, 'amount': amount, 'currency': currency}, request_id)
            return StereumQuoteResult(request_id=record.request_id, status=record.status,
                error=record.error, quote=record.response_data)
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class Query(stereum_qr_schema.Query, graphene.ObjectType):
    stereum_customer_status = graphene.Field(StereumCustomerResult)

    @staticmethod
    def resolve_stereum_customer_status(root, info):
        try:
            record = onboarding_status(personal_user(info))
            return StereumCustomerResult(status=record.status if record else 'not_registered', error=record.error if record else '')
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class Mutation(stereum_qr_schema.Mutation, graphene.ObjectType):
    onboard_stereum_customer = OnboardStereumCustomer.Field()
    create_stereum_customer_quote = CreateStereumCustomerQuote.Field()
