"""GraphQL of cloud-browser tasks. Account from the JWT; no account id is taken."""
import logging
from urllib.parse import urlsplit

import graphene
from graphql import GraphQLError

from . import service

logger = logging.getLogger(__name__)


def _owner(info):
    from payment_accounts.schema import _active_account
    from payment_accounts.services import PaymentAccountError
    user = getattr(info.context, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        raise service.TaskRefused('unavailable')
    try:
        account = _active_account(info, permission='send_funds', owner_only=True)
    except PaymentAccountError as exc:
        raise service.TaskRefused('not_personal') from exc
    service.require_owner(account, user)
    return account, user


def _failure(cls, exc):
    if isinstance(exc, service.TaskRefused):
        return cls(success=False, errors=[str(exc)], error_code=exc.code)
    logger.exception('agent task request failed')
    return cls(success=False, errors=['No pude hacerlo ahora. Inténtalo de nuevo.'], error_code='error')


def _read(resolve):
    try:
        return resolve()
    except service.TaskRefused as exc:
        if exc.code in ('not_found', 'not_personal'):
            return None
        raise GraphQLError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never a raw error to the app
        logger.warning('agent task read failed: %s', type(exc).__name__)
        raise GraphQLError('No pude leer eso ahora. Inténtalo de nuevo.') from None


class AgentOptionType(graphene.ObjectType):
    """A product the store's page showed: its words and picture are the store's, not Confío's."""
    title = graphene.String(required=True)
    price = graphene.String(required=True)
    image = graphene.String(required=True)


class AgentOrderType(graphene.ObjectType):
    """The order the person approves in the chat: the store's own words."""
    item = graphene.String(required=True)
    total = graphene.String(required=True)
    image = graphene.String(required=True)
    address = graphene.String(description='Where it is delivered, as the checkout writes it: part of the approval.')
    breakdown = graphene.List(graphene.NonNull(lambda: AgentPayDetailType), required=True,
                              description='What makes up the total (productos, envío...), checked to add up to it.')


class AgentPayDetailType(graphene.ObjectType):
    """One line of the data the person pays the order with, as the store's order page writes it."""
    label = graphene.String(required=True)
    value = graphene.String(required=True)


class AgentTaskType(graphene.ObjectType):
    id = graphene.UUID(required=True)
    goal = graphene.String(required=True)
    site = graphene.String(required=True)
    status = graphene.String(
        required=True, description='queued | working | needs_person | awaiting_code | payment_ready | stopped '
                                   '| cancelled')
    reason = graphene.String(required=True)
    message = graphene.String(required=True)
    wait_until = graphene.DateTime()
    stage = graphene.String(required=True, description='search | cart | checkout | pay | done | manage')
    kind = graphene.String(required=True, description="buy | manage (an order already placed)")
    request = graphene.String(description='The request about an order the person is asked to approve (manage).')
    request_button = graphene.String(description="The store's own button that sends it, as the page writes it.")
    checkout_handed = graphene.Boolean(
        required=True, description='The person has the checkout: there may be an order even if the task stops')
    payment_intent_id = graphene.UUID()
    pay_qr = graphene.String(description="The store's QR the person pays from their bank's app (no Confío payment).")
    pay_details = graphene.List(graphene.NonNull(AgentPayDetailType), required=True,
                                description='What the person pays the order with from their bank (no Confío payment).')
    open_account_method = graphene.String(
        description='The local account (LocalAccountApplication methodId) that would let Confío pay it next time.')
    created_at = graphene.DateTime(required=True)
    order = graphene.Field(AgentOrderType, description='With reason `approve`: confirm with approveAgentOrder')
    options = graphene.List(graphene.NonNull(AgentOptionType), required=True,
                            description='With reason `choose`: pick one with chooseAgentOption(index)')


WORKING = {
    'queued': 'Abriendo {site}…',
    'working': 'Trabajando en {site}…',
    'awaiting_code': 'Preparando el pago de tu pedido…',
}
# What it is doing, by where the purchase is (stage_of): never that anything was bought.
WORKING_AT = {
    'search': 'Buscando en {site}…',
    'cart': 'Preparando tu carrito en {site}…',
    'checkout': 'Preparando tu pedido en {site}…',
    'pay': 'Preparando el pago de tu pedido…',
    'manage': 'Revisando tu pedido en {site}…',
}
STAGES = ('search', 'cart', 'checkout', 'pay', 'done', 'manage')


def stage_of(task):
    """Where the purchase is, for the card's journey: search, cart, checkout, pay, done. Where it
    stopped stays where it was."""
    from . import guard
    if getattr(task, 'kind', 'buy') == 'manage':
        return 'manage'   # an order already placed: no purchase journey
    if task.state == 'payment_ready':
        return 'done'
    if task.phase == 'ordered' or task.state == 'awaiting_code' or task.checkout_at is not None:
        return 'pay'
    if task.phase == 'ordering':
        last = str(((task.trace or [{}])[-1] or {}).get('url') or '')
        return 'checkout' if last and guard.checkout_address(f'https://{last}') else 'cart'
    return 'search'


def task_type(task):
    if task is None:
        return None
    from . import notes
    stage = stage_of(task)
    if task.state == 'working':
        message = WORKING_AT.get(stage, WORKING['working']).format(site=task.site)
    elif task.state in WORKING:
        message = WORKING[task.state].format(site=task.site)
    elif task.state == 'needs_person':
        reason = task.reason
        if reason == 'login' and int((task.counts or {}).get('asked_login') or 0) > 1:
            reason = 'login_again'
        if reason == 'approve' and (task.order or {}).get('manual'):
            reason = 'approve_manual'   # the card they confirm on says they pay it themselves
        message = notes.say(notes.NEEDS_PERSON.get(reason, notes.NEEDS_PERSON['choice']), task).replace(
            '{step}', str(((task.order or {}).get('ask_step') or {}).get('label') or '')[:80]).replace(
            '{what}', str(((task.order or {}).get('request') or {}).get('what') or '')[:120])
        if task.reason == 'approve':
            message += notes.breakdown_text(task.order)   # what the total is made of: today's app shows this text
    elif task.state == 'payment_ready' and task.reason == 'manual':
        message = notes.manual_text(task)
    elif task.state == 'payment_ready':
        message = notes.say(notes.PAYMENT_READY, task)
    else:
        message = notes.stopped_text(task, task.reason)
    return AgentTaskType(
        id=task.internal_id, goal=task.goal, site=task.site, status=task.state, reason=task.reason, message=message,
        wait_until=task.wait_until, checkout_handed=task.checkout_at is not None,
        payment_intent_id=task.payment_intent.internal_id if task.payment_intent_id else None,
        # The store's own QR, for the person to pay from their bank (only when Confío cannot).
        pay_qr=str((task.order or {}).get('pay_qr') or '') or None if task.state == 'payment_ready' else None,
        pay_details=[AgentPayDetailType(label=str(d.get('label') or ''), value=str(d.get('value') or ''))
                     for d in ((task.order or {}).get('pay_details') or []) if isinstance(d, dict)]
        if task.state == 'payment_ready' else [],
        open_account_method=str((task.order or {}).get('offer') or '') or None,
        created_at=task.created_at, stage=stage, kind=getattr(task, 'kind', 'buy') or 'buy',
        request=str(((task.order or {}).get('request') or {}).get('what') or '') or None
        if task.state == 'needs_person' and task.reason == 'act' else None,
        request_button=str(((task.order or {}).get('request') or {}).get('button') or '') or None
        if task.state == 'needs_person' and task.reason == 'act' else None,
        order=(AgentOrderType(item=str(task.order.get('item') or ''), total=str(task.order.get('total') or ''),
                              image=str(task.order.get('image') or ''),
                              address=str(task.order.get('address') or ''),
                              breakdown=[AgentPayDetailType(label=notes.BREAKDOWN_LABELS[line['kind']].capitalize(),
                                                            value=('- ' if line['kind'] == 'discount' else '')
                                                            + str(line.get('amount') or ''))
                                         for line in (task.order.get('breakdown') or [])
                                         if line.get('kind') in notes.BREAKDOWN_LABELS])
               if task.order else None),
        options=[AgentOptionType(title=str(o.get('title') or ''), price=str(o.get('price') or ''),
                                 image=str(o.get('image') or '')) for o in (task.options or [])])


class Query(graphene.ObjectType):
    agent_task = graphene.Field(AgentTaskType, id=graphene.UUID(required=True))
    agent_active_task = graphene.Field(AgentTaskType)
    agent_stores = graphene.List(graphene.NonNull(graphene.String),
                                 description="Stores that keep the person's sign-in, each deletable")

    def resolve_agent_task(self, info, id):
        return _read(lambda: task_type(service.get(*_owner(info), id)))

    def resolve_agent_active_task(self, info):
        return _read(lambda: task_type(service.active(*_owner(info))))

    def resolve_agent_stores(self, info):
        return _read(lambda: service.stores(*_owner(info)))


class _Result(graphene.Mutation):
    class Meta:
        abstract = True

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    task = graphene.Field(AgentTaskType)


class StartAgentTask(_Result):
    class Arguments:
        goal = graphene.String(required=True, description="The person's own words")
        site = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, goal, site):
        try:
            task = service.start(*_owner(info), goal=goal, site=site, meta=getattr(info.context, 'META', None))
            return cls(success=True, errors=[], task=task_type(task))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class _ById(_Result):
    class Meta:
        abstract = True

    @classmethod
    def mutate(cls, root, info, id):
        try:
            return cls(success=True, errors=[], task=task_type(cls.apply(*_owner(info), id)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class ResumeAgentTask(_Result):
    class Arguments:
        id = graphene.UUID(required=True)
        view = graphene.String(description='The `view` of the screen the person was looking at (openAgentLiveView)')

    @classmethod
    def mutate(cls, root, info, id, view=None):
        try:
            return cls(success=True, errors=[], task=task_type(service.resume(*_owner(info), id, view=view)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class ChooseAgentOption(_Result):
    class Arguments:
        id = graphene.UUID(required=True)
        index = graphene.Int(required=True)

    @classmethod
    def mutate(cls, root, info, id, index):
        try:
            return cls(success=True, errors=[], task=task_type(service.choose(*_owner(info), id, index)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class SignInAgentStore(_Result):
    """The person's account at the store, typed in the chat's card. Stored encrypted; never echoed."""
    class Arguments:
        id = graphene.UUID(required=True)
        identifier = graphene.String(required=True)
        password = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, id, identifier, password):
        try:
            return cls(success=True, errors=[], task=task_type(service.sign_in(*_owner(info), id, identifier, password)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class GiveAgentCode(_Result):
    class Arguments:
        id = graphene.UUID(required=True)
        code = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, id, code):
        try:
            return cls(success=True, errors=[], task=task_type(service.give_code(*_owner(info), id, code)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class ApproveAgentOrder(_Result):
    class Arguments:
        id = graphene.UUID(required=True)
        total = graphene.String(description='The total on the card the person saw')

    @classmethod
    def mutate(cls, root, info, id, total=None):
        try:
            return cls(success=True, errors=[], task=task_type(service.approve(*_owner(info), id, total=total)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class AnswerAgentRequest(_Result):
    """Yes or no to a request about an order already placed (cancel, return, refund): sent only on yes."""
    class Arguments:
        id = graphene.UUID(required=True)
        yes = graphene.Boolean(required=True)
        what = graphene.String(description='The request the card showed: a yes is for that one only')

    @classmethod
    def mutate(cls, root, info, id, yes, what=None):
        try:
            return cls(success=True, errors=[], task=task_type(
                service.answer_request(*_owner(info), id, bool(yes), what=what)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class AnswerAgentStep(_Result):
    """Yes or no to one step the agent could not judge by itself ("¿lo hago?")."""
    class Arguments:
        id = graphene.UUID(required=True)
        yes = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, id, yes):
        try:
            return cls(success=True, errors=[], task=task_type(service.answer_step(*_owner(info), id, bool(yes))))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class CancelAgentTask(_ById):
    class Arguments:
        id = graphene.UUID(required=True)

    @classmethod
    def apply(cls, *args):
        return service.cancel(*args)


class OpenAgentLiveView(graphene.Mutation):
    """A mutation on purpose: the URL controls the browser and must not be cached."""
    class Arguments:
        id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()
    url = graphene.String()
    expires_in = graphene.Int()
    site = graphene.String(description='The store of the task')
    page_host = graphene.String(description='Show it above the screen: the host that was showing when it opened')
    host = graphene.String(description="The live view's own host, for the WebView's allow-list")
    view = graphene.String(description='Names the tab this screen shows: send it back with resumeAgentTask')

    @classmethod
    def mutate(cls, root, info, id):
        try:
            owner = _owner(info)
            url, seconds, showing, view = service.live_view(*owner, id)
            return cls(success=True, errors=[], url=url, expires_in=seconds, site=service.get(*owner, id).site,
                       page_host=showing, view=view,
                       host=urlsplit(url).hostname)
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class ForgetAgentStore(graphene.Mutation):
    class Arguments:
        site = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    error_code = graphene.String()

    @classmethod
    def mutate(cls, root, info, site):
        try:
            service.forget_store(*_owner(info), site)
            return cls(success=True, errors=[])
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class Mutation(graphene.ObjectType):
    start_agent_task = StartAgentTask.Field()
    resume_agent_task = ResumeAgentTask.Field()
    cancel_agent_task = CancelAgentTask.Field()
    choose_agent_option = ChooseAgentOption.Field()
    sign_in_agent_store = SignInAgentStore.Field()
    give_agent_code = GiveAgentCode.Field()
    approve_agent_order = ApproveAgentOrder.Field()
    answer_agent_step = AnswerAgentStep.Field()
    answer_agent_request = AnswerAgentRequest.Field()
    open_agent_live_view = OpenAgentLiveView.Field()
    forget_agent_store = ForgetAgentStore.Field()
