"""WhatsApp link GraphQL. Every field and operation holds "WhatsApp": the request logs redact on it."""
import logging
import uuid

import graphene
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models

from . import service
from .service import LinkRefused

logger = logging.getLogger(__name__)
FAILED = 'No pude completar eso con tu WhatsApp. Inténtalo de nuevo.'


class WhatsAppNoticeType(graphene.ObjectType):
    id = graphene.ID(required=True)
    kind = graphene.String(required=True, description='payment | order | delivery | appointment | reply | urgent')
    chat = graphene.String(required=True, description="The chat's name as WhatsApp shows it")
    preview = graphene.String(required=True, description="WhatsApp's one-line preview: third-party text")
    summary = graphene.String(required=True, description='Written by a model: show it as a claim')
    time = graphene.String(required=True)
    created_at = graphene.DateTime(required=True)


class WhatsAppLinkType(graphene.ObjectType):
    state = graphene.String(required=True, description='none | pairing | linked | gone | failed')
    code = graphene.String(description='While pairing: the 8 characters to type in WhatsApp, as ABCD-EFGH')
    code_at = graphene.DateTime()
    phone_hint = graphene.String(description='Last four digits of the linked number')
    reason = graphene.String()
    reason_message = graphene.String(description='Show verbatim')
    linked_at = graphene.DateTime()
    last_sync_at = graphene.DateTime()
    own_phone_hint = graphene.String(description='Deprecated: use suggestedPhone')
    suggested_phone = graphene.String(description="The account's number, to prefill the field (+digits). Never a proof")
    consent_version = graphene.Int(required=True, description='Show the consent text of this version, then send it back')
    consent_outdated = graphene.Boolean(required=True, description='Linked under an older text: reads wait for acceptWhatsAppConsent')
    notices = graphene.List(graphene.NonNull(WhatsAppNoticeType), required=True)


class WhatsAppDraftType(graphene.ObjectType):
    id = graphene.ID(required=True)
    chat = graphene.String()
    phone = graphene.String()
    body = graphene.String(required=True)
    status = graphene.String(required=True, description='draft | sending | sent | unknown | failed')
    reason = graphene.String(description='Why the last try did not send: show verbatim')
    display_hash = graphene.String(required=True, description='Send back with sendWhatsAppDraft')


def _check(info):
    user, account, _business, jwt_context = get_context_models(info)
    service.allowed(user, account, jwt_context)
    return user


def _link_type(data):
    code = data.get('code')
    if code:
        data['code'] = f'{code[:4]}-{code[4:]}'
    return WhatsAppLinkType(**{**data, 'notices': [WhatsAppNoticeType(**n) for n in data['notices']]})


class Query(graphene.ObjectType):
    whats_app_link = graphene.Field(WhatsAppLinkType)
    whats_app_draft = graphene.Field(WhatsAppDraftType, id=graphene.ID(required=True))

    @login_required
    def resolve_whats_app_link(self, info):
        try:
            user, account, _business, jwt_context = get_context_models(info)
            if account is None or (jwt_context or {}).get('account_type') != 'personal':
                return None
            # Shown with the kill switch off too: the person must always see it, to unlink.
            return _link_type(service.status(user))
        except LinkRefused:
            return None
        except Exception as exc:  # noqa: BLE001 - by type only
            logger.warning('WhatsApp status failed: %s', type(exc).__name__)
            return None

    @login_required
    def resolve_whats_app_draft(self, info, id):
        try:
            # Not behind the kill switch: a send that was running must still show how it ended.
            return WhatsAppDraftType(**service.get_draft(info.context.user, _uuid(id)))
        except Exception:  # noqa: BLE001
            return None


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise LinkRefused('not_found') from None


class _Result:
    success = graphene.Boolean(required=True)
    error = graphene.String()
    error_code = graphene.String()


def _run(cls, info, action):
    try:
        return cls(success=True, **(action(_check(info)) or {}))
    except LinkRefused as exc:
        return cls(success=False, error=exc.message, error_code=exc.code)
    except Exception as exc:  # noqa: BLE001 - by type only: a message can quote a chat
        logger.warning('%s failed: %s', cls.__name__, type(exc).__name__)
        return cls(success=False, error=FAILED, error_code='error')


class StartWhatsAppLink(_Result, graphene.Mutation):
    """Asks WhatsApp for a pairing code for the number the person typed (with its country code, starting with +),
    and answers once the code is there. Poll whatsAppLink every 2-3 s while state is pairing: the code may
    change, and the state turns linked."""

    class Arguments:
        phone = graphene.String()  # optional in the schema: a missing one gets the person's message, not an error
        consent_version = graphene.Int(required=True)
        country = graphene.String()  # the ISO country picked with the number (tells +1 countries apart)

    @classmethod
    @login_required
    def mutate(cls, root, info, consent_version, phone=None, country=None):
        return _run(cls, info, lambda user: service.start_link(user, phone, consent_version, country or '') and None)


class AcceptWhatsAppConsent(_Result, graphene.Mutation):
    class Arguments:
        consent_version = graphene.Int(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, consent_version):
        return _run(cls, info, lambda user: service.accept_consent(user, consent_version))


class UnlinkWhatsApp(_Result, graphene.Mutation):
    """Leaving is never gated: not by the kill switch, nor by which account is active."""

    @classmethod
    @login_required
    def mutate(cls, root, info):
        try:
            service.unlink(info.context.user)  # the signed-in person, whatever account is active
            return cls(success=True)
        except Exception as exc:  # noqa: BLE001 - by type only
            logger.warning('UnlinkWhatsApp failed: %s', type(exc).__name__)
            return cls(success=False, error=FAILED, error_code='error')


class RefreshWhatsApp(_Result, graphene.Mutation):
    """Call when Confío IA opens: reads the chat list again if the last read is older than 15 minutes."""
    queued = graphene.Boolean()

    @classmethod
    @login_required
    def mutate(cls, root, info):
        return _run(cls, info, lambda user: {'queued': service.refresh(user)})


class DismissWhatsAppNotice(_Result, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, id):
        return _run(cls, info, lambda user: service.dismiss(user, id))


class _DraftResult(_Result):
    draft = graphene.Field(WhatsAppDraftType)


def _draft(data):
    return {'draft': WhatsAppDraftType(**data)}


class CreateWhatsAppDraft(_DraftResult, graphene.Mutation):
    """One of chat (exact name), phone or noticeId; body as written, or instructions for Confío IA to write it."""

    class Arguments:
        chat = graphene.String()
        phone = graphene.String()
        notice_id = graphene.ID()
        body = graphene.String()
        instructions = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, chat=None, phone=None, notice_id=None, body=None, instructions=None):
        return _run(cls, info, lambda user: _draft(service.create_draft(
            user, chat=chat, phone=phone, notice_id=notice_id, body=body, instructions=instructions)))


class UpdateWhatsAppDraft(_DraftResult, graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        body = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, id, body):
        return _run(cls, info, lambda user: _draft(service.update_draft(user, _uuid(id), body)))


class SendWhatsAppDraft(_DraftResult, graphene.Mutation):
    """The person tapped Enviar on exactly what displayHash covers. Poll whatsAppDraft until it is not sending."""

    class Arguments:
        id = graphene.ID(required=True)
        display_hash = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, id, display_hash):
        return _run(cls, info, lambda user: _draft(service.send_draft(user, _uuid(id), display_hash)))


class PrepareWhatsAppReply(_DraftResult, graphene.Mutation):
    """A reply chip in the Confío IA conversation: that reply to that message, on a card the person sends with a
    tap (the card appears in the conversation; refetch the thread)."""

    class Arguments:
        notice_id = graphene.ID(required=True)
        body = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, notice_id, body):
        from . import chat
        return _run(cls, info, lambda user: _draft(chat.prepare(user, body, notice_id=notice_id)))


class Mutation(graphene.ObjectType):
    prepare_whats_app_reply = PrepareWhatsAppReply.Field()
    start_whats_app_link = StartWhatsAppLink.Field()
    unlink_whats_app = UnlinkWhatsApp.Field()
    accept_whats_app_consent = AcceptWhatsAppConsent.Field()
    refresh_whats_app = RefreshWhatsApp.Field()
    dismiss_whats_app_notice = DismissWhatsAppNotice.Field()
    create_whats_app_draft = CreateWhatsAppDraft.Field()
    update_whats_app_draft = UpdateWhatsAppDraft.Field()
    send_whats_app_draft = SendWhatsAppDraft.Field()
