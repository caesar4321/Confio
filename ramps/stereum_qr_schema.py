import graphene
from graphql import GraphQLError

from . import stereum_qr
from .stereum_client import StereumClient, StereumError


class QrAvailability(graphene.ObjectType):
    enabled = graphene.Boolean(required=True)
    can_pay = graphene.Boolean(required=True)
    pending_request_id = graphene.UUID()


class QrPreview(graphene.ObjectType):
    request_id = graphene.UUID(required=True)
    recipient_name = graphene.String(required=True)
    bank_name = graphene.String(required=True)
    account_last4 = graphene.String(required=True)
    amount = graphene.String(required=True)
    fixed_amount = graphene.Boolean(required=True)
    currency = graphene.String(required=True)
    expires_on = graphene.String(required=True)


class QrPayment(graphene.ObjectType):
    request_id = graphene.UUID(required=True)
    status = graphene.String(required=True)


def payment_result(row):
    return QrPayment(request_id=row.request_id, status=row.status) if row else None


class DecodeStereumQr(graphene.Mutation):
    class Arguments:
        request_id = graphene.UUID(required=True)
        payload = graphene.String(required=True)
    Output = QrPreview

    @staticmethod
    def mutate(root, info, request_id, payload):
        try:
            return QrPreview(**stereum_qr.decode(stereum_qr.require_operator(info), request_id, payload))
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class PayStereumQr(graphene.Mutation):
    class Arguments:
        request_id = graphene.UUID(required=True)
        decode_request_id = graphene.UUID(required=True)
        amount = graphene.String(required=True)
    Output = QrPayment

    @staticmethod
    def mutate(root, info, request_id, decode_request_id, amount):
        try:
            return payment_result(stereum_qr.pay(stereum_qr.require_operator(info), request_id, decode_request_id, amount))
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class Query(graphene.ObjectType):
    stereum_qr_availability = graphene.Field(QrAvailability, required=True)
    stereum_qr_payment = graphene.Field(QrPayment, request_id=graphene.UUID(required=True))

    @staticmethod
    def resolve_stereum_qr_availability(root, info):
        try:
            user = stereum_qr.require_operator(info)
        except StereumError:
            return QrAvailability(enabled=False, can_pay=False)
        client = StereumClient()
        existing = stereum_qr.pending(user, client)
        return QrAvailability(enabled=True, can_pay=stereum_qr.can_pay(user, client),
            pending_request_id=existing.request_id if existing else None)

    @staticmethod
    def resolve_stereum_qr_payment(root, info, request_id):
        try:
            return payment_result(stereum_qr.payment(stereum_qr.require_operator(info), request_id, poll=True))
        except StereumError as exc:
            raise GraphQLError(str(exc)) from None


class Mutation(graphene.ObjectType):
    decode_stereum_qr = DecodeStereumQr.Field()
    pay_stereum_qr = PayStereumQr.Field()
