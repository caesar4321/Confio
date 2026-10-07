"""GraphQL for Confio Assistant.

All new operations, no new fields on shared types: the app asks for these in
their own requests so an older server fails only the assistant, never the
inbox (see feedback-isolate-new-graphql-fields).
"""
import logging
import re

import graphene
from graphql import GraphQLError
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models, get_or_create_support_conversation

from . import billing, conf, pets, service, voice
from .engine import AssistantUnavailable
from .models import Mascot

logger = logging.getLogger(__name__)

HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


class AssistantActionType(graphene.ObjectType):
    type = graphene.String(required=True)
    destination = graphene.String(description='A screen key every build knows (the fallback for `target`)')
    target = graphene.String(description='A newer screen key; builds that know it open it instead of `destination`')
    ticker = graphene.String(description='For target "stock": the stock or ETF to open')
    label = graphene.String(description='Chip text, e.g. "Ver SPDR S&P 500 ETF"')


class AssistantMessageType(graphene.ObjectType):
    id = graphene.ID(required=True)
    role = graphene.String(required=True, description='user | assistant | team | system')
    body = graphene.String(required=True)
    created_at = graphene.DateTime(required=True)
    sender_name = graphene.String(required=True)
    modality = graphene.String()
    actions = graphene.List(graphene.NonNull(AssistantActionType), required=True)


class AssistantProfileType(graphene.ObjectType):
    mascot = graphene.String(required=True)
    mascot_name = graphene.String(required=True)
    mascot_color = graphene.String(required=True)
    bubble_hidden = graphene.Boolean(required=True)
    bubble_side = graphene.String(required=True)
    bubble_height = graphene.Float(required=True)
    wake_word_enabled = graphene.Boolean(required=True)
    custom_pet_id = graphene.ID()
    custom_pet_url = graphene.String(description='Signed, short-lived; refetch when it expires')
    pet_creations_left = graphene.Int(required=True)
    pet_creations_period = graphene.String(required=True, description='week (free) | day (Assistant+)')


class AssistantPetType(graphene.ObjectType):
    id = graphene.ID(required=True)
    image_url = graphene.String()
    idea = graphene.String(required=True)
    source = graphene.String(required=True)


class AssistantPlanType(graphene.ObjectType):
    is_plus = graphene.Boolean(required=True)
    # No store purchases since 2026-10-07. Kept (always empty / False) only
    # because older builds still request them in this query.
    product_id = graphene.String(required=True, deprecation_reason='No store purchases')
    billing_token = graphene.String(required=True, deprecation_reason='No store purchases')
    platform = graphene.String(description='Where the active subscription is billed')
    expires_at = graphene.DateTime()
    auto_renew = graphene.Boolean()
    in_grace = graphene.Boolean(required=True)
    daily_turns = graphene.Int(required=True)
    remaining_turns = graphene.Int(required=True)
    voice_minutes = graphene.Int(required=True)
    voice_minutes_left = graphene.Int(required=True)
    wake_word_available = graphene.Boolean(required=True)
    voice_calls_enabled = graphene.Boolean(required=True, description='Realtime calls offered at all')
    plus_sales_enabled = graphene.Boolean(required=True, deprecation_reason='No store purchases')


class AssistantWakeWordType(graphene.ObjectType):
    access_key = graphene.String(required=True)


class AssistantThreadType(graphene.ObjectType):
    messages = graphene.List(graphene.NonNull(AssistantMessageType), required=True)
    has_more = graphene.Boolean(required=True)
    mode = graphene.String(required=True, description='AI | HUMAN')
    remaining_turns = graphene.Int(required=True)
    enabled = graphene.Boolean(required=True)
    profile = graphene.Field(AssistantProfileType, required=True)


def message_payload(message):
    metadata = message.metadata or {}
    if message.sender_type == 'USER':
        role, name = 'user', 'Tú'
    elif message.sender_type == 'AGENT' and metadata.get('ai'):
        role, name = 'assistant', 'Confio Assistant'
    elif message.sender_type == 'AGENT':
        role = 'team'
        staff = message.sender_user
        name = (staff.first_name or '').strip() if staff else ''
        name = f'{name} · Equipo Confío' if name else 'Equipo Confío'
    else:
        role, name = 'system', 'Confío'
    return AssistantMessageType(
        id=str(message.id),
        role=role,
        body=message.body,
        created_at=message.created_at,
        sender_name=name,
        modality=metadata.get('modality'),
        actions=[
            AssistantActionType(type=a.get('type', ''), destination=a.get('destination'), target=a.get('target'),
                                ticker=a.get('ticker'), label=a.get('label'))
            for a in (metadata.get('actions') or []) if isinstance(a, dict)
        ],
    )


def profile_payload(profile):
    left, period = pets.creations_left(profile.user)
    return AssistantProfileType(
        custom_pet_id=str(profile.custom_pet_id) if profile.custom_pet_id else None,
        custom_pet_url=pets.pet_url(profile.custom_pet) if profile.mascot == Mascot.CUSTOM else None,
        pet_creations_left=left,
        pet_creations_period=period,

        mascot=profile.mascot,
        mascot_name=profile.mascot_name,
        mascot_color=profile.mascot_color,
        bubble_hidden=profile.bubble_hidden,
        bubble_side=profile.bubble_side,
        bubble_height=profile.bubble_height,
        wake_word_enabled=profile.wake_word_enabled,
    )


def plan_payload(user):
    sub = billing.active_subscription(user)
    plus = sub is not None
    return AssistantPlanType(
        is_plus=plus,
        product_id='',
        billing_token='',
        platform=sub.platform if sub else None,
        expires_at=sub.expires_at if sub else None,
        auto_renew=sub.auto_renew if sub else None,
        in_grace=bool(sub and sub.status == 'GRACE'),
        daily_turns=service.daily_turn_cap(user),
        remaining_turns=service.remaining_turns(user),
        voice_minutes=conf.get('CONFIO_ASSISTANT_PLUS_VOICE_MINUTES') if plus else 0,
        voice_minutes_left=int(voice.minutes_left(user)) if plus else 0,
        # Free for everyone: "Confío" opens a voice note (cheap), never a call.
        wake_word_available=bool(conf.get('CONFIO_ASSISTANT_ENABLED')) and bool(conf.get('CONFIO_ASSISTANT_PICOVOICE_ACCESS_KEY')),
        voice_calls_enabled=bool(conf.get('CONFIO_ASSISTANT_REALTIME_ENABLED')),
        plus_sales_enabled=False,
    )


def pet_payload(pet):
    return AssistantPetType(id=str(pet.id), image_url=pets.pet_url(pet), idea=pet.idea, source=pet.source)


class AssistantSuggestionType(graphene.ObjectType):
    id = graphene.String(required=True)
    text = graphene.String(required=True)
    prompt = graphene.String(required=True)
    kind = graphene.String(required=True, description='prompt | probe | picker')


class AssistantProbeAnswerOptionType(graphene.ObjectType):
    key = graphene.String(required=True)
    label = graphene.String(required=True)


class AssistantProbeType(graphene.ObjectType):
    id = graphene.String(required=True)
    question = graphene.String(required=True)
    answers = graphene.List(graphene.NonNull(AssistantProbeAnswerOptionType), required=True)


class AssistantSuggestionsType(graphene.ObjectType):
    hints = graphene.List(graphene.NonNull(AssistantSuggestionType), required=True,
                          description='Bubble hints for this screen, most important first')
    starters = graphene.List(graphene.NonNull(AssistantSuggestionType), required=True,
                             description='Chips shown when the chat opens (max 4)')
    probe = graphene.Field(AssistantProbeType, description='Set while the one-time question is pending')


class Query(graphene.ObjectType):
    assistant_suggestions = graphene.Field(
        AssistantSuggestionsType, screen=graphene.String(),
        context_key=graphene.String(description='Active account id; only keys the client cache per account'),
        description='Ranked by the person\'s situation. Null when unavailable: the app uses its built-in list.')

    @login_required
    def resolve_assistant_suggestions(self, info, screen=None, context_key=None):
        from . import suggestions as suggestion_rules

        user, account, business, jwt_context = get_context_models(info)
        try:
            viewer = service._viewer(user, account, business, jwt_context, screen=screen or '')
            result = suggestion_rules.build(viewer, (screen or '')[:64], getattr(info.context, 'META', {}))
        except Exception:  # noqa: BLE001 - the app falls back to its own list
            logger.exception('assistant suggestions failed')
            return None
        as_type = lambda s: AssistantSuggestionType(id=s.id, text=s.text, prompt=s.prompt, kind=s.kind)  # noqa: E731
        probe = result.probe and AssistantProbeType(
            id=result.probe['id'], question=result.probe['question'],
            answers=[AssistantProbeAnswerOptionType(**a) for a in result.probe['answers']])
        return AssistantSuggestionsType(hints=[as_type(s) for s in result.hints],
                                        starters=[as_type(s) for s in result.starters], probe=probe)

    assistant_pets = graphene.List(graphene.NonNull(AssistantPetType), required=True)

    @login_required
    def resolve_assistant_pets(self, info):
        from .models import CustomPet
        return [pet_payload(p) for p in CustomPet.objects.filter(
            user=info.context.user, deleted_at__isnull=True).exclude(image_key='').order_by('-created_at')[:12]]

    assistant_plan = graphene.Field(AssistantPlanType)
    assistant_wake_word = graphene.Field(AssistantWakeWordType, description='Null until the key is configured')

    @login_required
    def resolve_assistant_plan(self, info):
        return plan_payload(info.context.user)

    @login_required
    def resolve_assistant_wake_word(self, info):
        key = conf.get('CONFIO_ASSISTANT_PICOVOICE_ACCESS_KEY')
        if not key or not conf.get('CONFIO_ASSISTANT_ENABLED'):
            return None
        return AssistantWakeWordType(access_key=key)

    assistant_thread = graphene.Field(
        AssistantThreadType,
        limit=graphene.Int(default_value=30),
        before_id=graphene.ID(),
        context_key=graphene.String(description='Active account id; only keys the client cache per account'),
    )

    @login_required
    def resolve_assistant_thread(self, info, limit=30, before_id=None, context_key=None):
        user, account, business, _ = get_context_models(info)
        conversation = get_or_create_support_conversation(user, account, business)
        limit = min(max(int(limit or 30), 1), 50)
        queryset = conversation.messages.select_related('sender_user').order_by('-id')
        if before_id:
            queryset = queryset.filter(id__lt=int(before_id))
        page = list(queryset[:limit + 1])
        has_more = len(page) > limit
        page = list(reversed(page[:limit]))
        return AssistantThreadType(
            messages=[message_payload(m) for m in page],
            has_more=has_more,
            mode='HUMAN' if service.is_human_mode(conversation) else 'AI',
            remaining_turns=service.remaining_turns(user),
            # False = support answered by people (kill switch).
            enabled=bool(conf.get('CONFIO_ASSISTANT_ENABLED')),
            profile=profile_payload(service.profile_for(user)),
        )


class AskAssistant(graphene.Mutation):
    class Arguments:
        body = graphene.String(description='Typed text. Ignored when audio is sent.')
        audio_base64 = graphene.String(description='Voice note, base64. Transcribed, never stored.')
        audio_mime_type = graphene.String()
        audio_duration_ms = graphene.Int()
        screen = graphene.String(description='Route name the user is on, for context only')
        timezone = graphene.String(description='Device IANA timezone')

    success = graphene.Boolean(required=True)
    error = graphene.String()
    transcript = graphene.String()
    user_message = graphene.Field(AssistantMessageType)
    reply = graphene.Field(AssistantMessageType)
    actions = graphene.List(graphene.NonNull(AssistantActionType), required=True)
    mode = graphene.String(required=True)
    remaining_turns = graphene.Int()
    data_changed = graphene.Boolean(description='The reply changed the user\'s data: refresh money views')

    @classmethod
    @login_required
    def mutate(cls, root, info, body=None, audio_base64=None, audio_mime_type=None,
               audio_duration_ms=None, screen=None, timezone=None):
        user, account, business, jwt_context = get_context_models(info)
        audio = (audio_base64, audio_mime_type, audio_duration_ms) if audio_base64 else None
        if not audio and not (body or '').strip():
            raise GraphQLError('Message body is required')
        try:
            # Transcription happens inside, after the quota/human-mode checks.
            outcome = service.ask(user, account, business, jwt_context, None if audio else body, audio=audio,
                                  screen=screen or '', tz_name=timezone,
                                  request_meta=getattr(info.context, 'META', None))
        except ValueError as exc:
            return AskAssistant(success=False, error=str(exc), actions=[], mode='AI')
        except AssistantUnavailable as exc:
            logger.warning('Confio Assistant transcription unavailable: %s', exc)
            return AskAssistant(success=False, error='No pude escuchar el audio. Inténtalo de nuevo o escríbeme.',
                               actions=[], mode='AI')
        return AskAssistant(
            success=True,
            transcript=outcome.transcript,
            user_message=message_payload(outcome.user_message),
            reply=message_payload(outcome.reply_message) if outcome.reply_message else None,
            actions=[AssistantActionType(type=a['type'], destination=a.get('destination'), target=a.get('target'),
                                         ticker=a.get('ticker'), label=a.get('label')) for a in outcome.actions],
            mode=outcome.mode,
            remaining_turns=outcome.remaining_turns,
            data_changed=outcome.data_changed,
        )


class ReturnToAssistant(graphene.Mutation):
    success = graphene.Boolean(required=True)
    mode = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info):
        user, account, business, _ = get_context_models(info)
        service.return_to_ai(user, account, business)
        return ReturnToAssistant(success=True, mode='AI')


class UpdateAssistantProfile(graphene.Mutation):
    class Arguments:
        mascot = graphene.String()
        mascot_name = graphene.String()
        mascot_color = graphene.String()
        bubble_hidden = graphene.Boolean()
        bubble_side = graphene.String()
        bubble_height = graphene.Float()
        wake_word_enabled = graphene.Boolean()

    success = graphene.Boolean(required=True)
    profile = graphene.Field(AssistantProfileType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, mascot=None, mascot_name=None, mascot_color=None, bubble_hidden=None,
               bubble_side=None, bubble_height=None, wake_word_enabled=None):
        profile = service.profile_for(info.context.user)
        fields = []
        if mascot is not None:
            if mascot not in Mascot.values or mascot == Mascot.CUSTOM:
                raise GraphQLError('Personaje no válido')
            profile.mascot = mascot
            fields.append('mascot')
        if mascot_name is not None:
            profile.mascot_name = ' '.join(mascot_name.split())[:24]
            fields.append('mascot_name')
        if mascot_color is not None:
            if mascot_color and not HEX_COLOR.match(mascot_color):
                raise GraphQLError('Color no válido')
            profile.mascot_color = mascot_color
            fields.append('mascot_color')
        if bubble_hidden is not None:
            profile.bubble_hidden = bool(bubble_hidden)
            fields.append('bubble_hidden')
        if bubble_side is not None:
            if bubble_side not in ('left', 'right'):
                raise GraphQLError('Lado no válido')
            profile.bubble_side = bubble_side
            fields.append('bubble_side')
        if bubble_height is not None:
            profile.bubble_height = min(max(float(bubble_height), 0.0), 1.0)
            fields.append('bubble_height')
        if wake_word_enabled is not None:
            profile.wake_word_enabled = bool(wake_word_enabled)
            fields.append('wake_word_enabled')
        if fields:
            profile.save(update_fields=fields + ['updated_at'])
        return UpdateAssistantProfile(success=True, profile=profile_payload(profile))


class AssistantTranscriptInput(graphene.InputObjectType):
    role = graphene.String(required=True, description='user | assistant')
    text = graphene.String(required=True)


class StartAssistantVoice(graphene.Mutation):
    class Arguments:
        screen = graphene.String()
        timezone = graphene.String()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    session_id = graphene.ID()
    model = graphene.String()
    minutes_left = graphene.Int()

    @classmethod
    @login_required
    def mutate(cls, root, info, screen=None, timezone=None):
        user, account, business, jwt_context = get_context_models(info)
        viewer = service._viewer(user, account, business, jwt_context, screen=screen or '', tz_name=timezone,
                                 request_meta=getattr(info.context, 'META', None))
        conversation = get_or_create_support_conversation(user, account, business)
        try:
            session, left = voice.start_session(
                viewer, conversation, first_name=user.first_name,
                account_label=service._account_label(viewer, business),
                country=getattr(user, 'phone_country', ''),
            )
        except voice.VoiceUnavailable as exc:
            return cls(success=False, error=str(exc))
        return cls(success=True, session_id=str(session.id), model=session.model, minutes_left=left)


class ConnectAssistantVoice(graphene.Mutation):
    """WebRTC handshake done by the server (it holds the session secret and
    learns the call id, so it can always hang up)."""

    class Arguments:
        session_id = graphene.ID(required=True)
        offer_sdp = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    answer_sdp = graphene.String()

    @classmethod
    @login_required
    def mutate(cls, root, info, session_id, offer_sdp):
        user, account, business, _ = get_context_models(info)
        try:
            session = voice.get_session(user, session_id)
            if not voice.session_allowed(session, account, business):
                voice.hang_up(session)
                raise voice.VoiceUnavailable('La llamada terminó.')
            answer = voice.connect(session, offer_sdp)
        except voice.VoiceUnavailable as exc:
            return cls(success=False, error=str(exc))
        return cls(success=True, answer_sdp=answer)


class RunAssistantVoiceTool(graphene.Mutation):
    class Arguments:
        session_id = graphene.ID(required=True)
        name = graphene.String(required=True)
        arguments = graphene.String(description='JSON arguments from the model')

    output = graphene.String(required=True)
    handed_off = graphene.Boolean(required=True)
    keep_going = graphene.Boolean(required=True, description='False: hang up now')

    @classmethod
    @login_required
    def mutate(cls, root, info, session_id, name, arguments=None):
        from django.db import transaction

        user, account, business, jwt_context = get_context_models(info)
        ended = '{"error": "La llamada terminó."}'
        try:
            session = voice.get_session(user, session_id)
        except voice.VoiceUnavailable:
            return cls(output=ended, handed_off=False, keep_going=False)
        # Same account, still live, still entitled: anything else ends the call.
        if not voice.session_allowed(session, account, business) or not voice.heartbeat(session):
            voice.hang_up(session)
            return cls(output=ended, handed_off=False, keep_going=False)
        viewer = service._viewer(user, account, business, jwt_context, screen=session.screen,
                                 tz_name=session.tz_name, request_meta=getattr(info.context, 'META', None))
        # Analyses reserve their slot under the user's lock inside run_tool;
        # the slow work itself runs unlocked.
        output, result = voice.run_tool(session, viewer, name, arguments)
        if result.handoff_reason:
            with transaction.atomic():
                service.handoff_from_voice(session.conversation, result.handoff_reason)
        return cls(output=output, handed_off=bool(result.handoff_reason), keep_going=True)


class LogAssistantVoice(graphene.Mutation):
    """Transcripts + heartbeat. Returns whether the call may continue."""

    class Arguments:
        session_id = graphene.ID(required=True)
        transcript = graphene.List(graphene.NonNull(AssistantTranscriptInput))
        usage_json = graphene.String()
        ended = graphene.Boolean()

    keep_going = graphene.Boolean(required=True)
    minutes_left = graphene.Int(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, session_id, transcript=None, usage_json=None, ended=False):
        user, account, business, _ = get_context_models(info)
        try:
            session = voice.get_session(user, session_id)
        except voice.VoiceUnavailable:
            return cls(keep_going=False, minutes_left=0)
        # Always bound to the starting account; an already-ended call accepts
        # nothing more (final logs are idempotent, replays are ignored).
        if not voice.session_belongs(session, account, business) or session.ended_at is not None:
            voice.hang_up(session)
            return cls(keep_going=False, minutes_left=int(voice.minutes_left(user)))
        if not ended and not voice.session_allowed(session, account, business):
            voice.hang_up(session)
            return cls(keep_going=False, minutes_left=int(voice.minutes_left(user)))
        if transcript:
            service.append_voice_transcript(session.conversation, user,
                                            [{'role': t.role, 'text': t.text} for t in transcript])
        if usage_json:
            try:
                import json as _json
                voice.record_usage(session, _json.loads(usage_json))
            except (TypeError, ValueError):
                pass
        keep_going = voice.heartbeat(session, ended=bool(ended)) and not ended
        if not keep_going:
            voice.hang_up(session)
        return cls(keep_going=keep_going, minutes_left=int(voice.minutes_left(user)))


class CreateAssistantPet(graphene.Mutation):
    class Arguments:
        idea = graphene.String()
        photo_base64 = graphene.String(description='A photo of the user\'s own pet (no people)')
        photo_mime_type = graphene.String()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    pet = graphene.Field(AssistantPetType)
    creations_left = graphene.Int()

    @classmethod
    @login_required
    def mutate(cls, root, info, idea=None, photo_base64=None, photo_mime_type=None):
        user = info.context.user
        try:
            pet = pets.create_pet(user, idea=idea or '', photo_base64=photo_base64, photo_mime=photo_mime_type)
        except pets.PetError as exc:
            return cls(success=False, error=str(exc), creations_left=pets.creations_left(user)[0])
        return cls(success=True, pet=pet_payload(pet), creations_left=pets.creations_left(user)[0])


class UseAssistantPet(graphene.Mutation):
    """Wear a created pet (pet_id), or go back to the built-in mascot (null)."""

    class Arguments:
        pet_id = graphene.ID()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    profile = graphene.Field(AssistantProfileType)

    @classmethod
    @login_required
    def mutate(cls, root, info, pet_id=None):
        try:
            profile = pets.use_pet(info.context.user, int(pet_id) if pet_id else None)
        except (pets.PetError, ValueError) as exc:
            return cls(success=False, error=str(exc))
        return cls(success=True, profile=profile_payload(profile))


class DeleteAssistantPet(graphene.Mutation):
    class Arguments:
        pet_id = graphene.ID(required=True)

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, pet_id):
        pets.delete_pet(info.context.user, int(pet_id))
        return cls(success=True)


class AnswerAssistantProbe(graphene.Mutation):
    """Record the one-time question's answer (first answer wins)."""

    class Arguments:
        probe_id = graphene.String(required=True)
        answer = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    label = graphene.String(description='The chosen answer, to send on as the user\'s message')

    @login_required
    def mutate(self, info, probe_id, answer):
        from . import suggestions as suggestion_rules

        user, account, business, jwt_context = get_context_models(info)
        try:
            viewer = service._viewer(user, account, business, jwt_context)
            state = suggestion_rules._state(viewer, getattr(info.context, 'META', {}))
            if not suggestion_rules.wants_probe(state):
                # Not asked of this person (business context, funded, answered).
                return AnswerAssistantProbe(success=False, error='Pregunta no disponible')
            suggestion_rules.record_probe_answer(user, probe_id, answer, funded=state.funded)
        except ValueError as exc:
            return AnswerAssistantProbe(success=False, error=str(exc))
        return AnswerAssistantProbe(success=True, label=suggestion_rules.answer_label(answer))


class Mutation(graphene.ObjectType):
    answer_assistant_probe = AnswerAssistantProbe.Field()
    create_assistant_pet = CreateAssistantPet.Field()
    use_assistant_pet = UseAssistantPet.Field()
    delete_assistant_pet = DeleteAssistantPet.Field()
    start_assistant_voice = StartAssistantVoice.Field()
    connect_assistant_voice = ConnectAssistantVoice.Field()
    run_assistant_voice_tool = RunAssistantVoiceTool.Field()
    log_assistant_voice = LogAssistantVoice.Field()
    ask_assistant = AskAssistant.Field()
    return_to_assistant = ReturnToAssistant.Field()
    update_assistant_profile = UpdateAssistantProfile.Field()
