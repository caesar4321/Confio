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
    rating = graphene.String(description='Its star rating as the store writes it (out of 5), or empty')
    reviews = graphene.String(description='How many reviews, as the store writes it, or empty')
    cap = graphene.String(description='The most it may cost with shipping and taxes: choosing it approves up to this '
                                      '(spec decision 42). Empty when its price could not be read.')
    unit = graphene.String(description='Its price as a plain number ("1249.00"), only when `cap` is set: the app '
                                       'works out the top total of several chosen products from it (capRule).')


class AgentCapRuleType(graphene.ObjectType):
    """How a top total is worked out from chosen prices (operate.cart_top): the sum of unit price times
    quantity, plus the larger of sum × margin and minExtra, rounded up to a whole unit; written in the
    first chosen product's price text, with `commaDecimals` (1.249,00) or not (1,249.00)."""
    margin = graphene.String(required=True)
    min_extra = graphene.String(required=True)
    comma_decimals = graphene.Boolean(required=True)
    max_quantity = graphene.Int(required=True)


class AgentOrderItemType(graphene.ObjectType):
    """One product chosen into the order's cart, with how many."""
    title = graphene.String(required=True)
    quantity = graphene.Int(required=True)
    image = graphene.String(required=True)


class AgentPickInput(graphene.InputObjectType):
    index = graphene.Int(required=True)
    quantity = graphene.Int(required=True)


class AgentOrderType(graphene.ObjectType):
    """The order the person approves in the chat: the store's own words."""
    items = graphene.List(graphene.NonNull(AgentOrderItemType), required=True,
                          description='The products chosen into one cart with their quantities; empty for one item '
                                      'chosen the older way (`item` names it)')
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
    notify = graphene.String(required=True, description="With reason `no_rail` (this country's stores cannot be paid "
                                                        "yet) or `payer_data` (a Venezuelan store that asks the payer's "
                                                        "own data): '' unanswered, 'yes' (Sí, avísame) or 'no' (Solo "
                                                        "miraba), answered with answerAgentNotify")
    order = graphene.Field(AgentOrderType, description='With reason `approve`: confirm with approveAgentOrder. With `subscribe`, approveAgentOrder only resumes once subscribed')
    options = graphene.List(graphene.NonNull(AgentOptionType), required=True,
                            description='With reason `choose`: pick one or more, each with a quantity, with '
                                        'chooseAgentOptions (older builds: chooseAgentOption(index))')
    cap_rule = graphene.Field(AgentCapRuleType, description='With reason `choose`: how the top total of the chosen '
                                                            'products is worked out, shown before the tap')


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
REPORTING = 'Pasándole a {site} la referencia de tu pago…'
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
    if task.state in ('queued', 'working') and task.phase == 'report':
        message = REPORTING.format(site=task.site)   # paid by Pago Móvil: the reference goes to the store
    elif task.state == 'working':
        message = WORKING_AT.get(stage, WORKING['working']).format(site=task.site)
    elif task.state in WORKING:
        message = WORKING[task.state].format(site=task.site)
    elif task.state == 'needs_person' and task.reason == 'account_wait':
        # Why the Cuenta inteligente cannot pay it yet, with its figures (account_pay.figures).
        message = str(((task.order or {}).get('account_wait') or {}).get('text') or '') or notes.say(
            notes.ACCOUNT_STILL, task).strip()
    elif task.state == 'needs_person':
        reason = task.reason
        if reason == 'login' and int((task.counts or {}).get('asked_login') or 0) > 1:
            reason = 'login_again'
        if reason == 'approve' and (task.order or {}).get('manual'):
            reason = 'approve_manual'   # the card they confirm on says they pay it themselves
        message = notes.say(notes.NEEDS_PERSON.get(reason, notes.NEEDS_PERSON['choice']), task).replace(
            '{step}', str(((task.order or {}).get('ask_step') or {}).get('label') or '')[:80]).replace(
            '{what}', str(((task.order or {}).get('request') or {}).get('what') or '')[:120])
        if task.reason in ('approve', 'subscribe'):
            message += notes.breakdown_text(task.order)   # what the total is made of: today's app shows this text
    elif task.state == 'payment_ready' and task.reason == 'manual':
        message = notes.manual_text(task)
    elif task.state == 'payment_ready' and task.reason == 'reported':
        message = notes.reported_text(task)
    elif task.state == 'payment_ready' and task.reason == 'account':
        from . import account_pay
        message = account_pay.paid_text(task)   # paid by the account: there is no card to review
    elif task.state == 'payment_ready':
        message = notes.say(notes.PAYMENT_READY, task)
    elif task.reason in notes.ACCOUNT_STOPPED:
        message = notes.say(notes.ACCOUNT_STOPPED[task.reason], task)
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
        notify=str((task.order or {}).get('notify') or '') if task.reason in ('no_rail', 'payer_data') else '',
        request=str(((task.order or {}).get('request') or {}).get('what') or '') or None
        if task.state == 'needs_person' and task.reason == 'act' else None,
        request_button=str(((task.order or {}).get('request') or {}).get('button') or '') or None
        if task.state == 'needs_person' and task.reason == 'act' else None,
        order=(AgentOrderType(items=[AgentOrderItemType(title=str(one.get('title') or ''),
                                                        quantity=int(one.get('quantity') or 1),
                                                        image=str(one.get('image') or ''))
                                     for one in (task.order.get('items') or []) if isinstance(one, dict)],
                              item=str(task.order.get('item') or ''), total=str(task.order.get('total') or ''),
                              image=str(task.order.get('image') or ''),
                              address=str(task.order.get('address') or ''),
                              breakdown=[AgentPayDetailType(label=notes.BREAKDOWN_LABELS[line['kind']].capitalize(),
                                                            value=('- ' if line['kind'] == 'discount' else '')
                                                            + str(line.get('amount') or ''))
                                         for line in (task.order.get('breakdown') or [])
                                         if line.get('kind') in notes.BREAKDOWN_LABELS])
               if task.order else None),
        options=[AgentOptionType(title=str(o.get('title') or ''), rating=str(o.get('rating') or ''), reviews=str(o.get('reviews') or ''), price=str(o.get('price') or ''),
                                 image=str(o.get('image') or ''), cap=str(o.get('cap') or '') or None,
                                 unit=_unit(o, task.country))
                 for o in (task.options or [])],
        cap_rule=_cap_rule(task.country) if task.state == 'needs_person' and task.reason == 'choose' else None)


def _unit(option, country):
    """An offered product's price as a plain number, only when its top total was set (its price was read)."""
    from . import operate
    if not option.get('cap_amount'):
        return None
    price = operate.unit_price(option.get('price'), country)
    return format(price, 'f') if price is not None else None


def _cap_rule(country):
    from . import conf, operate
    return AgentCapRuleType(margin=str(conf.get('AGENT_TASKS_CAP_MARGIN')),
                            min_extra=str((conf.get('AGENT_TASKS_CAP_MIN_EXTRA') or {}).get(country, '0')),
                            comma_decimals=country in operate.COMMA_DECIMALS, max_quantity=operate.MAX_QUANTITY)


class AgentAccountWaitType(graphene.ObjectType):
    """A purchase waiting for the Cuenta inteligente (reason `account_wait`). Never paid from the personal
    wallet: the one action is signed with prepareAgentAccountWait, then resumeAgentPayment."""
    code = graphene.String(required=True, description='no_rule | move | cap | topup | renew')
    amount_usd = graphene.String(description='The action\'s amount: the cap to sign (no_rule, cap) or the dollars '
                                             'to move (move). The server\'s, never sent back.')
    until = graphene.DateTime(description='How long it waits; then it stops with nothing paid.')


def _account_wait(found):
    figures, task = found
    if not figures:
        return None
    return AgentAccountWaitType(code=str(figures.get('code') or ''), amount_usd=str(figures.get('amount_usd') or '')
                                or None, until=task.wait_until)


class Query(graphene.ObjectType):
    agent_account_wait = graphene.Field(AgentAccountWaitType, id=graphene.UUID(required=True))
    agent_task = graphene.Field(AgentTaskType, id=graphene.UUID(required=True))
    agent_active_task = graphene.Field(AgentTaskType)
    agent_stores = graphene.List(graphene.NonNull(graphene.String),
                                 description="Stores that keep the person's sign-in, each deletable")

    def resolve_agent_account_wait(self, info, id):
        return _read(lambda: _account_wait(service.account_wait(*_owner(info), id)))

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


class ResumeAgentPayment(_Result):
    """"Ya lo hice: pagar" on a purchase waiting for the Cuenta inteligente: the account is asked again."""
    class Arguments:
        id = graphene.UUID(required=True)

    @classmethod
    def mutate(cls, root, info, id):
        try:
            return cls(success=True, errors=[], task=task_type(service.resume_payment(*_owner(info), id)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


def _prepare_account_wait(info, id):
    """The owner-signed batch a waiting purchase needs, as the Cuenta inteligente's own prepare flows build it
    (smart_account.purchases): its amount is the task's, never the client's."""
    from decimal import Decimal

    from smart_account import purchases
    from smart_account.schema import _batch_error, _prepare
    try:
        figures, _task = service.account_wait(*_owner(info), id)
    except service.TaskRefused as exc:
        return _batch_error(exc.code, str(exc))
    code = str((figures or {}).get('code') or '')
    amount = str((figures or {}).get('amount_usd') or '')
    if code in ('no_rule', 'cap') and amount:
        return _prepare(info, lambda viewer: purchases.prepare_purchase_rule(viewer, Decimal(amount)))
    if code == 'move' and amount:
        return _prepare(info, lambda viewer: purchases.prepare_move_for_purchase(viewer, amount))
    return _batch_error('not_open', service.MESSAGES['not_open'])


def _prepared_batch_type():
    from smart_account.schema import SmartAccountPreparedBatchType
    return SmartAccountPreparedBatchType


class PrepareAgentAccountWait(graphene.Mutation):
    """Switch purchases on, raise the cap or move money in, for the purchase waiting for the account."""
    class Arguments:
        id = graphene.UUID(required=True)

    Output = _prepared_batch_type()

    def mutate(self, info, id):
        return _prepare_account_wait(info, id)


class ChooseAgentOption(_Result):
    class Arguments:
        id = graphene.UUID(required=True)
        index = graphene.Int(required=True)
        cap = graphene.String(description='The top total the tapped card showed (spec decision 42), as sent in '
                                          'options.cap: choosing approves up to it only when it is sent back')

    @classmethod
    def mutate(cls, root, info, id, index, cap=None):
        try:
            return cls(success=True, errors=[], task=task_type(service.choose(*_owner(info), id, index, cap=cap)))
        except Exception as exc:  # noqa: BLE001
            return _failure(cls, exc)


class ChooseAgentOptions(_Result):
    """One or more of the products offered, each with a quantity, confirmed with one tap (spec decision 42)."""
    class Arguments:
        id = graphene.UUID(required=True)
        items = graphene.List(graphene.NonNull(AgentPickInput), required=True,
                              description='Each chosen option (its index in `options`) and how many (1 to 9)')
        cap = graphene.String(description='The top total the confirm button showed (capRule): choosing approves up '
                                          'to it only when it is the one worked out from these items')

    @classmethod
    def mutate(cls, root, info, id, items, cap=None):
        try:
            picks = [{'index': pick.index, 'quantity': pick.quantity} for pick in items or []]
            return cls(success=True, errors=[], task=task_type(service.choose_cart(*_owner(info), id, picks, cap=cap)))
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


class AnswerAgentNotify(_Result):
    """Sí, avísame or Solo miraba on a purchase stopped because its country's stores cannot be paid yet: the
    intent probe for store payments there (the task keeps its store's country)."""
    class Arguments:
        id = graphene.UUID(required=True)
        yes = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, id, yes):
        try:
            return cls(success=True, errors=[], task=task_type(service.answer_notify(*_owner(info), id, bool(yes))))
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
    resume_agent_payment = ResumeAgentPayment.Field()
    prepare_agent_account_wait = PrepareAgentAccountWait.Field()
    cancel_agent_task = CancelAgentTask.Field()
    choose_agent_option = ChooseAgentOption.Field()
    choose_agent_options = ChooseAgentOptions.Field()
    sign_in_agent_store = SignInAgentStore.Field()
    give_agent_code = GiveAgentCode.Field()
    approve_agent_order = ApproveAgentOrder.Field()
    answer_agent_step = AnswerAgentStep.Field()
    answer_agent_request = AnswerAgentRequest.Field()
    answer_agent_notify = AnswerAgentNotify.Field()
    open_agent_live_view = OpenAgentLiveView.Field()
    forget_agent_store = ForgetAgentStore.Field()
