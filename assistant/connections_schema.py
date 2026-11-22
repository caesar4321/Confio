"""Discovery GraphQL. The names hold "AssistantMail", so both request logs redact them (they carry an address)."""
import logging

import graphene
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models

from . import connections

logger = logging.getLogger(__name__)


class AssistantMailConnectionsType(graphene.ObjectType):
    gmail = graphene.String(required=True, description=(
        'soon | request | full | left | waiting | waiting_full | invited | connected | reconnect | paused'))
    gmail_answered = graphene.Boolean(required=True)
    google_email = graphene.String(description='The account they asked with: the only one Google lets in')
    suggested_email = graphene.String()
    calendar = graphene.String(required=True, description='soon | waiting')
    calendar_answered = graphene.Boolean(required=True)


class Query(graphene.ObjectType):
    assistant_mail_connections = graphene.Field(AssistantMailConnectionsType, description='Null: show nothing')

    @login_required
    def resolve_assistant_mail_connections(self, info):
        user, account, _business, jwt_context = get_context_models(info)
        try:
            data = connections.overview(user, account, jwt_context)
        except Exception as exc:  # noqa: BLE001 - a card is never worth an error
            logger.warning('Connections overview failed: %s', type(exc).__name__)
            return None
        return AssistantMailConnectionsType(**data) if data else None


class AnswerAssistantMailConnection(graphene.Mutation):
    class Arguments:
        feature = graphene.String(required=True, description='gmail | calendar')
        wants = graphene.Boolean(required=True)
        google_email = graphene.String()

    success = graphene.Boolean(required=True)
    error = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, feature, wants, google_email=''):
        user, account, _business, jwt_context = get_context_models(info)
        try:
            connections.answer(user, account, jwt_context, feature, wants, google_email)
        except connections.ConnectionRefused as exc:
            return cls(success=False, error=exc.message)
        return cls(success=True)


class Mutation(graphene.ObjectType):
    answer_assistant_mail_connection = AnswerAssistantMailConnection.Field()
