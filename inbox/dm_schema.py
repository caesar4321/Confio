"""GraphQL for Mensajes (direct messages). Its own operations, so an older
server only loses the chat, never anything else the app asks for."""
from datetime import timedelta
from decimal import Decimal

import graphene
from graphql_jwt.decorators import login_required

from . import community, direct_messages as dm, profile_pictures
from .models import DirectMessageReview


def _context(info):
    from .schema import get_context_models

    return get_context_models(info)


CHANGES_LIMIT = 200


class DirectParticipantType(graphene.ObjectType):
    user_id = graphene.ID(required=True)
    username = graphene.String(required=True)
    avatar_url = graphene.String()


class DirectMessageType(graphene.ObjectType):
    id = graphene.ID(required=True)
    body = graphene.String(required=True)
    kind = graphene.String(required=True)        # text | tip
    tip_amount = graphene.String()
    from_me = graphene.Boolean(required=True)
    # Only ever not 'approved' on your own messages:
    # pending (being reviewed) | approved | rejected | failed.
    status = graphene.String(required=True)
    reason = graphene.String()
    client_key = graphene.String()
    created_at = graphene.DateTime(required=True)


class DirectConversationType(graphene.ObjectType):
    id = graphene.ID(required=True)
    other = graphene.Field(DirectParticipantType, required=True)
    # active | request (incoming or outgoing) | declined (only the sender sees it, as a request)
    status = graphene.String(required=True)
    is_incoming_request = graphene.Boolean(required=True)
    last_message = graphene.Field(DirectMessageType)
    unread_count = graphene.Int(required=True)
    # When you last deleted this chat: a screen showing older history drops it.
    cleared_at = graphene.DateTime()
    # Why you can't write here right now (code), if so.
    send_block = graphene.String()
    send_block_message = graphene.String()


class DirectMessagesPageType(graphene.ObjectType):
    messages = graphene.List(graphene.NonNull(DirectMessageType), required=True)
    has_more = graphene.Boolean(required=True)
    # Pass back as changedSince on the next poll.
    server_time = graphene.DateTime()


class DirectUnreadSummaryType(graphene.ObjectType):
    unread_messages = graphene.Int(required=True)
    requests = graphene.Int(required=True)
    dms_enabled = graphene.Boolean(required=True)


def message_type(message, viewer_id) -> DirectMessageType:
    status = message.review_status
    return DirectMessageType(
        id=str(message.id),
        body=message.body,
        kind=message.kind,
        tip_amount=None if message.tip_amount is None else format(message.tip_amount.quantize(Decimal('0.01')), 'f'),
        from_me=message.sender_id == viewer_id,
        status=status,
        reason=(message.reason or None) if status in (DirectMessageReview.REJECTED, DirectMessageReview.FAILED) else None,
        client_key=message.client_key or None if message.sender_id == viewer_id else None,
        created_at=message.created_at,
    )


def participant(user, avatars=None) -> DirectParticipantType:
    avatars = avatars if avatars is not None else profile_pictures.picture_urls([user.id])
    return DirectParticipantType(user_id=str(user.id), username=community.author_display_name(user),
                                 avatar_url=avatars.get(user.id))


def conversation_type(conversation, member, viewer, avatars=None) -> DirectConversationType:
    other = conversation.other(viewer.id)
    last = dm.visible_messages(conversation, viewer, member.cleared_at).order_by('-id').first()
    block = dm.send_block(viewer, other)
    status = conversation.status
    if status == 'declined' and conversation.requested_by_id == viewer.id:
        status = 'request'               # the sender is never told
    return DirectConversationType(
        id=str(conversation.id),
        other=participant(other, avatars),
        status=status,
        is_incoming_request=dm.is_incoming_request(conversation, viewer),
        last_message=message_type(last, viewer.id) if last else None,
        unread_count=dm.unread_count(conversation, member),
        cleared_at=member.cleared_at,
        send_block=block,
        send_block_message=dm.MESSAGES.get(block) if block else None,
    )


class DirectMessagesQuery(graphene.ObjectType):
    # folder: 'inbox' (default) | 'requests'
    direct_conversations = graphene.List(graphene.NonNull(DirectConversationType), required=True,
                                         folder=graphene.String(required=False),
                                         offset=graphene.Int(required=False), limit=graphene.Int(required=False))
    direct_conversation = graphene.Field(DirectConversationType, conversation_id=graphene.ID(required=True))
    # The conversation with this member, if there is one (opening from a profile).
    direct_conversation_with = graphene.Field(DirectConversationType, user_id=graphene.ID(required=True))
    # Newest first; before_id pages back. changed_since (a previous page's
    # server_time) returns everything delivered or re-reviewed since then,
    # whatever its position: a late approval is never skipped.
    direct_messages = graphene.Field(DirectMessagesPageType, required=True,
                                     conversation_id=graphene.ID(required=True),
                                     before_id=graphene.ID(required=False), limit=graphene.Int(required=False),
                                     changed_since=graphene.DateTime(required=False))
    direct_unread_summary = graphene.Field(DirectUnreadSummaryType, required=True)

    @login_required
    def resolve_direct_conversations(self, info, folder='inbox', offset=0, limit=30):
        user = info.context.user
        offset = max(offset or 0, 0)
        limit = min(max(limit or 30, 1), 50)
        pairs = dm.conversations(user, 'requests' if folder == 'requests' else 'inbox')[offset:offset + limit]
        avatars = profile_pictures.picture_urls([c.other_id(user.id) for c, _ in pairs])
        return [conversation_type(c, m, user, avatars) for c, m in pairs]

    @login_required
    def resolve_direct_conversation(self, info, conversation_id):
        user = info.context.user
        member = dm.member_of(user, conversation_id)
        if member is None or community.is_blocked_between(user.id, member.conversation.other_id(user.id)):
            return None
        return conversation_type(member.conversation, member, user)

    @login_required
    def resolve_direct_conversation_with(self, info, user_id):
        user = info.context.user
        try:
            other_id = int(user_id)
        except (TypeError, ValueError):
            return None
        conversation = dm.conversation_between(user.id, other_id)
        if conversation is None or community.is_blocked_between(user.id, other_id):
            return None
        member = dm.member_of(user, conversation.id)
        return conversation_type(conversation, member, user) if member else None

    @login_required
    def resolve_direct_messages(self, info, conversation_id, before_id=None, limit=dm.PAGE_SIZE, changed_since=None):
        from django.db.models import Q
        from django.utils import timezone

        user = info.context.user
        now = timezone.now()
        member = dm.member_of(user, conversation_id)
        if member is None or community.is_blocked_between(user.id, member.conversation.other_id(user.id)):
            return DirectMessagesPageType(messages=[], has_more=False, server_time=now)
        limit = min(max(limit or dm.PAGE_SIZE, 1), 50)
        qs = dm.visible_messages(member.conversation, user, member.cleared_at)
        if changed_since is not None:
            # A few seconds of overlap: a row committed just before `now` is
            # never lost between two polls (the app merges by id).
            since = changed_since - timedelta(seconds=5)
            rows = list(qs.filter(Q(delivered_at__gt=since) | Q(sender=user, updated_at__gt=since))
                        .order_by('-id')[:CHANGES_LIMIT + 1])
            if len(rows) > CHANGES_LIMIT:
                # Too much changed (a long time away): no cursor, so the app
                # starts over from the latest page instead of missing some.
                return DirectMessagesPageType(messages=[], has_more=True, server_time=None)
            return DirectMessagesPageType(messages=[message_type(m, user.id) for m in rows], has_more=False,
                                          server_time=now)
        if before_id:
            qs = qs.filter(id__lt=int(before_id))
        rows = list(qs.order_by('-id')[:limit + 1])
        return DirectMessagesPageType(
            messages=[message_type(m, user.id) for m in rows[:limit]],   # newest first
            has_more=len(rows) > limit,
            server_time=now,
        )

    @login_required
    def resolve_direct_unread_summary(self, info):
        user = info.context.user
        unread, requests = dm.unread_summary(user)
        return DirectUnreadSummaryType(unread_messages=unread, requests=requests, dms_enabled=dm.dms_enabled(user))


class SendDirectMessage(graphene.Mutation):
    """To an existing conversation, or to a member (starts one). The message
    is reviewed before the other person sees it: poll its status."""
    class Arguments:
        body = graphene.String(required=True)
        conversation_id = graphene.ID(required=False)
        recipient_user_id = graphene.ID(required=False)
        client_key = graphene.String(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    conversation_id = graphene.ID()
    message = graphene.Field(DirectMessageType)

    @classmethod
    @login_required
    def mutate(cls, root, info, body, conversation_id=None, recipient_user_id=None, client_key=None):
        user, account, business, _ = _context(info)
        if not conversation_id and not recipient_user_id:
            return SendDirectMessage(success=False, error=dm.MESSAGES[dm.NOT_AVAILABLE], code=dm.NOT_AVAILABLE)
        try:
            message = dm.send_message(user, business, body, recipient_id=recipient_user_id,
                                      conversation_id=int(conversation_id) if conversation_id else None,
                                      client_key=client_key or '')
        except (ValueError, TypeError):
            return SendDirectMessage(success=False, error=dm.MESSAGES[dm.NOT_AVAILABLE], code=dm.NOT_AVAILABLE)
        except community.CommunityPostError as error:
            return SendDirectMessage(success=False, error=error.message, code=error.code)
        return SendDirectMessage(success=True, conversation_id=str(message.conversation_id),
                                 message=message_type(message, user.id))


class AcceptDirectRequest(graphene.Mutation):
    class Arguments:
        conversation_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, conversation_id):
        try:
            dm.accept_request(info.context.user, conversation_id)
        except community.CommunityPostError:
            return AcceptDirectRequest(success=False)
        return AcceptDirectRequest(success=True)


class DeleteDirectConversation(graphene.Mutation):
    class Arguments:
        conversation_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, conversation_id):
        return DeleteDirectConversation(success=dm.delete_conversation(info.context.user, conversation_id))


class MarkDirectConversationRead(graphene.Mutation):
    class Arguments:
        conversation_id = graphene.ID(required=True)
        # The serverTime of the page the app showed: nothing delivered after it counts as read.
        up_to = graphene.DateTime(required=False)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, conversation_id, up_to=None):
        return MarkDirectConversationRead(success=dm.mark_read(info.context.user, conversation_id, up_to))


class ReportDirectMessage(graphene.Mutation):
    class Arguments:
        message_id = graphene.ID(required=True)
        reason = graphene.String(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, message_id, reason=''):
        try:
            dm.report_message(info.context.user, message_id, reason or '')
        except community.CommunityPostError as error:
            return ReportDirectMessage(success=False, error=error.message)
        return ReportDirectMessage(success=True)


class SetDirectMessagesEnabled(graphene.Mutation):
    """Your own switch: off, nobody new can write to you."""
    class Arguments:
        enabled = graphene.Boolean(required=True)

    success = graphene.Boolean(required=True)
    enabled = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, enabled):
        return SetDirectMessagesEnabled(success=True, enabled=dm.set_dms_enabled(info.context.user, enabled))


class PrepareTip(graphene.Mutation):
    """Propina, step 1: rules and the note's review, no money. Then the app
    runs the normal BSC send with idempotencyKey = sendKey."""
    class Arguments:
        recipient_user_id = graphene.ID(required=True)
        amount = graphene.String(required=True)
        note = graphene.String(required=False)
        client_key = graphene.String(required=False)
        # After the person confirmed sending another tip right after one.
        allow_repeat = graphene.Boolean(required=False)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    code = graphene.String()
    tip_id = graphene.ID()
    send_key = graphene.String()
    amount = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, recipient_user_id, amount, note='', client_key='', allow_repeat=False):
        from . import tips

        user, account, business, _ = _context(info)
        try:
            tip = tips.prepare_tip(user, business, recipient_user_id, amount, note or '', client_key or '',
                                   allow_repeat=bool(allow_repeat))
        except community.CommunityPostError as error:
            return PrepareTip(success=False, error=error.message, code=error.code)
        return PrepareTip(success=True, tip_id=str(tip.id), send_key=tip.send_key, amount=format(tip.amount, 'f'))


class DirectMessagesMutation(graphene.ObjectType):
    prepare_tip = PrepareTip.Field()
    send_direct_message = SendDirectMessage.Field()
    accept_direct_request = AcceptDirectRequest.Field()
    delete_direct_conversation = DeleteDirectConversation.Field()
    mark_direct_conversation_read = MarkDirectConversationRead.Field()
    report_direct_message = ReportDirectMessage.Field()
    set_direct_messages_enabled = SetDirectMessagesEnabled.Field()


