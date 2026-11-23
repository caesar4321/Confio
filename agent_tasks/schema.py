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
    checkout_handed = graphene.Boolean(
        required=True, description='The person has the checkout: there may be an order even if the task stops')
    payment_intent_id = graphene.UUID()
    created_at = graphene.DateTime(required=True)


WORKING = {
    'queued': 'Abriendo {site}…',
    'working': 'Buscando en {site}…',
    'awaiting_code': 'Leyendo el QR de tu pantalla…',
}


def task_type(task):
    if task is None:
        return None
    from . import notes
    if task.state in WORKING:
        message = WORKING[task.state].format(site=task.site)
    elif task.state == 'needs_person':
        message = notes.say(notes.NEEDS_PERSON.get(task.reason, notes.NEEDS_PERSON['choice']), task)
    elif task.state == 'payment_ready':
        message = notes.say(notes.PAYMENT_READY, task)
    else:
        message = notes.stopped_text(task, task.reason)
    return AgentTaskType(
        id=task.internal_id, goal=task.goal, site=task.site, status=task.state, reason=task.reason, message=message,
        wait_until=task.wait_until, checkout_handed=task.checkout_at is not None,
        payment_intent_id=task.payment_intent.internal_id if task.payment_intent_id else None,
        created_at=task.created_at)


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
    open_agent_live_view = OpenAgentLiveView.Field()
    forget_agent_store = ForgetAgentStore.Field()
