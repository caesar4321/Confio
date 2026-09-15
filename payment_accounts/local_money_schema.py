"""JWT-scoped local money API (Enviar/Recibir). Provider IDs never cross it.

Kept separate from the shared payment-account queries on purpose: the app asks
for these fields in their own operations, so an older server fails only the
local-money screens instead of every query that shares a document with them.
"""
import graphene
from send.schema import PrepareBscSend, BscSendCallType
from graphql import GraphQLError

from . import local_money
from .models import LedgerEntry, LimitIncreaseRequest, PaymentBridgeTransfer, PayoutDestination
from .services import PaymentAccountError


def _owner(info, permission, owner_only=False):
    from .schema import _active_account
    return _active_account(info, permission=permission, owner_only=owner_only)


def _identity(account, required=True):
    from .schema import _verified_identity
    try:
        return _verified_identity(account)
    except PaymentAccountError:
        if required:
            raise
        return None


def _query_error(exc):
    from .schema import _public_error
    return GraphQLError(_public_error(exc))


def _money(value):
    return None if value is None else str(value)


class LocalMethodType(graphene.ObjectType):
    id = graphene.String(required=True)
    direction = graphene.String(required=True)
    country = graphene.String(required=True)
    asset = graphene.String(required=True)
    title = graphene.String(required=True)
    subtitle = graphene.String(required=True)
    status = graphene.String(required=True)
    reason = graphene.String(required=True)
    account_status = graphene.String(required=True)
    # For status 'needs_document': what an additional-document session asks
    # for (ISO3 issuing country or '' for any; Didit type codes P/ID/DL).
    document_country = graphene.String(required=True)
    document_types = graphene.List(graphene.NonNull(graphene.String), required=True)


class LocalDestinationType(graphene.ObjectType):
    id = graphene.UUID(required=True)
    method_id = graphene.String(required=True)
    label = graphene.String(required=True)
    holder_name = graphene.String(required=True)
    holder_document = graphene.String(required=True)
    institution = graphene.String(required=True)
    verification = graphene.String(required=True)
    country = graphene.String(required=True)
    asset = graphene.String(required=True)


class LocalPayoutQuoteType(graphene.ObjectType):
    source_amount = graphene.String(required=True)
    target_amount = graphene.String(required=True)
    minimum_target = graphene.String(required=True)
    rate = graphene.String(required=True)
    asset = graphene.String(required=True)
    expires_at = graphene.String(required=True)


class LocalDepositQuoteType(graphene.ObjectType):
    source_amount = graphene.String(required=True)
    asset = graphene.String(required=True)
    target_amount = graphene.String(required=True)
    minimum_fx_output = graphene.String(required=True)
    minimum_wallet_output = graphene.String(required=True)
    rate = graphene.String(required=True)
    expires_at = graphene.String(required=True)


class LocalLimitsType(graphene.ObjectType):
    known = graphene.Boolean(required=True)
    has_account = graphene.Boolean(required=True)
    limit = graphene.String()
    used = graphene.String()
    available = graphene.String()
    resets_at = graphene.String(required=True)
    per_transfer_max = graphene.String()  # null: no per-transfer cap
    near_limit = graphene.Boolean(required=True)


class LocalReceiveAccountType(graphene.ObjectType):
    method_id = graphene.String(required=True)
    status = graphene.String(required=True)
    local_account_id = graphene.UUID()
    crypto_account_id = graphene.UUID()
    country = graphene.String(required=True)
    asset = graphene.String(required=True)
    instruction_kind = graphene.String(required=True)
    value = graphene.String(required=True)
    holder_name = graphene.String(required=True)
    institution = graphene.String(required=True)
    receive_same_name = graphene.String(required=True)
    receive_third_party = graphene.String(required=True)


class EddRequirementType(graphene.ObjectType):
    kind = graphene.String(required=True)
    title = graphene.String(required=True)
    detail = graphene.String(required=True)


class LimitIncreaseRequestType(graphene.ObjectType):
    id = graphene.UUID(required=True)
    status = graphene.String(required=True)
    income_type = graphene.String(required=True)
    user_message = graphene.String(required=True)
    submitted_at = graphene.DateTime()


def _destination(row):
    return LocalDestinationType(**local_money.destination_view(row))


def _request(row):
    return LimitIncreaseRequestType(id=row.internal_id, status=row.status, income_type=row.income_type,
                                    user_message=row.user_message, submitted_at=row.submitted_at)


class LocalMoneyQuery(graphene.ObjectType):
    local_money_methods = graphene.List(graphene.NonNull(LocalMethodType), required=True,
                                        direction=graphene.String(required=True))
    local_money_limits = graphene.Field(LocalLimitsType, required=True)
    local_receive_account = graphene.Field(LocalReceiveAccountType, required=True,
                                           method_id=graphene.String(required=True))
    local_saved_destinations = graphene.List(graphene.NonNull(LocalDestinationType), required=True,
                                             method_id=graphene.String(required=True))
    local_destination = graphene.Field(LocalDestinationType, id=graphene.UUID(required=True))
    local_payout_quote = graphene.Field(LocalPayoutQuoteType, destination_id=graphene.UUID(required=True),
                                        amount=graphene.Decimal(), bridge_id=graphene.UUID())
    local_deposit_quote = graphene.Field(LocalDepositQuoteType, credit_id=graphene.UUID(required=True))
    limit_increase_request = graphene.Field(LimitIncreaseRequestType)
    limit_increase_requirements = graphene.List(graphene.NonNull(EddRequirementType), required=True,
                                                income_type=graphene.String(required=True))

    def resolve_local_money_methods(self, info, direction):
        owner = _owner(info, 'view_balance')
        if direction not in {'send', 'receive'}:
            raise GraphQLError('Invalid direction')
        rows = local_money.methods(owner, _identity(owner, required=False), direction)
        from . import breb_location
        if direction == 'receive':
            # Bre-B is listed wherever the person is: its application checks the
            # location (device reading + IP) as a requirement, and every Bre-B
            # operation checks it again. Nothing is hidden up front.
            from django.conf import settings
            if breb_location.configured() and getattr(settings, 'COBRE_PAYMENT_ACCOUNTS_ENABLED', False):
                from .eligibility import context_from_identity, evaluate_active_policy
                identity = _identity(owner, required=False)
                allowed = False
                if identity and owner.account_type == 'personal':
                    try:
                        allowed = evaluate_active_policy(provider='cobre', scope='account_opening',
                            context=context_from_identity(identity, account_country='COL')).allowed
                    except Exception:
                        allowed = False
                if allowed:
                    # Cobre is a distinct application, never Infinia activation.
                    rows = [r for r in rows if r['method'].id != 'co_breb_receive']
                    rows.append(dict(method=local_money.Method('cobre_co_breb_receive', 'receive', 'COL', 'CO',
                        'COP', 'Llave Bre-B', 'Tu propia llave para recibir pesos', instruction_kind='breb_key'),
                        status='live', reason='', requirement=None, account_status='none'))
        return [LocalMethodType(
            id=row['method'].id, direction=row['method'].direction, country=row['method'].iso2,
            asset=row['method'].asset, title=row['method'].title, subtitle=row['method'].subtitle,
            status=row['status'], reason=row['reason'], account_status=row['account_status'],
            document_country=(row['requirement'] or {}).get('id_country', ''),
            document_types=(row['requirement'] or {}).get('document_types', []),
        ) for row in rows]

    def resolve_local_money_limits(self, info):
        view = local_money.limits(_owner(info, 'view_balance'))
        return LocalLimitsType(
            known=view['known'], has_account=view['has_account'], limit=_money(view['limit']),
            used=_money(view['used']), available=_money(view['available']), resets_at=view['resets_at'],
            per_transfer_max=None if view['per_transfer_max'] is None else str(view['per_transfer_max']),
            near_limit=view['near_limit'])

    def resolve_local_receive_account(self, info, method_id):
        owner = _owner(info, 'view_balance')
        try:
            view = local_money.receive_account(owner, method_id)
        except PaymentAccountError as exc:
            raise _query_error(exc)
        method = view['method']
        value, holder_name = view['value'], view['holder_name']
        if value:
            # A Bre-B key is shown only after a recent location check from an
            # allowed IP, like every other Bre-B operation.
            from . import breb_location
            try:
                breb_location.require_for_country(owner, method.country, info.context.META)
            except PaymentAccountError:
                value, holder_name = '', ''
        return LocalReceiveAccountType(
            method_id=method.id, status=view['status'],
            local_account_id=view['local'].internal_id if view['local'] else None,
            crypto_account_id=view['crypto'].internal_id if view['crypto'] else None,
            country=method.iso2, asset=method.asset, instruction_kind=method.instruction_kind,
            value=value, holder_name=holder_name, institution=view['institution'],
            receive_same_name=view['receive_same_name'], receive_third_party=view['receive_third_party'])

    def resolve_local_saved_destinations(self, info, method_id):
        owner = _owner(info, 'send_funds')
        try:
            return [_destination(row) for row in local_money.saved_destinations(owner, method_id)]
        except PaymentAccountError as exc:
            raise _query_error(exc)

    def resolve_local_destination(self, info, id):
        owner = _owner(info, 'send_funds')
        row = PayoutDestination.objects.filter(internal_id=id, confio_account=owner, provider='infinia').first()
        return _destination(local_money.refresh_destination(row)) if row else None

    def resolve_local_payout_quote(self, info, destination_id, amount=None, bridge_id=None):
        owner = _owner(info, 'send_funds')
        try:
            destination = PayoutDestination.objects.get(internal_id=destination_id, confio_account=owner)
            bridge = (PaymentBridgeTransfer.objects.select_related('quote__funding_instruction').get(
                internal_id=bridge_id, quote__confio_account=owner) if bridge_id else None)
            quote = local_money.payout_quote(owner, destination, amount=amount, bridge=bridge)
        except (PayoutDestination.DoesNotExist, PaymentBridgeTransfer.DoesNotExist):
            raise GraphQLError('Destino no encontrado')
        except Exception as exc:
            raise _query_error(exc)
        return LocalPayoutQuoteType(**{key: str(value) for key, value in quote.items()})

    def resolve_local_deposit_quote(self, info, credit_id):
        owner = _owner(info, 'send_funds', owner_only=True)
        try:
            credit = LedgerEntry.objects.select_related('financial_account__provider_profile').get(
                internal_id=credit_id, financial_account__provider_profile__confio_account=owner)
            quote = local_money.deposit_quote(owner, credit)
        except LedgerEntry.DoesNotExist:
            raise GraphQLError('Depósito no encontrado')
        except Exception as exc:
            raise _query_error(exc)
        return LocalDepositQuoteType(**{key: str(value) for key, value in quote.items()})

    def resolve_limit_increase_request(self, info):
        owner = _owner(info, 'manage_bank_accounts', owner_only=True)
        row = LimitIncreaseRequest.objects.filter(confio_account=owner).order_by('-created_at').first()
        return _request(row) if row else None

    def resolve_limit_increase_requirements(self, info, income_type):
        owner = _owner(info, 'manage_bank_accounts', owner_only=True)
        try:
            rows = local_money.edd_requirements(owner, income_type)
        except PaymentAccountError as exc:
            raise _query_error(exc)
        return [EddRequirementType(kind=kind, title=title, detail=detail) for kind, title, detail in rows]


class ActivateLocalMoney(graphene.Mutation):
    class Arguments:
        method_id = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    status = graphene.String()

    @classmethod
    def mutate(cls, root, info, method_id):
        from .schema import _public_error
        try:
            owner = _owner(info, 'manage_bank_accounts', owner_only=True)
            # A passport-only person has no primary document; the rail picks
            # the verified document this country accepts.
            from .models import AccountActivation
            from .activation import reconcile
            method = local_money.get_method(method_id)
            from . import breb_location
            breb_location.require_for_country(owner, method.country, info.context.META)
            row = AccountActivation.objects.filter(confio_account=owner, country=method.country, asset=method.asset).first()
            if row is None:
                raise PaymentAccountError('Confirma el costo de apertura antes de solicitar la cuenta.')
            if row.status == 'legacy':
                status = local_money.activate(owner, _identity(owner, required=False), method_id)
            else:
                row = reconcile(row.pk)
                status = row.status
                if status == 'payment_pending':
                    status = 'provisioning'
            return cls(success=True, errors=[], status=status)
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)], status=None)


class ResolveLocalDestination(graphene.Mutation):
    class Arguments:
        method_id = graphene.String(required=True)
        value = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    destination = graphene.Field(LocalDestinationType)

    @classmethod
    def mutate(cls, root, info, method_id, value):
        from .schema import _public_error
        try:
            owner = _owner(info, 'send_funds', owner_only=True)
            method = local_money.get_method(method_id, 'send')
            local_money.require_rail(owner, _identity(owner, required=False), method)
            from . import breb_location
            breb_location.require_for_country(owner, method.country, info.context.META)
            row = local_money.resolve_destination(owner, method_id, value)
            return cls(success=True, errors=[], destination=_destination(row))
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)], destination=None)


class RecheckLocalDestination(graphene.Mutation):
    """A saved recipient, checked again when its holder check is old."""

    class Arguments:
        id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    destination = graphene.Field(LocalDestinationType)

    @classmethod
    def mutate(cls, root, info, id):
        from .schema import _public_error
        try:
            owner = _owner(info, 'send_funds', owner_only=True)
            row = PayoutDestination.objects.filter(internal_id=id, confio_account=owner, provider='infinia').first()
            if row is None:
                raise PaymentAccountError('Destino no encontrado')
            method = local_money.METHODS.get((row.provider_data or {}).get('method_id'))
            if method is not None:
                local_money.require_rail(owner, _identity(owner, required=False), method)
            from . import breb_location
            breb_location.require_for_country(owner, row.country, info.context.META)
            return cls(success=True, errors=[], destination=_destination(local_money.recheck_destination(row)))
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)], destination=None)


class StartLimitIncreaseVerification(graphene.Mutation):
    """Record the EDD answers and open (or resume) the Didit EDD session."""

    class Arguments:
        income_type = graphene.String(required=True)
        occupation = graphene.String(required=True)
        expected_monthly_usd = graphene.Decimal(required=True)
        source_of_funds = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    session_id = graphene.String()
    session_token = graphene.String()
    request = graphene.Field(LimitIncreaseRequestType)

    @classmethod
    def mutate(cls, root, info, income_type, occupation, expected_monthly_usd, source_of_funds):
        from .schema import _public_error
        from . import edd
        from security.didit import build_didit_callback_url
        try:
            owner = _owner(info, 'manage_bank_accounts', owner_only=True)
            row, session = edd.start(
                owner, income_type=income_type, occupation=occupation,
                expected_monthly_usd=expected_monthly_usd, source_of_funds=source_of_funds,
                callback_url=build_didit_callback_url(info.context))
            return cls(success=True, errors=[], session_id=session['session_id'],
                       session_token=session['session_token'], request=_request(row))
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)], session_id=None, session_token=None, request=None)


class SyncLimitIncreaseVerification(graphene.Mutation):
    class Arguments:
        session_id = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    request = graphene.Field(LimitIncreaseRequestType)

    @classmethod
    def mutate(cls, root, info, session_id):
        from .schema import _public_error
        from . import edd
        try:
            owner = _owner(info, 'manage_bank_accounts', owner_only=True)
            if not LimitIncreaseRequest.objects.filter(confio_account=owner, didit_session_id=session_id).exists():
                raise PaymentAccountError('Solicitud no encontrada')
            row = edd.sync_edd_session(session_id, expected_user=owner.user)
            return cls(success=True, errors=[], request=_request(row))
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)], request=None)



class PrepareLocalActivation(graphene.Mutation):
    class Arguments:
        method_id = graphene.String(required=True)
        accepted_fee = graphene.Decimal()

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    status = graphene.String()
    amount = graphene.String()
    payment = graphene.Field(PrepareBscSend)

    @classmethod
    def mutate(cls, root, info, method_id, accepted_fee=None):
        from . import activation
        from .schema import _public_error
        from send.schema import PrepareBscSend, BscSendCallType
        from users.jwt_context import get_jwt_business_context_with_validation
        try:
            owner = _owner(info, 'manage_bank_accounts', owner_only=True)
            from . import breb_location
            breb_location.require_for_country(owner, local_money.get_method(method_id).country, info.context.META)
            ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not ctx:
                raise PaymentAccountError('No autorizado')
            row, payment = activation.prepare(owner, _identity(owner, required=False), method_id, ctx, accepted_fee=accepted_fee)
            if payment:
                payment['calls'] = [BscSendCallType(to=c['to'], value_wei=c['value'], data=c['data'])
                                    for c in payment['calls']]
            return cls(success=True, errors=[], status=row.status, amount=str(row.amount),
                       payment=PrepareBscSend(**payment) if payment else None)
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)])


class LocalMoneyMutation(graphene.ObjectType):
    prepare_local_activation = PrepareLocalActivation.Field()
    activate_local_money = ActivateLocalMoney.Field()
    resolve_local_destination = ResolveLocalDestination.Field()
    recheck_local_destination = RecheckLocalDestination.Field()
    start_limit_increase_verification = StartLimitIncreaseVerification.Field()
    sync_limit_increase_verification = SyncLimitIncreaseVerification.Field()
