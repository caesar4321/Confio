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
from security.geo import country_of

logger = logging.getLogger(__name__)

HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


class AssistantActionType(graphene.ObjectType):
    type = graphene.String(required=True)
    destination = graphene.String(description='A screen key every build knows (the fallback for `target`)')
    target = graphene.String(description='A newer screen key; builds that know it open it instead of `destination`')
    ticker = graphene.String(description='For target "stock": the stock or ETF to open')
    label = graphene.String(description='Chip text, e.g. "Ver SPDR S&P 500 ETF"')
    source = graphene.String(description='Paid-offer chips: why it was shown, e.g. "chip:investing"')


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


class AssistantStockTradeType(graphene.ObjectType):
    # none | pending | done | failed | expired | gone (assistant/trades.py)
    status = graphene.String(required=True)
    tx_hash = graphene.String()


class AssistantTopUpType(graphene.ObjectType):
    # none | order | expired | gone (assistant/topup_limits.py)
    status = graphene.String(required=True)
    order_id = graphene.String()
    country_code = graphene.String()
    fiat_currency = graphene.String()
    fiat_amount = graphene.String()
    payment_method_code = graphene.String()
    payment_method_display = graphene.String()


class AttachAssistantTopUp(graphene.Mutation):
    """The top-up form of this message created this order: the conversation keeps it."""
    class Arguments:
        message_id = graphene.ID(required=True)
        order_id = graphene.String(required=True)
        payment_method_code = graphene.String()
        payment_method_display = graphene.String()

    success = graphene.Boolean(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, message_id, order_id, payment_method_code='', payment_method_display=''):
        from . import topup_limits
        return AttachAssistantTopUp(success=topup_limits.attach(
            info.context.user, message_id, order_id, payment_method_code or '', payment_method_display or ''))


class ClaimAssistantStockTrade(graphene.Mutation):
    """The one request a stock-trade card may sign now. Empty while another
    is out, once a batch is on record, or after the card expired."""
    class Arguments:
        message_id = graphene.ID(required=True)

    request_id = graphene.String()
    status = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, message_id):
        from . import trades
        request_id, status = trades.claim(info.context.user, message_id)
        return ClaimAssistantStockTrade(request_id=request_id or None, status=status)


class ReleaseAssistantStockTrade(graphene.Mutation):
    """The phone's word that the request it was given sent nothing."""
    class Arguments:
        message_id = graphene.ID(required=True)
        request_id = graphene.String(required=True)

    status = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, message_id, request_id):
        from . import trades
        return ReleaseAssistantStockTrade(status=trades.release(info.context.user, message_id, request_id))


class AssistantRelayTradeType(graphene.ObjectType):
    # waiting_rule | pending | done | failed | cancelled (smart_account/relay_trades.py)
    status = graphene.String(required=True)
    tx_hash = graphene.String()
    label = graphene.String(required=True)
    error_code = graphene.String()
    # While waiting_rule (the cap card): new | raise, the choices, the one preselected, the cap today.
    mode = graphene.String()
    choices = graphene.List(graphene.NonNull(graphene.String))
    preselected = graphene.String()
    current_cap = graphene.String()
    # While waiting_move: the dollars the move card moves in (the server's).
    move_amount = graphene.String()
    # stock | crypto: which Comunidad share the card offers once done (asked in its own query: older
    # servers lack it).
    asset_kind = graphene.String()


def _hands_off_prepare(info, fn):
    from smart_account.schema import _prepare
    return _prepare(info, fn)


def _prepared_batch_output():
    from smart_account.schema import SmartAccountPreparedBatchType
    return SmartAccountPreparedBatchType


class PrepareAssistantTradeCap(graphene.Mutation):
    """The weekly cap the person chose on a chat trade's cap card: the Trade
    rule (created, or raised), signed once with Confío Face."""
    class Arguments:
        trade = graphene.UUID(required=True)
        amount = graphene.String(required=True, description='US dollars per week, as chosen on the card')

    Output = _prepared_batch_output()

    def mutate(self, info, trade, amount):
        from smart_account import services
        from smart_account.models import SmartRelayTrade
        from smart_account.schema import _batch_error
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated or not SmartRelayTrade.objects.filter(
                user=user, internal_id=trade, status='waiting_rule').exists():
            return _batch_error('not_open', 'Esa operación ya no está pendiente. Pídemela de nuevo en el chat.')
        return _hands_off_prepare(info, lambda viewer: services.prepare_trade_rule(viewer, amount))


class PrepareAssistantTradeMove(graphene.Mutation):
    """Personal wallet -> Cuenta inteligente for a chat trade it is short of (its amount is the server's)."""
    class Arguments:
        trade = graphene.UUID(required=True)

    Output = _prepared_batch_output()

    def mutate(self, info, trade):
        from smart_account import services
        return _hands_off_prepare(info, lambda viewer: services.prepare_trade_move(viewer, trade))


class PrepareAssistantAccountMigration(graphene.Mutation):
    """The one-Face batch that updates a Cuenta inteligente to the version that trades for the person."""
    Output = _prepared_batch_output()

    def mutate(self, info):
        from smart_account import services
        return _hands_off_prepare(info, services.prepare_migration)


class ResumeAssistantRelayTrade(graphene.Mutation):
    """The cap card was signed: the chat trade waiting for it goes ahead."""
    class Arguments:
        trade = graphene.UUID(required=True)

    status = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, trade):
        from smart_account import relay_trades
        row = relay_trades.resume(info.context.user, trade)
        return ResumeAssistantRelayTrade(status=(relay_trades.status_of(info.context.user, trade) or {}).get(
            'status', 'gone') if row is not None else 'gone')


class AssistantRelayPurchaseType(graphene.ObjectType):
    # waiting_rule | waiting_move | pending | done | failed | cancelled (smart_account/relay_purchases.py)
    status = graphene.String(required=True)
    tx_hash = graphene.String()
    label = graphene.String(required=True)
    error_code = graphene.String()
    amount = graphene.String(description='The total the person said "sí" to, US dollars')
    order = graphene.String(description='The Comprar order (public id) once paid')
    # While waiting_rule (the cap card): new | raise, the choices, the one preselected, the cap today.
    mode = graphene.String()
    choices = graphene.List(graphene.NonNull(graphene.String))
    preselected = graphene.String()
    current_cap = graphene.String()
    # While waiting_move: the dollars the move card moves in (the server's).
    move_amount = graphene.String()


class PrepareAssistantPurchaseCap(graphene.Mutation):
    """The weekly Comprar cap the person chose on a chat purchase's cap card:
    the Purchase rule (created, or raised), signed once with Confío Face."""
    class Arguments:
        purchase = graphene.UUID(required=True)
        amount = graphene.String(required=True, description='US dollars per week, as chosen on the card')

    Output = _prepared_batch_output()

    def mutate(self, info, purchase, amount):
        from smart_account import relay_purchases
        from smart_account.models import SmartRelayPurchase
        from smart_account.schema import _batch_error
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated or not SmartRelayPurchase.objects.filter(
                user=user, internal_id=purchase, status='waiting_rule').exists():
            return _batch_error('not_open', 'Esa compra ya no está pendiente. Pídemela de nuevo en el chat.')
        return _hands_off_prepare(info, lambda viewer: relay_purchases.prepare_purchase_rule(viewer, amount))


class PrepareAssistantPurchaseMove(graphene.Mutation):
    """Personal wallet -> Cuenta inteligente for a chat purchase it is short of (its amount is the server's)."""
    class Arguments:
        purchase = graphene.UUID(required=True)

    Output = _prepared_batch_output()

    def mutate(self, info, purchase):
        from smart_account import relay_purchases
        return _hands_off_prepare(info, lambda viewer: relay_purchases.prepare_purchase_move(viewer, purchase))


class ResumeAssistantRelayPurchase(graphene.Mutation):
    """The cap or move card was signed: the chat purchase waiting for it goes ahead."""
    class Arguments:
        purchase = graphene.UUID(required=True)

    status = graphene.String(required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, purchase):
        from smart_account import relay_purchases
        row = relay_purchases.resume(info.context.user, purchase)
        return ResumeAssistantRelayPurchase(status=(relay_purchases.status_of(info.context.user, purchase) or {}).get(
            'status', 'gone') if row is not None else 'gone')


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
                                ticker=a.get('ticker'), label=a.get('label'), source=a.get('source'))
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


class AssistantGuideTrailStopType(graphene.ObjectType):
    route = graphene.String(required=True)
    text = graphene.String(required=True)
    pointer = graphene.String(required=True, description='Button to circle; empty shows only the sentence')


class AssistantGuideChipType(graphene.ObjectType):
    label = graphene.String(required=True)
    kind = graphene.String(required=True, description='navigate | probe | dismiss; unknown kinds are not drawn')
    answer = graphene.String(required=True)
    trail = graphene.List(graphene.NonNull(AssistantGuideTrailStopType), required=True,
                          description='Screens to walk through after the tap, each with its own sentence')


class AssistantGuideType(graphene.ObjectType):
    step = graphene.String(required=True)
    stage = graphene.String(required=True)
    text = graphene.String(required=True)
    presentation = graphene.String(required=True, description='full | bubble; anything unknown is a bubble')
    chips = graphene.List(graphene.NonNull(AssistantGuideChipType), required=True)


class AssistantWalkType(graphene.ObjectType):
    key = graphene.String(required=True)
    trail = graphene.List(graphene.NonNull(AssistantGuideTrailStopType), required=True)


class AssistantRuleStepType(graphene.ObjectType):
    """One rule change Confío IA+ proposed. Data for prefilling the rule
    screen, never authority: the screen's prepare re-validates everything
    and nothing changes until the owner signs."""
    action = graphene.String(required=True, description='create | update | cancel')
    kind = graphene.String(required=True, description='send | payout | buy')
    rule_id = graphene.String()
    amount_usd = graphene.String()
    frequency = graphene.String()
    first_run_at = graphene.String(description='ISO-8601; null = from now')
    payee_handle = graphene.String()
    payee_name = graphene.String()
    payout_method_id = graphene.String()
    payout_label = graphene.String()
    asset_key = graphene.String()
    asset_name = graphene.String()
    sentence = graphene.String(required=True)
    # The step's place in the whole proposal (signed steps are left out, so
    # it is not the list position): sent back with the prepare as
    # proposalStep.
    step_index = graphene.Int()


class AssistantRuleProposalType(graphene.ObjectType):
    # Only the steps still to sign: one the owner already signed (on the
    # wire or final) is never offered again.
    steps = graphene.List(graphene.NonNull(AssistantRuleStepType), required=True)
    expired = graphene.Boolean(required=True)
    signed_steps = graphene.Int(description='Steps of this proposal already signed')
    done = graphene.Boolean(description='Every step is already signed: nothing is left to sign')
    message = graphene.String(description='Spanish, for the owner, when done')


RULE_PROPOSAL_DONE_MESSAGE = ('Ya firmaste este plan. Puedes verlo en tus reglas; '
                              'si algo todavía se está confirmando, espera a que aparezca.')
RULE_PROPOSAL_UNREADABLE_MESSAGE = 'No pudimos revisar este plan. Ábrelo de nuevo en un momento.'


RULE_PROPOSAL_TTL_DAYS = 7


class Query(graphene.ObjectType):
    # Own field (isolated from the thread query): only builds that open the
    # proposal chip ask for it.
    assistant_rule_proposal = graphene.Field(
        AssistantRuleProposalType, message_id=graphene.ID(required=True),
        description="The Cuenta inteligente rule proposal on one of the viewer's own assistant messages.")

    @login_required
    def resolve_assistant_rule_proposal(self, info, message_id):
        from datetime import datetime, timedelta

        from django.utils import timezone
        from inbox.models import SupportMessage

        user = info.context.user
        try:
            message = SupportMessage.objects.filter(
                pk=int(message_id), conversation__user=user, sender_type__in=('AGENT', 'SYSTEM')).first()
        except (TypeError, ValueError):
            message = None
        proposal = (message.metadata or {}).get('rule_proposal') if message is not None else None
        if not isinstance(proposal, dict) or not proposal.get('steps'):
            return None
        expired, created = True, None
        try:
            created = datetime.fromisoformat(proposal.get('created_at') or '')
            expired = created < timezone.now() - timedelta(days=RULE_PROPOSAL_TTL_DAYS)
        except ValueError:
            pass
        steps = [step for step in proposal['steps'] if isinstance(step, dict)]
        signed = [False] * len(steps)
        if created is not None and not expired:
            from smart_account.services import proposal_signed_steps
            try:
                signed = proposal_signed_steps(user, message.pk, steps, created)
            except Exception:  # noqa: BLE001 — fails closed: nothing offered to sign
                logger.exception('assistant rule proposal progress failed')
                return AssistantRuleProposalType(expired=expired, steps=[], signed_steps=0, done=False,
                                                 message=RULE_PROPOSAL_UNREADABLE_MESSAGE)
        fields = set(AssistantRuleStepType._meta.fields) - {'step_index'}
        open_steps = [
            AssistantRuleStepType(step_index=index, **{k: v for k, v in step.items() if k in fields})
            for index, step in enumerate(steps) if not signed[index]]
        done = bool(steps) and not open_steps
        return AssistantRuleProposalType(
            expired=expired, steps=open_steps, signed_steps=sum(signed), done=done,
            message=RULE_PROPOSAL_DONE_MESSAGE if done else None)

    assistant_walk = graphene.Field(
        AssistantWalkType, key=graphene.String(required=True),
        description='The steps of a walk the person asked for. Null when they can\'t do it now.')

    @login_required
    def resolve_assistant_walk(self, info, key):
        from . import guide

        user, account, business, jwt_context = get_context_models(info)
        meta = getattr(info.context, 'META', None)
        try:
            viewer = service._viewer(user, account, business, jwt_context, request_meta=meta)
            trail = guide.walk_trail(viewer, key, meta)
        except Exception:  # noqa: BLE001 - the chat explains it in words instead
            logger.exception('assistant walk failed')
            return None
        if not trail:
            return None
        return AssistantWalkType(key=key, trail=[
            AssistantGuideTrailStopType(route=t.route, text=t.text, pointer=t.pointer) for t in trail])

    assistant_guide = graphene.Field(
        AssistantGuideType, screen=graphene.String(),
        context_key=graphene.String(description='Active account id; only keys the client cache per account'),
        description='The first-steps card to show now. Null means no card.')

    @login_required
    def resolve_assistant_guide(self, info, screen=None, context_key=None):
        from . import guide

        user, account, business, jwt_context = get_context_models(info)
        try:
            viewer = service._viewer(user, account, business, jwt_context, screen=screen or '',
                                     request_meta=getattr(info.context, 'META', None))
            conversation = get_or_create_support_conversation(user, account, business)
            if service.is_human_mode(conversation):
                return None
            found = guide.current(
                viewer, getattr(info.context, 'META', {}), conversation=conversation, first_name=user.first_name,
                account_label=service._account_label(viewer, business), country=country_of(user))
        except Exception:  # noqa: BLE001 - no card is always safe
            logger.exception('assistant guide failed')
            return None
        if found is None:
            return None
        return AssistantGuideType(
            step=found.key, stage=found.stage, text=found.text,
            presentation=found.presentation,
            chips=[AssistantGuideChipType(
                label=c.label, kind=c.kind, answer=c.answer,
                trail=[AssistantGuideTrailStopType(route=t.route, text=t.text, pointer=t.pointer) for t in c.trail])
                for c in found.chips])

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

    assistant_top_up = graphene.Field(
        AssistantTopUpType, required=True, message_id=graphene.ID(required=True),
        description="The order the top-up form on one of the viewer's own assistant messages created, if any.")

    @login_required
    def resolve_assistant_top_up(self, info, message_id):
        from . import topup_limits
        status, order = topup_limits.card(info.context.user, message_id)
        return AssistantTopUpType(status=status, **(order or {}))

    assistant_stock_trade = graphene.Field(
        AssistantStockTradeType, required=True, message_id=graphene.ID(required=True),
        description="Whether the stock-trade card on one of the viewer's own assistant messages already traded.")

    @login_required
    def resolve_assistant_stock_trade(self, info, message_id):
        from . import trades
        status, tx_hash = trades.status(info.context.user, message_id)
        return AssistantStockTradeType(status=status, tx_hash=tx_hash or None)

    assistant_relay_trade = graphene.Field(
        AssistantRelayTradeType, trade=graphene.UUID(required=True),
        description="One hands-off chat trade of the viewer's (its own query: older servers lack it).")

    @login_required
    def resolve_assistant_relay_trade(self, info, trade):
        from smart_account import relay_trades
        found = relay_trades.status_of(info.context.user, trade)
        return AssistantRelayTradeType(**found) if found else None

    assistant_relay_purchase = graphene.Field(
        AssistantRelayPurchaseType, purchase=graphene.UUID(required=True),
        description="One hands-off chat purchase in Comprar of the viewer's (its own query: older servers lack it).")

    @login_required
    def resolve_assistant_relay_purchase(self, info, purchase):
        from smart_account import relay_purchases
        found = relay_purchases.status_of(info.context.user, purchase)
        return AssistantRelayPurchaseType(**found) if found else None

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
        guide_step = graphene.String(description='Typed in the first-steps card: steer back to this step')
        photo_base64 = graphene.String(description='A photo sent with the message, base64. Shown to the '
                                                   'assistant, never stored.')
        photo_mime_type = graphene.String()

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
               audio_duration_ms=None, screen=None, timezone=None, guide_step=None,
               photo_base64=None, photo_mime_type=None):
        user, account, business, jwt_context = get_context_models(info)
        audio = (audio_base64, audio_mime_type, audio_duration_ms) if audio_base64 else None
        # A photo goes with typed words (or none), never with a voice note.
        photo = (photo_base64, photo_mime_type) if photo_base64 and not audio else None
        if not audio and not photo and not (body or '').strip():
            raise GraphQLError('Message body is required')
        try:
            # Transcription happens inside, after the quota/human-mode checks.
            outcome = service.ask(user, account, business, jwt_context, None if audio else body, audio=audio,
                                  screen=screen or '', tz_name=timezone, guide_step=guide_step or '',
                                  photo=photo, request_meta=getattr(info.context, 'META', None))
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
                                         ticker=a.get('ticker'), label=a.get('label'), source=a.get('source'))
                     for a in outcome.actions],
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
        user, account, business, jwt_context = get_context_models(info)
        conversation = service.return_to_ai(user, account, business, jwt_context,
                                            request_meta=getattr(info.context, 'META', None))
        return ReturnToAssistant(success=True, mode=getattr(conversation, 'returned_mode', 'AI'))


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
                country=country_of(user),
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
        return cls(output=output, handed_off=False, keep_going=True)


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


class RecordAssistantGuideEvent(graphene.Mutation):
    """shown, accepted or dismissed, for one step of the first-steps guide."""

    class Arguments:
        step = graphene.String(required=True)
        event = graphene.String(required=True)
        answer = graphene.String(description='The opening question\'s answer, when a chip carries one')
        detail = graphene.String(description='Which option or button, for the funnel')

    success = graphene.Boolean(required=True)
    error = graphene.String()

    @login_required
    def mutate(self, info, step, event, answer=None, detail=None):
        from users.funding import has_funded

        from . import guide

        user, account, business, jwt_context = get_context_models(info)
        viewer = service._viewer(user, account, business, jwt_context)
        if viewer.account_type == 'business':
            return RecordAssistantGuideEvent(success=False, error='No disponible')
        try:
            guide.record_event(viewer, step, event, answer=answer, funded=has_funded(user), detail=detail or '')
        except ValueError as exc:
            return RecordAssistantGuideEvent(success=False, error=str(exc))
        return RecordAssistantGuideEvent(success=True)


class Mutation(graphene.ObjectType):
    record_assistant_guide_event = RecordAssistantGuideEvent.Field()
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
    claim_assistant_stock_trade = ClaimAssistantStockTrade.Field()
    attach_assistant_top_up = AttachAssistantTopUp.Field()
    release_assistant_stock_trade = ReleaseAssistantStockTrade.Field()
    prepare_assistant_trade_cap = PrepareAssistantTradeCap.Field()
    prepare_assistant_account_migration = PrepareAssistantAccountMigration.Field()
    prepare_assistant_trade_move = PrepareAssistantTradeMove.Field()
    resume_assistant_relay_trade = ResumeAssistantRelayTrade.Field()
    prepare_assistant_purchase_cap = PrepareAssistantPurchaseCap.Field()
    prepare_assistant_purchase_move = PrepareAssistantPurchaseMove.Field()
    resume_assistant_relay_purchase = ResumeAssistantRelayPurchase.Field()
