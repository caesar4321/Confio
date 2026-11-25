"""Gmail pilot GraphQL. Every operation name holds "AssistantMail": the request logs redact on it."""
import logging
import uuid

import graphene
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models

from . import compose, config, limits, oauth, service
from .errors import MailRefused

logger = logging.getLogger(__name__)
FAILED = 'No pude completar eso con tu correo. Inténtalo de nuevo.'


class AssistantMailNeedType(graphene.ObjectType):
    id = graphene.ID(required=True)
    kind = graphene.String(
        required=True,
        description='payment | ticket | trip | deadline | reply | appointment | delivery | money')
    due_date = graphene.Date()
    amount = graphene.String(description='As the mail said it: never prefill a payment with it')
    currency = graphene.String()
    summary = graphene.String(description='One line about the mail, written by a model: show it as a claim')


class AssistantMailEventType(graphene.ObjectType):
    title = graphene.String(required=True)
    day = graphene.Date(required=True, description="In the person's own timezone")
    starts_at = graphene.DateTime(description='Null for an all-day event')
    all_day = graphene.Boolean(required=True)


class AssistantMailSourceType(graphene.ObjectType):
    handle = graphene.String(required=True, description='Opaque: pass it back to reply')
    sender = graphene.String(required=True)
    subject = graphene.String(required=True)
    sent_at = graphene.DateTime(required=True)


class AssistantMailDraftType(graphene.ObjectType):
    id = graphene.ID(description='Null when there is nothing to send with: open the phone composer')
    sender = graphene.String()
    to = graphene.String(required=True)
    subject = graphene.String(required=True)
    body = graphene.String(required=True)
    is_reply = graphene.Boolean(required=True)
    reply_to_differs = graphene.Boolean(required=True)
    can_send = graphene.Boolean(required=True)
    display_hash = graphene.String(required=True)


class AssistantMailType(graphene.ObjectType):
    available = graphene.Boolean(required=True)
    connected = graphene.Boolean(required=True)
    needs_reconnect = graphene.Boolean(required=True)
    can_send = graphene.Boolean(required=True)
    can_calendar = graphene.Boolean(required=True)
    consent_outdated = graphene.Boolean(required=True, description='Show the consent text again before reconnecting')
    consent_version = graphene.Int(description='What the connection was accepted under: an app with newer text asks again')
    email = graphene.String()
    needs = graphene.List(graphene.NonNull(AssistantMailNeedType), required=True)


class Query(graphene.ObjectType):
    assistant_mail = graphene.Field(AssistantMailType)

    @login_required
    def resolve_assistant_mail(self, info):
        user, account, _business, jwt_context = get_context_models(info)
        try:
            data = service.overview(user, account, jwt_context)
        except Exception as exc:  # noqa: BLE001 - by type only
            logger.warning('Gmail overview failed: %s', type(exc).__name__)
            return None
        needs = [AssistantMailNeedType(**need) for need in data.pop('needs')]
        return AssistantMailType(**data, needs=needs)


class _Result:
    success = graphene.Boolean(required=True)
    error = graphene.String()
    error_code = graphene.String()


def _run(cls, info, action, *, needs_pilot=True):
    user, account, _business, jwt_context = get_context_models(info)
    try:
        permitted = (config.allowed(user, account, jwt_context) if needs_pilot
                     else config.is_personal(account, jwt_context))
        if not permitted:
            raise MailRefused('unavailable', 'El correo en Confío IA todavía no está disponible.')
        return cls(success=True, **action(user))
    except MailRefused as exc:
        return cls(success=False, error=exc.message, error_code=exc.code)
    except Exception as exc:  # noqa: BLE001 - by type only: a message can quote mail
        logger.warning('%s failed: %s', cls.__name__, type(exc).__name__)
        return cls(success=False, error=FAILED, error_code='error')


def _connected(user):
    connection = service.connection_of(user)
    if connection is None:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    return connection


def _draft_id(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise MailRefused('not_found', 'Ese borrador ya no existe.') from None


class StartAssistantMailConnect(_Result, graphene.Mutation):
    class Arguments:
        consent_version = graphene.Int(required=True)

    auth_url = graphene.String()
    verifier = graphene.String(description='Keep on the phone; send it back to finish')

    @classmethod
    @login_required
    def mutate(cls, root, info, consent_version):
        def action(user):
            limits.claim(user, 'connect')
            url, verifier = oauth.start(user, consent_version)
            return {'auth_url': url, 'verifier': verifier}
        return _run(cls, info, action)


class CompleteAssistantMailConnect(_Result, graphene.Mutation):
    class Arguments:
        code = graphene.String(required=True)
        state = graphene.String(required=True)
        verifier = graphene.String(required=True)

    can_send = graphene.Boolean()

    @classmethod
    @login_required
    def mutate(cls, root, info, code, state, verifier):
        return _run(cls, info, lambda user: {'can_send': oauth.complete(user, code, state, verifier).can_send})


class DisconnectAssistantMail(_Result, graphene.Mutation):
    revoked = graphene.Boolean(description='False: also remove Confío at myaccount.google.com/permissions')

    @classmethod
    @login_required
    def mutate(cls, root, info):
        def action(user):
            connection = service.connection_of(user)
            return {'revoked': oauth.disconnect(connection) if connection else True}
        # Leaving always works, also off the tester list.
        return _run(cls, info, action, needs_pilot=False)


class AskAssistantMail(_Result, graphene.Mutation):
    class Arguments:
        question = graphene.String(required=True)

    answer = graphene.String()
    sources = graphene.List(graphene.NonNull(AssistantMailSourceType))

    @classmethod
    @login_required
    def mutate(cls, root, info, question):
        def action(user):
            found = service.ask(user, question)
            return {'answer': found['answer'], 'sources': [AssistantMailSourceType(**s) for s in found['sources']]}
        return _run(cls, info, action)


class ShowAssistantMailNeed(_Result, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    source = graphene.Field(AssistantMailSourceType)

    @classmethod
    @login_required
    def mutate(cls, root, info, id):
        return _run(cls, info, lambda user: {'source': AssistantMailSourceType(**service.need_source(user, id))})


class DismissAssistantMailNeed(_Result, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, id):
        def action(user):
            service.dismiss(user, id)
            return {}
        return _run(cls, info, action)


class DraftAssistantMail(_Result, graphene.Mutation):
    class Arguments:
        instructions = graphene.String(required=True)
        to = graphene.String(description='Typed by the person. Ignored for a reply.')
        source = graphene.String()

    draft = graphene.Field(AssistantMailDraftType)

    @classmethod
    @login_required
    def mutate(cls, root, info, instructions, to=None, source=None):
        def action(user):
            asked = service.words(instructions)
            limits.claim(user, 'draft')
            draft = compose.create(service.connection_of(user), asked, to=to, source=source)
            return {'draft': AssistantMailDraftType(**draft)}
        return _run(cls, info, action)


class UpdateAssistantMailDraft(_Result, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        to = graphene.String(required=True)
        subject = graphene.String(required=True)
        body = graphene.String(required=True)

    draft = graphene.Field(AssistantMailDraftType)

    @classmethod
    @login_required
    def mutate(cls, root, info, id, to, subject, body):
        return _run(cls, info, lambda user: {'draft': AssistantMailDraftType(
            **compose.update(_connected(user), _draft_id(id), to, subject, body))})


class SendAssistantMailDraft(_Result, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        display_hash = graphene.String(required=True, description='Of exactly what the confirmation showed')

    @classmethod
    @login_required
    def mutate(cls, root, info, id, display_hash):
        def action(user):
            connection, draft = _connected(user), _draft_id(id)
            limits.claim(user, 'send')
            compose.send(connection, draft, display_hash)
            if config.chat_consented(connection):
                from . import chat
                chat.sent(user, draft)
            return {}
        return _run(cls, info, action)


class PrepareAssistantMailReply(_Result, graphene.Mutation):
    """From the "Responder…" chip in the conversation: what she wants to say, written into a card there."""

    class Arguments:
        need_id = graphene.ID(required=True)
        instructions = graphene.String(required=True)

    draft = graphene.Field(AssistantMailDraftType)

    @classmethod
    @login_required
    def mutate(cls, root, info, need_id, instructions):
        def action(user):
            from . import chat
            asked = service.words(instructions)
            limits.claim(user, 'draft')
            return {'draft': AssistantMailDraftType(**chat.prepare(user, asked, need_id=need_id))}
        return _run(cls, info, action)


class ShowAssistantMailDraft(_Result, graphene.Mutation):
    """The card in the conversation. A mutation: never cached in the app's store."""

    class Arguments:
        id = graphene.ID(required=True)

    draft = graphene.Field(AssistantMailDraftType)

    @classmethod
    @login_required
    def mutate(cls, root, info, id):
        return _run(cls, info, lambda user: {'draft': AssistantMailDraftType(
            **compose.show(_connected(user), _draft_id(id)))})


class ShowAssistantMailAgenda(_Result, graphene.Mutation):
    """A mutation on purpose: it calls Google, is counted, and must never be cached or batched with a query."""

    events = graphene.List(graphene.NonNull(AssistantMailEventType))

    @classmethod
    @login_required
    def mutate(cls, root, info):
        return _run(cls, info, lambda user: {
            'events': [AssistantMailEventType(**event) for event in service.agenda(user)]})


class Mutation(graphene.ObjectType):
    prepare_assistant_mail_reply = PrepareAssistantMailReply.Field()
    show_assistant_mail_draft = ShowAssistantMailDraft.Field()
    show_assistant_mail_agenda = ShowAssistantMailAgenda.Field()
    start_assistant_mail_connect = StartAssistantMailConnect.Field()
    complete_assistant_mail_connect = CompleteAssistantMailConnect.Field()
    disconnect_assistant_mail = DisconnectAssistantMail.Field()
    ask_assistant_mail = AskAssistantMail.Field()
    show_assistant_mail_need = ShowAssistantMailNeed.Field()
    dismiss_assistant_mail_need = DismissAssistantMailNeed.Field()
    draft_assistant_mail = DraftAssistantMail.Field()
    update_assistant_mail_draft = UpdateAssistantMailDraft.Field()
    send_assistant_mail_draft = SendAssistantMailDraft.Field()
