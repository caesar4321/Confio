import base64
import logging
import json
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, time
import msgpack

import graphene
from graphene_django import DjangoObjectType
from django.db import transaction as db_transaction
from django.conf import settings
from django.utils import timezone
from algosdk import transaction
from algosdk.v2client import algod
from algosdk import encoding as algo_encoding
from algosdk import logic as algo_logic
from blockchain.algorand_client import AlgorandClient

from security.utils import graphql_require_kyc, graphql_require_aml
from security.utils import check_kyc_required, perform_aml_check
from send.validators import validate_transaction_amount
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account, Business
from .models import PayrollRun, PayrollItem, PayrollRecipient
from blockchain.payroll_transaction_builder import PayrollTransactionBuilder


logger = logging.getLogger(__name__)

DECIMAL_QUANT = Decimal('0.000001')  # 6 decimals for ASA amounts


def _payroll_business_account(info, user):
    """The business Account a payroll READ is about, or None.

    Owners and active delegates both reach payroll screens, and a delegate
    viewing from their PERSONAL account has no business JWT context — hence
    the fallbacks. Reads only: every mutation still goes through
    get_jwt_business_context_with_validation with its own permission.
    """
    biz_id = None
    account_index = None
    ctx = get_jwt_business_context_with_validation(info, required_permission=None)
    if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
        emp_rec = ctx.get('employee_record')
        if emp_rec and not emp_rec.is_active:
            return None
        biz_id = ctx['business_id']
        # The write path (_business_context) pins the account by JWT
        # account_index. Reading the lowest-index account instead meant a
        # multi-account business could be shown one account's escrow while
        # the buttons funded another's.
        account_index = ctx.get('account_index', 0)
    if not biz_id:
        owned = Account.objects.filter(
            user=user, account_type='business', deleted_at__isnull=True
        ).order_by('account_index').first()
        if owned and owned.business_id:
            biz_id = owned.business_id
    if not biz_id:
        try:
            from users.models_employee import BusinessEmployee
            emp = BusinessEmployee.objects.filter(
                user=user, is_active=True, deleted_at__isnull=True
            ).order_by('business_id').first()
            if emp:
                biz_id = emp.business_id
        except Exception:  # noqa: BLE001
            biz_id = None
    if not biz_id:
        return None
    qs = Account.objects.filter(
        business_id=biz_id, account_type='business', deleted_at__isnull=True)
    if account_index is not None:
        pinned = qs.filter(account_index=account_index).first()
        if pinned:
            return pinned
    return qs.order_by('account_index').first()


def _caller_signer_address(user):
    """The acting user's own personal EVM address — the key ConfioPayrollVault
    checks when they sign a payout."""
    acct = Account.objects.filter(
        user=user, account_type='personal', account_index=0,
        deleted_at__isnull=True).first()
    return ((getattr(acct, 'bsc_address', None) or '') or '').lower() or None


def _delegate_candidates(business_account):
    """(employee_id, evm_address) for every active employee who could
    plausibly be allowlisted on this business's vault.

    The contract's allowlist is a mapping with no enumerator, so the answer
    to "who are my delegates" is this set intersected with the chain. Callers
    that also care about the business EOA prepend it themselves."""
    from users.models_employee import BusinessEmployee

    pairs = []
    employees = BusinessEmployee.objects.filter(
        business_id=business_account.business_id, is_active=True,
        deleted_at__isnull=True).select_related('user')
    user_ids = [e.user_id for e in employees]
    personal = {
        a.user_id: a for a in Account.objects.filter(
            user_id__in=user_ids, account_type='personal', account_index=0,
            deleted_at__isnull=True)
    }
    for emp in employees:
        acct = personal.get(emp.user_id)
        addr = (getattr(acct, 'bsc_address', None) or '').lower()
        if addr:
            pairs.append((str(emp.id), addr))
    return pairs


def _algorand_delegate_employee_ids(business_account, delegate_addrs_upper):
    """Legacy-rail counterpart of _delegate_candidates: which employees own
    one of the Algorand addresses in the allowlist boxes."""
    from users.models_employee import BusinessEmployee

    employees = list(BusinessEmployee.objects.filter(
        business_id=business_account.business_id, is_active=True,
        deleted_at__isnull=True))
    personal = {
        a.user_id: a for a in Account.objects.filter(
            user_id__in=[e.user_id for e in employees], account_type='personal',
            account_index=0, deleted_at__isnull=True)
    }
    out = []
    for emp in employees:
        acct = personal.get(emp.user_id)
        addr = (getattr(acct, 'algorand_address', None) or '').strip().upper()
        if addr and addr in delegate_addrs_upper:
            out.append(str(emp.id))
    return out


class PayrollItemType(DjangoObjectType):
    class Meta:
        model = PayrollItem
        fields = (
            'id',
            'internal_id',
            'run',
            'recipient_user',
            'recipient_account',
            'token_type',
            'net_amount',
            # What actually LANDED. A payout to an Ondo-ineligible employee
            # redeems shares to USDT with a slippage floor, so it can settle
            # below the nominal wage — a receipt that prints net_amount for
            # one of those is stating a number that never arrived.
            'settled_amount',
            'gross_amount',
            'fee_amount',
            'status',
            'transaction_hash',
            'blockchain_data',
            'executed_by_user',
            'executed_at',
            'created_at',
            'updated_at',
        )

class PayrollRecipientType(DjangoObjectType):
    class Meta:
        model = PayrollRecipient
        fields = (
            'id',
            'business',
            'recipient_user',
            'recipient_account',
            'display_name',
            'created_at',
            'updated_at',
        )

    is_employee = graphene.Boolean()
    employee_role = graphene.String()
    employee_effective_permissions = graphene.JSONString()

    def resolve_is_employee(self, info):
        from users.models_employee import BusinessEmployee
        return BusinessEmployee.objects.filter(
            business_id=self.business_id,
            user_id=self.recipient_user_id,
            deleted_at__isnull=True,
            is_active=True
        ).exists()

    def resolve_employee_role(self, info):
        from users.models_employee import BusinessEmployee
        emp = BusinessEmployee.objects.filter(
            business_id=self.business_id,
            user_id=self.recipient_user_id,
            deleted_at__isnull=True,
            is_active=True
        ).first()
        return emp.role if emp else None

    def resolve_employee_effective_permissions(self, info):
        from users.models_employee import BusinessEmployee
        emp = BusinessEmployee.objects.filter(
            business_id=self.business_id,
            user_id=self.recipient_user_id,
            deleted_at__isnull=True,
            is_active=True
        ).first()
        return emp.get_effective_permissions() if emp else None


class CreatePayrollRecipient(graphene.Mutation):
    class Arguments:
        recipient_user_id = graphene.ID(required=True)
        recipient_account_id = graphene.ID(required=True)
        display_name = graphene.String()
        mark_owner = graphene.Boolean(
            required=False,
            description="If true and the user is owner, mark as owner recipient"
        )

    recipient = graphene.Field(PayrollRecipientType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, recipient_user_id, recipient_account_id, display_name=None, mark_owner=False):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreatePayrollRecipient(recipient=None, success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return CreatePayrollRecipient(recipient=None, success=False, errors=["Business context required"])

        from users.models import Account, User

        try:
            recipient_user = User.objects.get(id=recipient_user_id)
            recipient_account = Account.objects.get(id=recipient_account_id, deleted_at__isnull=True)
        except User.DoesNotExist:
            return CreatePayrollRecipient(recipient=None, success=False, errors=["Recipient user not found"])
        except Account.DoesNotExist:
            return CreatePayrollRecipient(recipient=None, success=False, errors=["Recipient account not found"])

        # Basic sanity: account belongs to user
        if recipient_account.user_id != recipient_user.id:
            return CreatePayrollRecipient(recipient=None, success=False, errors=["Account does not belong to user"])

        try:
            recipient, created = PayrollRecipient.objects.get_or_create(
                business_id=ctx['business_id'],
                recipient_user=recipient_user,
                recipient_account=recipient_account,
                defaults={'display_name': display_name or ''}
            )
            if not created and display_name is not None:
                recipient.display_name = display_name
                recipient.save(update_fields=['display_name', 'updated_at'])

            return CreatePayrollRecipient(recipient=recipient, success=True, errors=None)
        except Exception as e:
            return CreatePayrollRecipient(recipient=None, success=False, errors=[str(e)])


class DeletePayrollRecipient(graphene.Mutation):
    class Arguments:
        recipient_id = graphene.ID(required=True)

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, recipient_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return DeletePayrollRecipient(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return DeletePayrollRecipient(success=False, errors=["Business context required"])

        try:
            recipient = PayrollRecipient.objects.get(id=recipient_id, business_id=ctx['business_id'], deleted_at__isnull=True)
            recipient.soft_delete()
            return DeletePayrollRecipient(success=True, errors=None)
        except PayrollRecipient.DoesNotExist:
            return DeletePayrollRecipient(success=False, errors=["Recipient not found"])
        except Exception as e:
            return DeletePayrollRecipient(success=False, errors=[str(e)])


class PayrollRunType(DjangoObjectType):
    items = graphene.List(PayrollItemType)

    class Meta:
        model = PayrollRun
        fields = (
            'id',
            'run_id',
            'business',
            'created_by_user',
            'token_type',
            'period_seconds',
            'cap_amount',
            'gross_total',
            'net_total',
            'fee_total',
            'status',
            'scheduled_at',
            'created_at',
            'updated_at',
        )

    def resolve_items(self, info):
        return self.items.all()


class PayrollItemInput(graphene.InputObjectType):
    recipient_account_id = graphene.ID(required=True, description="Confío account ID that will receive payroll")
    net_amount = graphene.String(required=True, description="Net amount to deliver (decimal string)")


class CreatePayrollRun(graphene.Mutation):
    class Arguments:
        token_type = graphene.String(
            required=False, default_value=None,
            description="DEPRECATED — the rail decides the token; a mismatched value is ignored")
        period_seconds = graphene.Int(required=False)
        cap_amount = graphene.String(required=False, description="Optional gross cap per window")
        scheduled_at = graphene.String(required=False, description="ISO datetime or YYYY-MM-DD for scheduling")
        items = graphene.List(PayrollItemInput, required=True)

    run = graphene.Field(PayrollRunType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, items, token_type=None, period_seconds=None, cap_amount=None, scheduled_at=None):
        # Firebase App Check
        from security.integrity_service import app_check_service
        ac_result = app_check_service.verify_request_header(info.context, action='payroll', should_enforce=True)
        if not ac_result.get('success', True):
            return CreatePayrollRun(run=None, success=False, errors=["Actualiza la aplicación a la última versión o usa la app oficial para continuar."])

        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreatePayrollRun(run=None, success=False, errors=["Authentication required"])

        if not items:
            return CreatePayrollRun(run=None, success=False, errors=["At least one payroll item is required"])

        # Business context with send_funds permission
        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return CreatePayrollRun(run=None, success=False, errors=["Business context with send_funds permission required"])

        business_id = ctx['business_id']
        try:
            business = Business.objects.get(id=business_id)
        except Business.DoesNotExist:
            return CreatePayrollRun(run=None, success=False, errors=["Business not found"])

        # The token is a property of the RAIL, not a client choice: payroll
        # settles from one escrow and that escrow holds one token. The client
        # used to hardcode 'cUSD', which is how a business on the cUSD+ vault
        # ended up with runs labelled in the token being phased out. Whatever
        # arrives is checked against the rail and otherwise ignored.
        # Pinned by JWT account_index, exactly like _business_context does at
        # payout time. Reading the lowest-index account instead let a
        # multi-account business stamp a run from one account's rail and then
        # execute it against another's — where the new rail guards strand it.
        business_account = Account.objects.filter(
            business_id=business_id, account_type='business',
            account_index=ctx.get('account_index', 0),
            deleted_at__isnull=True).first() or Account.objects.filter(
            business_id=business_id, account_type='business',
            deleted_at__isnull=True).order_by('account_index').first()
        from . import bsc_flow
        # The rail no longer determines the token by itself: on BSC the run
        # is denominated in the pool this employer can actually park into
        # (cUSD+ when Ondo-eligible, otherwise universal cUSD). PINNED here, at
        # creation — a run must keep paying out of the escrow it was funded
        # into even if the employer's eligibility changes mid-run.
        normalized_token = bsc_flow.rail_token(
            bsc_flow.execution_rail(business_account), business_account, user)
        if token_type and str(token_type).upper() != normalized_token:
            logger.info(
                '[PAYROLL] client asked for %s; this business pays in %s — '
                'using the rail token', token_type, normalized_token)
        # Model choices do not constrain writes, so an unrecognised token
        # used to travel all the way to the ledger — where it is now a
        # constraint violation that the unified signal swallows, leaving a
        # real payroll run with no ledger row at all. Refuse it at the door.
        _allowed = {c[0] for c in PayrollRun.TOKEN_TYPES}
        if normalized_token not in _allowed:
            return cls(success=False, errors=[
                f"token_type inválido: {normalized_token}. "
                f"Debe ser uno de: {', '.join(sorted(_allowed))}"], run=None)

        # Validate cap if provided
        if cap_amount:
            validate_transaction_amount(cap_amount)

        builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)

        scheduled_dt = None
        if scheduled_at:
            try:
                normalized = str(scheduled_at).replace('Z', '+00:00')
                scheduled_dt = datetime.fromisoformat(normalized)
            except ValueError:
                try:
                    date_only = datetime.strptime(str(scheduled_at), '%Y-%m-%d')
                    scheduled_dt = datetime.combine(date_only.date(), time.min)
                except Exception:
                    return CreatePayrollRun(run=None, success=False, errors=["Invalid scheduled_at format; use ISO 8601 or YYYY-MM-DD"])
            if timezone.is_naive(scheduled_dt):
                scheduled_dt = timezone.make_aware(scheduled_dt)
            scheduled_dt = scheduled_dt.astimezone(timezone.get_current_timezone())

            # Prevent scheduling in the past (date must be today or later)
            now = timezone.now()
            if scheduled_dt < now.replace(hour=0, minute=0, second=0, microsecond=0):
                return CreatePayrollRun(run=None, success=False, errors=["scheduled_at no puede ser anterior a hoy"])

        try:
            with db_transaction.atomic():
                run = PayrollRun.objects.create(
                    business=business,
                    created_by_user=user,
                    token_type=normalized_token,
                    period_seconds=period_seconds,
                    cap_amount=Decimal(cap_amount) if cap_amount else None,
                    status='READY',
                    scheduled_at=scheduled_dt,
                )

                gross_total = Decimal('0')
                net_total = Decimal('0')
                fee_total = Decimal('0')

                for item_input in items:
                    validate_transaction_amount(item_input.net_amount)
                    account = Account.objects.filter(id=item_input.recipient_account_id, deleted_at__isnull=True).select_related('user').first()
                    if not account:
                        raise ValueError("Recipient account invalid")
                    # A recipient needs an address on SOME rail, not on
                    # Algorand specifically. Requiring algorand_address here
                    # made BSC payroll unusable for exactly the people being
                    # onboarded now: with ALGORAND_ONBOARDING_ENABLED=False a
                    # new employee never gets an Algorand address, so a run
                    # that would have paid them entirely over BSC was refused
                    # before it could be prepared.
                    if not (account.algorand_address or account.bsc_address):
                        raise ValueError(
                            "Recipient account has no wallet address on any network")

                    # Only Confío users (accounts stored in DB) are allowed
                    recipient_user = account.user

                    net_dec = Decimal(str(item_input.net_amount)).quantize(DECIMAL_QUANT, rounding=ROUND_DOWN)
                    net_base = int((net_dec * Decimal(1_000_000)))

                    amounts = builder.calculate_amounts_for_net(net_base)
                    gross_dec = Decimal(amounts['gross_amount']) / Decimal(1_000_000)
                    fee_dec = Decimal(amounts['fee_amount']) / Decimal(1_000_000)

                    PayrollItem.objects.create(
                        run=run,
                        recipient_user=recipient_user,
                        recipient_account=account,
                        token_type=normalized_token,
                        net_amount=net_dec,
                        gross_amount=gross_dec,
                        fee_amount=fee_dec,
                        status='PENDING',
                    )

                    gross_total += gross_dec
                    net_total += net_dec
                    fee_total += fee_dec

                run.gross_total = gross_total
                run.net_total = net_total
                run.fee_total = fee_total
                run.save(update_fields=['gross_total', 'net_total', 'fee_total', 'updated_at'])

                return CreatePayrollRun(run=run, success=True, errors=None)

        except Exception as e:
            return CreatePayrollRun(run=None, success=False, errors=[str(e)])


class PreparePayrollItemPayout(graphene.Mutation):
    class Arguments:
        payroll_item_id = graphene.String(required=True, description="Payroll internal_id to prepare payout for")
        note = graphene.String(required=False)

    item = graphene.Field(PayrollItemType)
    run = graphene.Field(PayrollRunType)
    transactions = graphene.JSONString(description="Unsigned transactions for delegate to sign")
    unsigned_transaction_b64 = graphene.String(description="Base64-encoded unsigned transaction for direct signing")
    sponsor_transaction = graphene.String(description="Base64-encoded signed sponsor transaction")
    gross_amount = graphene.Float()
    net_amount = graphene.Float()
    fee_amount = graphene.Float()
    group_id = graphene.String()
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    logger = logging.getLogger(__name__)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, payroll_item_id, note=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        # Track businesses the user can operate on (owner/admin via context, or delegate)
        allowed_business_ids = set()
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            allowed_business_ids.add(ctx['business_id'])

        from users.models_employee import BusinessEmployee
        delegate_biz_ids = BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).values_list('business_id', flat=True)
        allowed_business_ids.update(delegate_biz_ids)

        if not allowed_business_ids:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Business context with send_funds permission required"])

        try:
            item = PayrollItem.objects.select_related('run', 'recipient_account', 'recipient_user').get(internal_id=payroll_item_id, deleted_at__isnull=True)
        except PayrollItem.DoesNotExist:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Payroll item not found"])

        # Ensure item belongs to a business the user can operate on
        if item.run.business_id not in allowed_business_ids:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["No access to this payroll item"])

        # A run is denominated in the token of the escrow it will be paid
        # FROM, so the run pins its rail — the live flag does not. Without
        # this, flipping BSC_PAYROLL_ENABLED off between creation and payout
        # let a cUSD+ run fall through to here and be paid out of the
        # Algorand vault: a different pot of money than the run describes.
        if item.run.token_type in ('CUSD_PLUS', 'CUSD_BSC', 'USDT'):
            return PreparePayrollItemPayout(
                item=None, run=None, success=False,
                errors=["Esta nómina se paga desde la bóveda en BNB Chain, "
                        "no desde la bóveda de cUSD."])

        # Check delegate permission if employee
        employee_record = ctx.get('employee_record')
        if employee_record and not employee_record.has_permission('send_funds'):
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["No permission to send funds"])

        if not item.recipient_account.algorand_address:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Recipient missing Algorand address"])

        # Determine delegate account (active account from JWT)
        delegate_account = None
        from users.models import Account  # local import to avoid circulars
        if ctx['account_type'] == 'business' and ctx.get('business_id'):
            delegate_account = Account.objects.filter(
                business_id=ctx['business_id'],
                account_type='business',
                deleted_at__isnull=True
            ).order_by('account_index').first()
        else:
            delegate_account = Account.objects.filter(
                user=user,
                account_type=ctx.get('account_type'),
                account_index=ctx.get('account_index'),
                deleted_at__isnull=True
            ).first()

        if not delegate_account or not delegate_account.algorand_address:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Delegate account not found or missing Algorand address"])

        # Business account ALWAYS comes from the payroll run's business, not the delegate's business
        # This ensures the allowlist check is for business||delegate, not delegate||delegate
        business_account = Account.objects.filter(
            business_id=item.run.business_id,
            account_type='business',
            deleted_at__isnull=True
        ).order_by('account_index').first()
        if not business_account or not business_account.algorand_address:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Business account not found or missing Algorand address"])
        try:
            cls.logger.info(
                "[Payroll] prepare_payout addresses delegate=%s business=%s item=%s run_biz=%s",
                delegate_account.algorand_address,
                business_account.algorand_address,
                payroll_item_id,
                getattr(item.run, 'business_id', None),
            )
        except Exception:
            pass

        # Ensure delegate is allowlisted for this business in the payroll app (owners included)
        try:
            algod_client = algod.AlgodClient(
                settings.ALGORAND_ALGOD_TOKEN,
                settings.ALGORAND_ALGOD_ADDRESS,
                headers={"User-Agent": "py-algorand-sdk"}
            )
            allow_key = (
                algo_encoding.decode_address(business_account.algorand_address) +
                algo_encoding.decode_address(delegate_account.algorand_address)
            )
            algod_client.application_box_by_name(settings.ALGORAND_PAYROLL_APP_ID, allow_key)
        except Exception:
            return PreparePayrollItemPayout(
                item=None,
                run=None,
                success=False,
                errors=[
                    "No estás autorizado para pagar esta nómina. Activa nómina y agrega este delegado en Configuración.",
                    f"Falta allowlist para {delegate_account.algorand_address} en negocio {business_account.algorand_address}"
                ],
            )

        # Convert amounts back to base units for builder
        net_base = int((Decimal(item.net_amount).quantize(DECIMAL_QUANT, rounding=ROUND_DOWN)) * Decimal(1_000_000))
        builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)
        amounts = builder.calculate_amounts_for_net(net_base)

        # Preflight: ensure vault balance is sufficient before building txn
        try:
            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
            vault_key = b"VAULT" + algo_encoding.decode_address(business_account.algorand_address)
            vault_box = algod_client.application_box_by_name(settings.ALGORAND_PAYROLL_APP_ID, vault_key)
            data = base64.b64decode(vault_box.get('value', '')) if vault_box else b''
            vault_amount = int.from_bytes(data[:8], 'big') if len(data) >= 8 else 0
            try:
                cls.logger.info("[Payroll] vault check biz=%s vault=%s gross=%s net=%s fee=%s", business_account.algorand_address, vault_amount, amounts['gross_amount'], amounts['net_amount'], amounts['fee_amount'])
            except Exception:
                pass
            if vault_amount <= 0:
                return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["La bóveda de nómina no está fondeada. Agrega fondos desde el negocio."])
            if vault_amount < amounts['gross_amount']:
                return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Saldo insuficiente en la bóveda de nómina."])
        except Exception:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["No se pudo leer la bóveda de nómina. Intenta fondearla nuevamente desde el negocio."])

        try:
            def _convert_bytes(obj):
                if isinstance(obj, (bytes, bytearray)):
                    return base64.b64encode(obj).decode()
                if isinstance(obj, list):
                    return [_convert_bytes(x) for x in obj]
                if isinstance(obj, dict):
                    return {k: _convert_bytes(v) for k, v in obj.items()}
                return obj

            try:
                cls.logger.info("[Payroll] prepare_payout building txn: delegate=%s business=%s recipient=%s", delegate_account.algorand_address, business_account.algorand_address, item.recipient_account.algorand_address)
            except Exception:
                pass

            txn = builder.build_payout_app_call(
                delegate_address=delegate_account.algorand_address,
                business_address=business_account.algorand_address,
                recipient_address=item.recipient_account.algorand_address,
                net_amount=net_base,
                payroll_item_id=item.internal_id,
                note=note.encode() if note else None,
            )
            # Use sponsored execution so delegate pays 0 fees
            from blockchain.algorand_sponsor_service import algorand_sponsor_service
            import asyncio
            
            # We need to run async method in sync context
            # In Django channels/graphene, we might be in async or sync. 
            # Assuming sync for now, using async_to_sync or just asyncio.run if safe?
            # Ideally we should await if we are in async context.
            # But graphene mutations are often sync.
            
            # Let's try to run it.
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            sponsor_result = loop.run_until_complete(
                algorand_sponsor_service.create_sponsored_execution(txn)
            )
            
            if not sponsor_result['success']:
                return PreparePayrollItemPayout(item=item, run=item.run, success=False, errors=[f"Sponsorship failed: {sponsor_result.get('error')}"])

            txn_clean = sponsor_result['user_transaction'] # This is b64 encoded unsigned txn
            sponsor_txn = sponsor_result['sponsor_transaction'] # This is b64 encoded signed txn
            group_id = sponsor_result['group_id']

            item.blockchain_data = {
                'transactions': [txn_clean], # Store user txn
                'sponsor_transaction': sponsor_txn,
                'group_id': group_id,
                'gross_amount': float(amounts['gross_amount']) / 1_000_000,
                'net_amount': float(amounts['net_amount']) / 1_000_000,
                'fee_amount': float(amounts['fee_amount']) / 1_000_000,
            }
            item.status = 'PREPARED'
            item.save(update_fields=['blockchain_data', 'status', 'updated_at'])

            return PreparePayrollItemPayout(
                item=item,
                run=item.run,
                transactions=json.dumps([txn_clean]), # Legacy field, maybe not used?
                unsigned_transaction_b64=txn_clean,
                sponsor_transaction=sponsor_txn,
                gross_amount=amounts['gross_amount'] / 1_000_000,
                net_amount=amounts['net_amount'] / 1_000_000,
                fee_amount=amounts['fee_amount'] / 1_000_000,
                group_id=group_id,
                success=True,
                errors=None
            )
        except Exception as e:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=[str(e)])


class SubmitPayrollItemPayout(graphene.Mutation):
    class Arguments:
        payroll_item_id = graphene.String(required=True, description="Payroll internal_id to submit payout for")
        signed_transaction = graphene.String(required=True, description="Base64-encoded signed AppCall transaction")
        sponsor_signature = graphene.String(required=False, description="Base64-encoded signed sponsor transaction")

    item = graphene.Field(PayrollItemType)
    run = graphene.Field(PayrollRunType)
    transaction_hash = graphene.String()
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    logger = logging.getLogger(__name__)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, payroll_item_id, signed_transaction, sponsor_signature=None):
        # Firebase App Check
        from security.integrity_service import app_check_service
        ac_result = app_check_service.verify_request_header(info.context, action='payroll', should_enforce=True)
        if not ac_result.get('success', True):
            return SubmitPayrollItemPayout(item=None, run=None, success=False, errors=["Actualiza la aplicación a la última versión o usa la app oficial para continuar."])

        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SubmitPayrollItemPayout(item=None, run=None, success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        allowed_business_ids = set()
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            allowed_business_ids.add(ctx['business_id'])

        from users.models_employee import BusinessEmployee
        delegate_biz_ids = BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).values_list('business_id', flat=True)
        allowed_business_ids.update(delegate_biz_ids)

        if not allowed_business_ids:
            return SubmitPayrollItemPayout(item=None, run=None, success=False, errors=["Business context with send_funds permission required"])
        try:
            cls.logger.info("[Payroll] submit_payout start user=%s item=%s ctx=%s", getattr(user, 'id', None), payroll_item_id, ctx)
        except Exception:
            pass

        try:
            item = PayrollItem.objects.select_related('run').get(internal_id=payroll_item_id, deleted_at__isnull=True)
        except PayrollItem.DoesNotExist:
            return SubmitPayrollItemPayout(item=None, run=None, success=False, errors=["Payroll item not found"])

        # Ensure item belongs to the same business
        if item.run.business_id not in allowed_business_ids:
            return SubmitPayrollItemPayout(item=None, run=None, success=False, errors=["No access to this payroll item"])

        # Only allow submission from prepared or previously failed
        if item.status not in ['PREPARED', 'FAILED', 'PENDING']:
            return SubmitPayrollItemPayout(item=item, run=item.run, success=False, errors=[f"Item in status {item.status} cannot be submitted"])

        try:
            # Normalize base64 (handle missing padding and url-safe variants)
            stx_str = str(signed_transaction or "").strip()
            stx_str = stx_str.replace('-', '+').replace('_', '/')
            if len(stx_str) % 4 != 0:
                stx_str = stx_str + ('=' * ((4 - (len(stx_str) % 4)) % 4))
            stx_bytes = base64.b64decode(stx_str)
        except Exception:
            return SubmitPayrollItemPayout(item=item, run=item.run, success=False, errors=["Invalid base64 transaction"])

        try:
            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
            
            if sponsor_signature:
                # Use sponsored submission
                from blockchain.algorand_sponsor_service import algorand_sponsor_service
                import asyncio
                
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                submit_result = loop.run_until_complete(
                    algorand_sponsor_service.submit_sponsored_group(
                        signed_user_txn=signed_transaction,
                        signed_sponsor_txn=sponsor_signature
                    )
                )
                
                if not submit_result['success']:
                    return SubmitPayrollItemPayout(item=item, run=item.run, success=False, errors=[f"Sponsored submission failed: {submit_result.get('error')}"])
                
                tx_hash = submit_result['tx_id']
            else:
                # Legacy direct submission
                try:
                    print(f"[Payroll] Submitting signed txn len={len(stx_bytes)} first8={list(stx_bytes[:8])}")
                except Exception:
                    pass
                try:
                    # Decode for debug: accounts and boxes to ensure ordering/values
                    txn_dict = msgpack.unpackb(stx_bytes, raw=False)
                    core_txn = txn_dict.get('txn', txn_dict)
                    accts = core_txn.get('apat', [])
                    boxes = core_txn.get('apbx', [])
                    cls.logger.info(
                        "[Payroll] submit_payout debug accounts=%s boxes=%s sender=%s",
                        [algo_encoding.encode_address(a) for a in accts],
                        [b.get('n').hex() if isinstance(b, dict) and 'n' in b else None for b in boxes],
                        algo_encoding.encode_address(core_txn.get('snd')) if core_txn.get('snd') else None,
                    )
                except Exception:
                    pass
                stx_b64 = base64.b64encode(stx_bytes).decode('utf-8')
                send_result = algod_client.send_raw_transaction(stx_b64)
                tx_hash = send_result if isinstance(send_result, str) else send_result.get('txId') if isinstance(send_result, dict) else None
        except Exception as e:
            msg = str(e)
            
            # Already in pool recovery logic
            if "already in pool" in msg.lower():
                import re
                txid_match = re.search(r'([A-Z2-7]{52})', msg)
                if txid_match:
                    recovered_txid = txid_match.group(1)
                    cls.logger.info("[Payroll] Duplicate submission detected for item=%s. Recovered TxID: %s", payroll_item_id, recovered_txid)
                    tx_hash = recovered_txid
                else:
                    # If we can't find hash in error, try to derive it from stx_bytes
                    try:
                        txn_dict = msgpack.unpackb(stx_bytes, raw=False)
                        tx_hash = algo_encoding.encode_txid(txn_dict.get('txn', txn_dict))
                        cls.logger.info("[Payroll] Duplicate submission (no hash in err), derived TxID: %s", tx_hash)
                    except Exception:
                        tx_hash = None
                
                if tx_hash:
                    # Proceed to update status below
                    pass
                else:
                    return SubmitPayrollItemPayout(item=item, run=item.run, success=False, errors=[f"Duplicate submission, but could not recover TxID: {msg}"])
            else:
                print(f"[Payroll] Submit payroll item failed: {msg}")
                try:
                    cls.logger.exception("[Payroll] submit_payout broadcast failed item=%s msg=%s", payroll_item_id, msg)
                except Exception:
                    pass
                friendly = None
                if "logic eval error" in msg:
                    if "delegate_check" in msg or "allowlist" in msg or "authorized" in msg:
                        friendly = "No estás autorizado para pagar esta nómina. Asegúrate de estar en la lista de delegados para este negocio."
                    elif "cap" in msg or "limit" in msg:
                        friendly = "Se superó el límite o cap de nómina. Revisa el tope configurado."
                    elif "balance" in msg or "insufficient" in msg:
                        friendly = "Saldo insuficiente en el escrow de nómina."
                    elif "opt in" in msg or "asset" in msg or "receiver" in msg:
                        friendly = "El destinatario o fee_recipient no está optado al asset de nómina."
                    else:
                        friendly = "La transacción fue rechazada por el contrato. Verifica autorización y saldo."
                detail = f"Algorand: {msg}"
                return SubmitPayrollItemPayout(item=item, run=item.run, success=False, errors=[friendly or detail, detail])

        # Derive txid if needed
        if not tx_hash:
            try:
                txn_dict = msgpack.unpackb(stx_bytes, raw=False)
                tx_hash = algo_encoding.encode_txid(txn_dict.get('txn', txn_dict))
            except Exception:
                tx_hash = None

        item.transaction_hash = tx_hash or ""
        item.status = 'SUBMITTED'
        item.executed_by_user = user
        item.executed_at = timezone.now()
        item.save(update_fields=['transaction_hash', 'status', 'executed_by_user', 'executed_at', 'updated_at'])

        # Enqueue confirmation task
        if tx_hash:
            try:
                from blockchain.tasks import confirm_payroll_item_payout
                confirm_payroll_item_payout.delay(item.internal_id, tx_hash)
            except Exception as e:
                cls.logger.warning(f"Failed to enqueue payroll confirmation task: {e}")

        return SubmitPayrollItemPayout(item=item, run=item.run, transaction_hash=tx_hash, success=True, errors=None)


class PreparePayrollVaultFunding(graphene.Mutation):
    class Arguments:
        amount = graphene.Float(required=True, description="Amount to fund in payroll token units (e.g., cUSD)")

    unsigned_transactions = graphene.List(graphene.String, description="Unsigned business AXFER transaction (single item)")
    sponsor_app_call = graphene.String(description="Signed sponsor app call transaction")
    group_id = graphene.String()
    amount = graphene.Float()
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, amount):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Business context with send_funds permission required"])

        try:
            amt_dec = Decimal(str(amount))
            if amt_dec <= 0:
                return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Amount must be greater than 0"])
            amt_dec = amt_dec.quantize(DECIMAL_QUANT, rounding=ROUND_DOWN)
            amount_base = int(amt_dec * Decimal(1_000_000))
        except Exception:
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Invalid amount"])

        if amount_base <= 0:
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Amount too small after rounding"])

        # Fetch business account for this context
        biz_acct = Account.objects.filter(
            business_id=ctx['business_id'],
            account_type='business',
            deleted_at__isnull=True
        ).order_by('account_index').first()
        if not biz_acct or not biz_acct.algorand_address:
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=["Business account not found or missing Algorand address"])

        # Use sponsored transaction service
        from blockchain.algorand_sponsor_service import create_sponsored_vault_funding
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            sponsor_result = loop.run_until_complete(
                create_sponsored_vault_funding(
                    business_address=biz_acct.algorand_address,
                    amount_base=amount_base,
                    payroll_app_id=settings.ALGORAND_PAYROLL_APP_ID,
                    payroll_asset_id=settings.BLOCKCHAIN_CONFIG["ALGORAND_PAYROLL_ASSET_ID"]
                )
            )

            if not sponsor_result['success']:
                return PreparePayrollVaultFunding(
                    unsigned_transactions=None,
                    success=False,
                    errors=[f"Sponsorship failed: {sponsor_result.get('error')}"]
                )

            # Return unsigned business transaction + signed sponsor app call
            return PreparePayrollVaultFunding(
                unsigned_transactions=[sponsor_result['user_transaction']],  # Business signs this
                sponsor_app_call=sponsor_result['sponsor_app_call'],  # Already signed
                group_id=sponsor_result['group_id'],
                amount=sponsor_result['amount'],
                success=True,
                errors=None,
            )
        except Exception as e:
            return PreparePayrollVaultFunding(unsigned_transactions=None, success=False, errors=[str(e)])


class SubmitPayrollVaultFunding(graphene.Mutation):
    class Arguments:
        signed_transactions = graphene.List(graphene.String, required=True, description="Signed business AXFER transaction (single item)")
        sponsor_app_call = graphene.String(required=False, description="Signed sponsor app call transaction")

    transaction_hash = graphene.String()
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, signed_transactions, sponsor_app_call=None):
        # Firebase App Check
        from security.integrity_service import app_check_service
        ac_result = app_check_service.verify_request_header(info.context, action='payroll', should_enforce=True)
        if not ac_result.get('success', True):
            return SubmitPayrollVaultFunding(success=False, errors=["Actualiza la aplicación a la última versión o usa la app oficial para continuar."])

        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SubmitPayrollVaultFunding(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return SubmitPayrollVaultFunding(success=False, errors=["Business context with send_funds permission required"])

        if not signed_transactions or len(signed_transactions) < 1:
            return SubmitPayrollVaultFunding(success=False, errors=["Signed business transaction required"])

        # If sponsor app call is provided, use sponsored submission (2-txn group)
        if sponsor_app_call:
            from blockchain.algorand_sponsor_service import submit_sponsored_vault_funding
            import asyncio

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            try:
                submit_result = loop.run_until_complete(
                    submit_sponsored_vault_funding(
                        signed_user_txn=signed_transactions[0],
                        signed_sponsor_app_call=sponsor_app_call
                    )
                )

                if not submit_result['success']:
                    return SubmitPayrollVaultFunding(
                        success=False,
                        errors=[f"Sponsored submission failed: {submit_result.get('error')}"]
                    )

                return SubmitPayrollVaultFunding(
                    success=True,
                    errors=None,
                    transaction_hash=submit_result['tx_id']
                )
            except Exception as e:
                msg = str(e)
                friendly = None
                if "logic eval error" in msg and ("fund" in msg or "vault" in msg or "balance" in msg):
                    friendly = "Saldo insuficiente o rechazo del contrato al fondear la bóveda. Verifica el monto y vuelve a intentar."
                return SubmitPayrollVaultFunding(success=False, errors=[friendly or f"Broadcast failed: {e}"], transaction_hash=None)

        # Legacy: if no sponsor transactions, assume all transactions are user-signed (backward compatibility)
        try:
            decoded_bytes = []
            for stx in signed_transactions:
                stx_str = str(stx or "").strip().replace('-', '+').replace('_', '/')
                if len(stx_str) % 4 != 0:
                    stx_str = stx_str + ('=' * ((4 - (len(stx_str) % 4)) % 4))
                decoded_bytes.append(base64.b64decode(stx_str))
        except Exception:
            return SubmitPayrollVaultFunding(success=False, errors=["Invalid base64 transaction"])

        try:
            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
            combined = b"".join(decoded_bytes)
            combined_b64 = base64.b64encode(combined).decode("utf-8")
            try:
                tx_id = algod_client.send_raw_transaction(combined_b64)
            except Exception as e:
                err_str = str(e)
                if "already in pool" in err_str.lower() or "already in ledger" in err_str.lower():
                    import re
                    txid_match = re.search(r'([A-Z2-7]{52})', err_str)
                    tx_id = txid_match.group(1) if txid_match else None
                    if not tx_id:
                        # Fallback for payroll vault funding
                        tx_id = "already-in-pool"
                else:
                    raise
            tx_hash = tx_id if isinstance(tx_id, str) else tx_id.get('txId') if isinstance(tx_id, dict) else None
            return SubmitPayrollVaultFunding(success=True, errors=None, transaction_hash=tx_hash)
        except Exception as e:
            msg = str(e)
            friendly = None
            if "logic eval error" in msg and ("fund" in msg or "vault" in msg or "balance" in msg):
                friendly = "Saldo insuficiente o rechazo del contrato al fondear la bóveda. Verifica el monto y vuelve a intentar."
            return SubmitPayrollVaultFunding(success=False, errors=[friendly or f"Broadcast failed: {e}"], transaction_hash=None)


class PreparePayrollVaultWithdrawal(graphene.Mutation):
    """Prepare an unsigned withdrawal from the business payroll vault (to business account_0)."""

    class Arguments:
        amount = graphene.Float(required=True, description="Amount to withdraw in payroll token units (e.g., cUSD)")

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    transaction = graphene.String(description="Unsigned withdrawal AppCall (base64 msgpack)")
    amount = graphene.Float()

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, amount):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PreparePayrollVaultWithdrawal(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return PreparePayrollVaultWithdrawal(success=False, errors=["Business context with send_funds permission required"])

        try:
            amt_dec = Decimal(str(amount))
            if amt_dec <= 0:
                return PreparePayrollVaultWithdrawal(success=False, errors=["Amount must be greater than 0"])
            amt_dec = amt_dec.quantize(DECIMAL_QUANT, rounding=ROUND_DOWN)
            amount_base = int(amt_dec * Decimal(1_000_000))
        except Exception:
            return PreparePayrollVaultWithdrawal(success=False, errors=["Invalid amount"])

        if amount_base <= 0:
            return PreparePayrollVaultWithdrawal(success=False, errors=["Amount too small after rounding"])

        biz_acct = Account.objects.filter(
            business_id=ctx['business_id'],
            account_type='business',
            deleted_at__isnull=True
        ).order_by('account_index').first()
        if not biz_acct or not biz_acct.algorand_address:
            return PreparePayrollVaultWithdrawal(success=False, errors=["Business account not found or missing Algorand address"])

        try:
            builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)
            txn = builder.build_withdrawal_app_call(
                business_account=biz_acct.algorand_address,
                amount_base=amount_base,
                recipient_address=None  # defaults to business account
            )
            unsigned_b64 = algo_encoding.msgpack_encode(txn)
            return PreparePayrollVaultWithdrawal(
                success=True,
                transaction=unsigned_b64,
                amount=float(amt_dec),
                errors=None
            )
        except Exception as e:
            try:
                logger.exception("[Payroll] prepare withdrawal build failed biz=%s amt=%s", biz_acct.algorand_address if biz_acct else None, amount)
            except Exception:
                pass
            return PreparePayrollVaultWithdrawal(success=False, errors=[str(e)])


class SubmitPayrollVaultWithdrawal(graphene.Mutation):
    """Submit a signed withdraw_vault transaction."""

    class Arguments:
        signed_transaction = graphene.String(required=True, description="Base64 signed AppCall for withdraw_vault")

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    transaction_hash = graphene.String()

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, signed_transaction):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SubmitPayrollVaultWithdrawal(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return SubmitPayrollVaultWithdrawal(success=False, errors=["Business context with send_funds permission required"])

        try:
            stx_bytes = base64.b64decode(str(signed_transaction or "").strip())
        except Exception:
            return SubmitPayrollVaultWithdrawal(success=False, errors=["Invalid base64 transaction"])

        try:
            algod_client = AlgorandClient().algod
            try:
                tx_id = algod_client.send_raw_transaction(base64.b64encode(stx_bytes).decode('utf-8'))
            except Exception as e:
                err_str = str(e)
                if "already in pool" in err_str.lower() or "already in ledger" in err_str.lower():
                    import re
                    txid_match = re.search(r'([A-Z2-7]{52})', err_str)
                    tx_id = txid_match.group(1) if txid_match else "already-in-pool"
                else:
                    raise
            tx_hash = tx_id if isinstance(tx_id, str) else tx_id.get('txId') if isinstance(tx_id, dict) else None
            return SubmitPayrollVaultWithdrawal(success=True, errors=None, transaction_hash=tx_hash)
        except Exception as e:
            try:
                logger.exception("[Payroll] withdraw broadcast failed: %s", e)
            except Exception:
                pass
            msg = str(e)
            friendly = None
            if "logic eval error" in msg:
                friendly = "El contrato rechazó la transacción de retiro. Verifica el monto y los permisos."
            return SubmitPayrollVaultWithdrawal(success=False, errors=[friendly or f"Broadcast failed: {e}"], transaction_hash=None)


class SetBusinessDelegates(graphene.Mutation):
    class Arguments:
        business_account = graphene.String(required=True, description="Business account address")
        add = graphene.List(graphene.String, required=True)
        remove = graphene.List(graphene.String, required=True)
        signed_transaction = graphene.String(required=False, description="Optional base64 signed AppCall; if provided, server will broadcast.")

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    unsigned_transaction_b64 = graphene.String()
    transaction_hash = graphene.String()
    logger = logging.getLogger(__name__)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, business_account, add, remove, signed_transaction=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SetBusinessDelegates(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        allowed_business_ids = set()
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            allowed_business_ids.add(ctx['business_id'])

        if not allowed_business_ids:
            return SetBusinessDelegates(success=False, errors=["Business context with send_funds permission required"])
        try:
            cls.logger.info("[Payroll] set_business_delegates start user=%s business_account=%s add=%s remove=%s ctx=%s",
                            getattr(user, 'id', None), business_account, add, remove, ctx)
        except Exception:
            pass

        from users.models import Account
        # Ensure provided business account matches context
        biz_acct = Account.objects.filter(
            business_id__in=allowed_business_ids,
            account_type='business',
            algorand_address=business_account,
            deleted_at__isnull=True,
        ).first()
        if not biz_acct:
            return SetBusinessDelegates(success=False, errors=["Business account not found for this context"])

        if not biz_acct.algorand_address:
            return SetBusinessDelegates(success=False, errors=["Business account missing Algorand address"])

        # Ensure owner personal address is included in allowlist adds
        add_set = set(add or [])
        try:
            from users.models_employee import BusinessEmployee
            owners = BusinessEmployee.objects.filter(
                business_id__in=allowed_business_ids,
                role__iexact='owner',
                is_active=True,
                deleted_at__isnull=True,
            ).values_list('user_id', flat=True)
            if owners:
                owner_accounts = Account.objects.filter(
                    user_id__in=owners,
                    account_type='personal',
                    deleted_at__isnull=True,
                    account_index=0,
                )
                for acc in owner_accounts:
                    if acc.algorand_address:
                        add_set.add(acc.algorand_address)
            # Also include owner of the business account directly
            if biz_acct.user_id:
                owner_personal = Account.objects.filter(
                    user_id=biz_acct.user_id,
                    account_type='personal',
                    account_index=0,
                    deleted_at__isnull=True,
                ).exclude(algorand_address__isnull=True).exclude(algorand_address__exact='').first()
                if owner_personal and owner_personal.algorand_address:
                    add_set.add(owner_personal.algorand_address)
        except Exception:
            pass

        # Always include the current user's personal address (delegate) if available
        try:
            current_personal = Account.objects.filter(
                user=user,
                account_type='personal',
                account_index=0,
                deleted_at__isnull=True,
            ).exclude(algorand_address__isnull=True).exclude(algorand_address__exact='').first()
            if current_personal and current_personal.algorand_address:
                add_set.add(current_personal.algorand_address)
        except Exception:
            pass

        # Build unsigned txn for set_business_delegates
        builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)
        try:
            sp = builder.algod_client.suggested_params()
            txn = builder.build_set_business_delegates(
                business_account=business_account,
                add=list(add_set),
                remove=remove or [],
                suggested_params=sp,
            )
            unsigned_b64 = algo_encoding.msgpack_encode(txn)
        except Exception as e:
            try:
                cls.logger.exception("[Payroll] set_business_delegates build failed biz=%s add=%s remove=%s", business_account, add_set, remove)
            except Exception:
                pass
            return SetBusinessDelegates(success=False, errors=[f"Build failed: {e}"], unsigned_transaction_b64=None, transaction_hash=None)

        # If a signed transaction is provided, broadcast it
        if signed_transaction:
            try:
                stx_str = str(signed_transaction or "").strip()
                stx_str = stx_str.replace('-', '+').replace('_', '/')
                if len(stx_str) % 4 != 0:
                    stx_str = stx_str + ('=' * ((4 - (len(stx_str) % 4)) % 4))
                stx_bytes = base64.b64decode(stx_str)
            except Exception:
                return SetBusinessDelegates(success=False, errors=["Invalid base64 transaction"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

            try:
                algod_client = builder.algod_client
                try:
                    print(f"[Payroll] Submitting delegate txn len={len(stx_bytes)} first8={list(stx_bytes[:8])}")
                except Exception:
                    pass
                stx_b64 = base64.b64encode(stx_bytes).decode('utf-8')
                try:
                    tx_id = algod_client.send_raw_transaction(stx_b64)
                except Exception as e:
                    err_str = str(e)
                    if "already in pool" in err_str.lower() or "already in ledger" in err_str.lower():
                        import re
                        txid_match = re.search(r'([A-Z2-7]{52})', err_str)
                        tx_id = txid_match.group(1) if txid_match else "already-in-pool"
                    else:
                        raise
                try:
                    cls.logger.info("[Payroll] set_business_delegates broadcast ok tx_id=%s biz=%s add=%s remove=%s", tx_id, business_account, add_set, remove)
                except Exception:
                    pass
                
                # Automatically fund vault with ALGO for minimum balance requirements
                try:
                    from blockchain.algorand_sponsor_service import algorand_sponsor_service
                    import asyncio
                    
                    # Get app address (vault)
                    app_addr = algo_logic.get_application_address(settings.ALGORAND_PAYROLL_APP_ID)
                    
                    # Check if vault needs funding
                    try:
                        vault_info = algod_client.account_info(app_addr)
                        current_balance = vault_info.get('amount', 0)
                        min_balance = vault_info.get('min-balance', 0)
                        
                        if current_balance < min_balance + 500_000:  # Fund if below min + 0.5 ALGO buffer
                            cls.logger.info("[Payroll] Auto-funding vault %s (current: %s, min: %s)", app_addr, current_balance, min_balance)
                            
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                            
                            fund_result = loop.run_until_complete(
                                algorand_sponsor_service.fund_account(app_addr, 1_000_000)  # 1 ALGO
                            )
                            
                            if fund_result.get('success'):
                                cls.logger.info("[Payroll] Vault auto-funded successfully: %s", fund_result.get('tx_id'))
                            else:
                                cls.logger.warning("[Payroll] Vault auto-funding failed: %s", fund_result.get('error'))
                        else:
                            cls.logger.info("[Payroll] Vault has sufficient balance (%s >= %s)", current_balance, min_balance)
                    except Exception as e:
                        cls.logger.warning("[Payroll] Could not check/fund vault: %s", e)
                except Exception as e:
                    cls.logger.warning("[Payroll] Vault auto-funding error: %s", e)
                
                return SetBusinessDelegates(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=tx_id)
            except Exception as e:
                try:
                    cls.logger.exception("[Payroll] set_business_delegates broadcast failed biz=%s add=%s remove=%s err=%s", business_account, add_set, remove, e)
                except Exception:
                    pass
                return SetBusinessDelegates(success=False, errors=[f"Broadcast failed: {e}"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

        # Return unsigned txn for client signing
        return SetBusinessDelegates(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=None)


class SetBusinessDelegatesByEmployee(graphene.Mutation):
    class Arguments:
        business_account = graphene.String(required=True, description="Business account address")
        add_employee_ids = graphene.List(graphene.ID, required=True, description="Employee IDs to add as delegates")
        remove_employee_ids = graphene.List(graphene.ID, required=True, description="Employee IDs to remove as delegates")
        signed_transaction = graphene.String(required=False, description="Optional base64 signed AppCall; if provided, server will broadcast.")

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    unsigned_transaction_b64 = graphene.String()
    transaction_hash = graphene.String()
    logger = logging.getLogger(__name__)

    @classmethod
    @graphql_require_kyc('send_money')
    @graphql_require_aml()
    def mutate(cls, root, info, business_account, add_employee_ids, remove_employee_ids, signed_transaction=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SetBusinessDelegatesByEmployee(success=False, errors=["Authentication required"])

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        allowed_business_ids = set()
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            allowed_business_ids.add(ctx['business_id'])

        if not allowed_business_ids:
            return SetBusinessDelegatesByEmployee(success=False, errors=["Business context with send_funds permission required"])

        try:
            cls.logger.info("[Payroll] set_business_delegates_by_employee start user=%s business_account=%s add_ids=%s remove_ids=%s ctx=%s",
                            getattr(user, 'id', None), business_account, add_employee_ids, remove_employee_ids, ctx)
        except Exception:
            pass

        from users.models import Account
        from users.models_employee import BusinessEmployee

        biz_acct = Account.objects.filter(
            business_id__in=allowed_business_ids,
            account_type='business',
            algorand_address=business_account,
            deleted_at__isnull=True,
        ).first()
        if not biz_acct:
            return SetBusinessDelegatesByEmployee(success=False, errors=["Business account not found for this context"])
        if not biz_acct.algorand_address:
            return SetBusinessDelegatesByEmployee(success=False, errors=["Business account missing Algorand address"])

        add_set = set()
        remove_set = set()
        errors = []

        combined_ids = (add_employee_ids or []) + (remove_employee_ids or [])
        employees = {
            str(be.id): be for be in BusinessEmployee.objects.filter(
                id__in=combined_ids,
                business_id__in=allowed_business_ids,
                deleted_at__isnull=True,
            ).select_related('user')
        }

        def resolve_personal_address(be: BusinessEmployee):
            return Account.objects.filter(
                user_id=be.user_id,
                account_type='personal',
                account_index=0,
                deleted_at__isnull=True,
            ).exclude(algorand_address__isnull=True).exclude(algorand_address__exact='').first()

        for emp_id in add_employee_ids or []:
            be = employees.get(str(emp_id))
            if not be:
                errors.append(f"Empleado {emp_id} no encontrado o sin acceso.")
                continue
            if not be.is_active:
                errors.append(f"Empleado {be.user.username if be.user else emp_id} inactivo.")
                continue
            acct = resolve_personal_address(be)
            if acct and acct.algorand_address:
                add_set.add(acct.algorand_address)
            else:
                display = be.user.username if getattr(be, 'user', None) else str(emp_id)
                errors.append(f"Empleado {display} no tiene cuenta personal con dirección Algorand.")

        for emp_id in remove_employee_ids or []:
            be = employees.get(str(emp_id))
            if not be:
                continue
            acct = resolve_personal_address(be)
            if acct and acct.algorand_address:
                remove_set.add(acct.algorand_address)

        # Persist permission overrides so UI can reflect delegate status
        try:
            for emp_id in add_employee_ids or []:
                be = employees.get(str(emp_id))
                if not be:
                    continue
                perms = be.permissions or {}
                perms['send_funds'] = True
                be.permissions = perms
                be.save(update_fields=['permissions', 'updated_at'])
            for emp_id in remove_employee_ids or []:
                be = employees.get(str(emp_id))
                if not be:
                    continue
                # An owner's sending authority is not a delegate flag. This
                # mutation is gated on send_funds alone, so without this any
                # manager could aim it at the owner's employee row — every
                # business has one — and revoke the owner's authority across
                # the whole product. The gate ignores owner overrides too;
                # this is the second lock on the same door.
                #
                # Tested by ACCOUNT ownership, not by be.role: the role string
                # is delegation, so keying on it protected a non-owner who had
                # merely been handed 'owner' while leaving a real owner whose
                # row was demoted wide open to exactly this revocation.
                from users.models import Account as _Account
                if _Account.objects.filter(
                        user=be.user, business_id=be.business_id,
                        account_type='business', deleted_at__isnull=True).exists():
                    errors.append(
                        "No se puede quitar el permiso de envío al dueño del negocio.")
                    continue
                perms = be.permissions or {}
                perms['send_funds'] = False
                be.permissions = perms
                be.save(update_fields=['permissions', 'updated_at'])
        except Exception as e:
            errors.append(f"No se pudieron actualizar permisos: {e}")

        # Include owners and current user personal for safety (allowlist)
        try:
            owners = BusinessEmployee.objects.filter(
                business_id__in=allowed_business_ids,
                role__iexact='owner',
                is_active=True,
                deleted_at__isnull=True,
            ).values_list('user_id', flat=True)
            if owners:
                owner_accounts = Account.objects.filter(
                    user_id__in=owners,
                    account_type='personal',
                    deleted_at__isnull=True,
                    account_index=0,
                )
                for acc in owner_accounts:
                    if acc.algorand_address:
                        add_set.add(acc.algorand_address)
        except Exception:
            pass

        try:
            if biz_acct.user_id:
                owner_personal = Account.objects.filter(
                    user_id=biz_acct.user_id,
                    account_type='personal',
                    account_index=0,
                    deleted_at__isnull=True,
                ).exclude(algorand_address__isnull=True).exclude(algorand_address__exact='').first()
                if owner_personal and owner_personal.algorand_address:
                    add_set.add(owner_personal.algorand_address)
        except Exception:
            pass

        try:
            current_personal = Account.objects.filter(
                user=user,
                account_type='personal',
                account_index=0,
                deleted_at__isnull=True,
            ).exclude(algorand_address__isnull=True).exclude(algorand_address__exact='').first()
            if current_personal and current_personal.algorand_address:
                add_set.add(current_personal.algorand_address)
        except Exception:
            pass

        # Always include the business account itself in the allowlist
        # This is required for the system to recognize the payroll as activated (resolve_payroll_delegates checks this)
        if business_account:
            add_set.add(business_account)

        if errors:
            return SetBusinessDelegatesByEmployee(success=False, errors=errors, unsigned_transaction_b64=None, transaction_hash=None)

        builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)
        
        # Determine sponsor address from settings
        sponsor_address = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_ADDRESS')
        if not sponsor_address:
             return SetBusinessDelegatesByEmployee(success=False, errors=["Sponsor address not configured"], unsigned_transaction_b64=None, transaction_hash=None)

        try:
            # Retry suggested_params up to 3 times to handle timeouts
            sp = None
            last_err = None
            for _ in range(3):
                try:
                    sp = builder.algod_client.suggested_params()
                    break
                except Exception as e:
                    last_err = e
                    import time
                    time.sleep(0.5)
            
            if not sp:
                raise last_err or Exception("Failed to get suggested params")

            # Build Atomic Group: [SponsorPay, BusinessAppCall]
            txns = builder.build_set_business_delegates_group(
                business_account=business_account,
                add=list(add_set),
                remove=list(remove_set),
                sponsor_address=sponsor_address,
                sponsor_amount=500_000, # 0.5 Algo funding
                suggested_params=sp,
            )
            # txns[0] is Sponsor Pay, txns[1] is Business App Call
            
            # Save the unsigned Business Transaction to return to client
            # The client needs THIS exact transaction because it contains the group ID
            unsigned_b64 = algo_encoding.msgpack_encode(txns[1])
            
            # We don't sign or save the sponsor txn here yet. We rebuild it on submit.
            # But wait, if we rebuild it on submit, we must ensure we use the EXACT same params (fv, lv, gh, gen).
            # The client will sign txns[1] which contains the group ID.
            # When we receive signed txns[1], we extract its params and rebuild txns[0] with same params.
            
        except Exception as e:
            try:
                cls.logger.exception("[Payroll] set_business_delegates_by_employee build failed biz=%s add=%s remove=%s", business_account, add_set, remove_set)
            except Exception:
                pass
            return SetBusinessDelegatesByEmployee(success=False, errors=[f"Build failed: {e}"], unsigned_transaction_b64=None, transaction_hash=None)

        if signed_transaction:
                # Deterministic Reconstruction and Submission
            try:
                # 1. Decode signed business transaction
                stx_str = str(signed_transaction or "").strip()
                stx_str = stx_str.replace('-', '+').replace('_', '/')
                if len(stx_str) % 4 != 0:
                    stx_str = stx_str + ('=' * ((4 - (len(stx_str) % 4)) % 4))
                
                # Note: algo_encoding.msgpack_decode expects a BASE64 STRING.
                stx_bytes = base64.b64decode(stx_str) # Still needed for generic error check or later usage?
                # Actually, we need stx_bytes only if we are concatenating raw bytes later.
                
                # Decode as SignedTransaction to get the inner Transaction
                stx_obj = algo_encoding.msgpack_decode(stx_str)
                cls.logger.info("[Payroll] Decoded STX type: %s, Dir: %s", type(stx_obj), dir(stx_obj))

                business_txn = None
                if hasattr(stx_obj, 'txn'):
                    business_txn = stx_obj.txn
                elif hasattr(stx_obj, 'transaction'):
                    business_txn = stx_obj.transaction
                
                # If decoded object IS the transaction (implies unsigned or weird decoding), check that
                if not business_txn and isinstance(stx_obj, transaction.Transaction):
                    # It's an unsigned transaction! We can't broadcast this.
                    cls.logger.error("[Payroll] Received UNSIGNED transaction object: %s", stx_obj)
                    return SetBusinessDelegatesByEmployee(success=False, errors=["Received unsigned transaction. Please sign the transaction."], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)
                
                if not business_txn:
                     return SetBusinessDelegatesByEmployee(success=False, errors=[f"Invalid signed transaction format (Type: {type(stx_obj)})"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)
                
                group_id_bytes = business_txn.group
                
                if not group_id_bytes:
                     return SetBusinessDelegatesByEmployee(success=False, errors=["Transaction is missing group ID"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

                # 2. Rebuild Sponsor Transaction using parameters from Business Transaction
                # Use standard SuggestParams structure populated from the received txn
                from algosdk.transaction import SuggestedParams, PaymentTxn
                
                rebuilt_sp = SuggestedParams(
                    fee=1000,
                    first=business_txn.first_valid_round,
                    last=business_txn.last_valid_round,
                    gh=business_txn.genesis_hash,
                    gen=business_txn.genesis_id,
                    flat_fee=True
                )
                
                sponsor_txn = PaymentTxn(
                    sender=sponsor_address,
                    sp=rebuilt_sp,
                    receiver=business_account,
                    amt=500_000, # Must match creation amount exactly
                    note=b"Payroll Setup Sponsor" # Must match creation note exactly
                )
                sponsor_txn.group = group_id_bytes # Assign the Group ID directly
                
                # 3. Sign Sponsor Transaction
                from blockchain.kms_manager import get_kms_signer_from_settings
                signer = get_kms_signer_from_settings()
                sponsor_stx = signer.sign_transaction_msgpack(sponsor_txn)
                
                # 4. Assemble Group: [SponsorSigned, BusinessSigned]
                # Combine raw bytes: standard Algorand SDK broadcast expects concatenated binaries? 
                # Or send_raw_transaction takes one blob? It takes concatenated blobs.
                # Sponsor STX is msgpack bytes. Business STX is `stx_bytes`.
                group_blob = base64.b64decode(sponsor_stx) + stx_bytes
                
                # 5. Broadcast
                algod_client = builder.algod_client
                group_b64 = base64.b64encode(group_blob).decode('utf-8')
                try:
                    tx_id = algod_client.send_raw_transaction(group_b64)
                except Exception as e:
                    err_str = str(e)
                    if "already in pool" in err_str.lower() or "already in ledger" in err_str.lower():
                        import re
                        txid_match = re.search(r'([A-Z2-7]{52})', err_str)
                        tx_id = txid_match.group(1) if txid_match else "already-in-pool"
                    else:
                        raise
                
                try:
                    cls.logger.info("[Payroll] set_business_delegates_by_employee atomic broadcast ok tx_id=%s biz=%s", tx_id, business_account)
                except Exception:
                    pass

                # Automatically fund vault for minimum balance (separate from fee sponsorship)
                try:
                    from blockchain.algorand_sponsor_service import algorand_sponsor_service
                    import asyncio
                    
                    app_addr = algo_logic.get_application_address(settings.ALGORAND_PAYROLL_APP_ID)
                    
                    try:
                        vault_info = algod_client.account_info(app_addr)
                        current_balance = vault_info.get('amount', 0)
                        min_balance = vault_info.get('min-balance', 0)
                        
                        if current_balance < min_balance + 500_000:
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                            
                            loop.run_until_complete(
                                algorand_sponsor_service.fund_account(app_addr, 1_000_000)
                            )
                    except Exception as e:
                        cls.logger.warning("[Payroll] Could not check/fund vault: %s", e)
                except Exception as e:
                    cls.logger.warning("[Payroll] Vault auto-funding error: %s", e)
                
                # The returned tx_id from a group is usually the ID of the first txn? 
                # Or we can return the ID of the business txn (which is what we care about).
                # Business txn ID is the hash of business_txn.
                business_tx_id = business_txn.get_txid()

                return SetBusinessDelegatesByEmployee(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=business_tx_id)
            except Exception as e:
                try:
                    cls.logger.exception("[Payroll] set_business_delegates_by_employee broadcast failed biz=%s err=%s", business_account, e)
                except Exception:
                    pass
                return SetBusinessDelegatesByEmployee(success=False, errors=[f"Broadcast failed: {e}"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

        return SetBusinessDelegatesByEmployee(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=None)



def mask_string(s):
    """Mask string (e.g. 'Julian' -> 'Ju****')"""
    if not s or len(s) < 2:
        return "****"
    return f"{s[:2]}****"

def mask_phone(phone):
    """Mask phone (e.g. '1234567890' -> '******7890')"""
    if not phone or len(phone) < 4:
        return "****"
    return f"******{phone[-4:]}"


class VerifiedPayrollTransactionType(graphene.ObjectType):
    is_valid = graphene.Boolean()
    status = graphene.String()  # VALID, REVOKED, INVALID, ERROR
    transaction_hash = graphene.String()
    amount = graphene.String()
    currency = graphene.String()
    timestamp = graphene.DateTime()
    
    sender_name = graphene.String()
    
    recipient_name_masked = graphene.String()
    recipient_phone_masked = graphene.String()
    
    verification_message = graphene.String()


class PayrollRailStatusType(graphene.ObjectType):
    """Everything the payroll screens need to describe THIS business's rail
    without guessing at it client-side.

    It exists because the app was deriving all of this from an Algorand
    address list: which token wages are paid in, whether payroll is
    activated, who the delegates are. On BSC the delegate is an EVM address
    the client has no copy of, so the question is answered here — in
    employee ids, which the client already holds — instead of shipping
    addresses to the phone to be string-matched."""

    rail = graphene.String(
        description="bsc | algorand — where this business's payroll money currently IS")
    execution_rail = graphene.String(
        description="bsc | algorand — where NEW work (funding, fresh runs) executes. "
                    "Differs from `rail` only while the kill switch is on with money still parked.")
    token_type = graphene.String(
        description="Token a run created now is denominated in — CUSD_PLUS on BSC, "
                    "or CUSD_BSC for an Ondo-blocked employer")
    funding_token = graphene.String(
        description="DEFAULT pool for a top-up: CUSD_PLUS or CUSD_BSC. A hint, not a "
                    "constraint — the client may fund or withdraw either pool "
                    "explicitly. Names the asset fundableBalanceUsd is measured in.")
    escrow_cusd_plus_usd = graphene.Float(
        description="Payroll escrow parked as cUSD+ shares, in USD. null = unknown")
    escrow_usdt_usd = graphene.Float(
        description="Legacy payroll escrow parked as raw USDT, in USD. null = unknown")
    escrow_cusd_usd = graphene.Float(
        description="Payroll escrow parked as universal cUSD, in USD. null = unknown")
    fundable_cusd_plus_usd = graphene.Float(
        description="Business wallet cUSD+ position a top-up could park, in USD")
    fundable_usdt_usd = graphene.Float(
        description="Legacy business-wallet raw USDT, in USD")
    fundable_cusd_usd = graphene.Float(
        description="Business wallet cUSD a top-up could park, in USD")
    vault_balance_usd = graphene.Float(description="Payroll escrow, in USD")
    fundable_balance_usd = graphene.Float(
        description="Business balance a top-up can draw from, in USD, measured in "
                    "whatever fundingToken names — the cUSD+ position or universal cUSD")
    activated = graphene.Boolean(description="At least one signer is allowlisted, so a payout can be authorized")
    delegate_employee_ids = graphene.List(
        graphene.ID, description="BusinessEmployee ids whose signer is allowlisted on the rail")


class Query(graphene.ObjectType):
    payroll_runs = graphene.List(PayrollRunType)
    pending_payroll_items = graphene.List(PayrollItemType, description="Pending payroll items for delegate user")
    payroll_recipients = graphene.List(PayrollRecipientType, description="Saved payroll recipients for the current business")
    payroll_delegates = graphene.List(graphene.String, description="Delegates for the current business account")
    payroll_vault_balance = graphene.Float(description="Balance of payroll vault for this business (token units)")
    payroll_rail_status = graphene.Field(
        PayrollRailStatusType,
        description="Rail, token, escrow and delegate status for the current business")

    verify_payroll_transaction = graphene.Field(
        VerifiedPayrollTransactionType,
        transaction_hash=graphene.String(required=True)
    )

    def resolve_verify_payroll_transaction(self, info, transaction_hash):
        try:
            # Clean hash
            tx_hash = str(transaction_hash).strip()
            
            # Find item
            item = PayrollItem.objects.select_related(
                'run__business', 
                'recipient_user'
            ).filter(
                transaction_hash=tx_hash
            ).first()

            if not item:
                return VerifiedPayrollTransactionType(
                    is_valid=False,
                    status='INVALID',
                    verification_message="Transacción no encontrada en los registros de Confío."
                )

            # Check if revoked (deleted or failed/cancelled status)
            if item.deleted_at or item.status in ['FAILED', 'CANCELLED']:
                return VerifiedPayrollTransactionType(
                    is_valid=False,
                    status='REVOKED',
                    transaction_hash=tx_hash,
                    verification_message="Esta transacción fue anulada o revocada."
                )

            # Valid
            user = item.recipient_user
            
            return VerifiedPayrollTransactionType(
                is_valid=True,
                status='VALID',
                transaction_hash=tx_hash,
                amount=f"{item.net_amount:f}",
                currency=item.token_type,
                timestamp=item.executed_at or item.updated_at,
                sender_name=item.run.business.name,
                recipient_name_masked=f"{mask_string(user.first_name)} {mask_string(user.last_name)}",
                recipient_phone_masked=mask_phone(user.phone_key) if user.phone_key else None,
                verification_message="Transacción verificada y certificada por Confío."
            )

        except Exception:
            return VerifiedPayrollTransactionType(
                is_valid=False,
                status='ERROR',
                verification_message="Ocurrió un error al verificar."
            )

    def _kyc_aml_ok(self, user, operation_type: str):
        if not user or not getattr(user, 'is_authenticated', False):
            return False, ["Authentication required"]
        required, reason = check_kyc_required(user, operation_type, None)
        if required:
            return False, [reason]
        aml_result = perform_aml_check(user=user, transaction_type=operation_type)
        if aml_result.get('blocked', False):
            return False, [aml_result.get('reason', 'Transaction blocked by AML')]
        return True, []

    def resolve_payroll_runs(self, info, **kwargs):
        user = getattr(info.context, 'user', None)
        ok, _ = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return []

        ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return []

        return PayrollRun.objects.filter(business_id=ctx['business_id'])

    def resolve_pending_payroll_items(self, info, **kwargs):
        """Pending payroll items for businesses where the user is an active employee (delegate)."""
        user = getattr(info.context, 'user', None)
        ok, _ = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return []

        # GATED ON send_funds, the same permission the payout mutation
        # requires. This list is not a report — HomeScreen turns a non-empty
        # answer into a payroll card with a Pagar button, so anything served
        # here is an action we are offering. It used to filter on
        # BusinessEmployee.is_active alone, which handed the card to every
        # cashier of every business the user works at: people the app will
        # not even let the owner APPOINT as a payroll delegate
        # (PayrollDelegatesManageScreen excludes role 'cashier'), sent to a
        # button that could only ever answer permission_denied.
        #
        # If caller is in a business context (owner/admin), return that
        # business' items.
        ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            # Second call rather than one gated call: a permission failure
            # must return NOTHING, not fall through to the delegate branch
            # below and hand back the same business's items anyway.
            if not get_jwt_business_context_with_validation(
                    info, required_permission='send_funds'):
                return []
            return PayrollItem.objects.filter(
                run__business_id=ctx['business_id'],
                status__in=['PENDING', 'PREPARED'],
                deleted_at__isnull=True
            ).select_related('run', 'recipient_account', 'recipient_user')

        # Otherwise, fall back to delegate view (employee of any business),
        # keeping only the businesses this user could actually pay.
        from users.models_employee import BusinessEmployee
        from users.jwt_context import check_role_permission
        biz_ids = []
        for emp in BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).only('business_id', 'role', 'permissions'):
            # Same two-step as jwt_context: the role matrix grants, and an
            # explicit per-employee False revokes. Deny-only — an explicit
            # True is left to the matrix, so this cannot widen the role.
            overrides = emp.permissions or {}
            if 'send_funds' in overrides and not overrides['send_funds']:
                continue
            if check_role_permission(emp.role, 'send_funds'):
                biz_ids.append(emp.business_id)

        if not biz_ids:
            return []

        return PayrollItem.objects.filter(
            run__business_id__in=biz_ids,
            status__in=['PENDING', 'PREPARED'],
            deleted_at__isnull=True
        ).select_related('run', 'recipient_account', 'recipient_user')

    def resolve_payroll_recipients(self, info, **kwargs):
        """Saved payroll recipients (no permissions) for the current business context."""
        user = getattr(info.context, 'user', None)
        ok, _ = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return []

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return []

        return PayrollRecipient.objects.filter(
            business_id=ctx['business_id'],
            deleted_at__isnull=True
        ).select_related('recipient_user', 'recipient_account')

    def resolve_payroll_delegates(self, info, **kwargs):
        """Delegates for the current business context (addresses)."""
        user = getattr(info.context, 'user', None)
        ok, err = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return []

        ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not ctx or ctx.get('account_type') != 'business' or not ctx.get('business_id'):
            return []

        from users.models import Account
        biz_acct = Account.objects.filter(
            business_id=ctx['business_id'],
            account_type='business',
            deleted_at__isnull=True
        ).order_by('account_index').first()
        if not biz_acct:
            return []

        # On the BSC rail the allowlist lives in ConfioPayrollVault, not in
        # Algorand boxes — an address list read off the wrong chain is the
        # reason a business that had already delegated on BSC still saw
        # "nómina no activada".
        from . import bsc_flow
        if bsc_flow.display_rail(biz_acct) == 'bsc':
            biz_addr = (biz_acct.bsc_address or '').lower()
            candidates = [addr for _eid, addr in _delegate_candidates(biz_acct)]
            return bsc_flow.onchain_delegates(biz_addr, [biz_addr] + candidates)

        if not biz_acct.algorand_address:
            return []

        logger = logging.getLogger(__name__)
        biz_addr = biz_acct.algorand_address
        delegates = set()
        print(f"[Payroll DEBUG] resolve_payroll_delegates for biz={biz_addr}")

        # Try to read allowlist boxes for this business to return all delegates (biz||delegate)
        try:
            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
            prefix = algo_encoding.decode_address(biz_addr)
            print(f"[Payroll DEBUG] Looking for boxes with prefix (biz address decoded)")
            
            # Get all boxes for this application
            boxes_resp = algod_client.application_boxes(settings.ALGORAND_PAYROLL_APP_ID)
            boxes = boxes_resp.get('boxes', [])
            box_count = 0
            print(f"[Payroll DEBUG] Found {len(boxes)} total boxes")
            
            for box in boxes:
                try:
                    box_count += 1
                    name_bytes = base64.b64decode(box.get('name', ''))
                    print(f"[Payroll DEBUG] Box #{box_count}: name_bytes length={len(name_bytes)}, prefix length={len(prefix)}")
                    if not name_bytes.startswith(prefix):
                        print(f"[Payroll DEBUG] Box #{box_count}: Does not start with prefix, skipping")
                        continue
                    if len(name_bytes) < len(prefix) + 32:
                        print(f"[Payroll DEBUG] Box #{box_count}: Too short (< {len(prefix) + 32} bytes), skipping")
                        continue
                    delegate_bytes = name_bytes[len(prefix):len(prefix) + 32]
                    delegate_addr = algo_encoding.encode_address(delegate_bytes)
                    print(f"[Payroll DEBUG] Box #{box_count}: Extracted delegate address: {delegate_addr}")
                    delegates.add(delegate_addr)
                except Exception as e:
                    print(f"[Payroll DEBUG] Box #{box_count}: Error extracting delegate: {e}")
                    continue
            
            print(f"[Payroll DEBUG] Total delegates found: {len(delegates)}, addresses: {delegates}")
        except Exception as e:
            logger.warning("[Payroll] Failed to read delegates from allowlist boxes: %s", e)
            print(f"[Payroll DEBUG] Exception reading boxes: {e}")
            # Fall back to simple allowlist existence check (biz||biz)
            try:
                algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
                allow_key = algo_encoding.decode_address(biz_addr) + algo_encoding.decode_address(biz_addr)
                algod_client.application_box_by_name(settings.ALGORAND_PAYROLL_APP_ID, allow_key)
                print(f"[Payroll DEBUG] Fallback: Found biz||biz box, adding business address")
                delegates.add(biz_addr)
            except Exception:
                print(f"[Payroll DEBUG] Fallback: biz||biz box not found, returning empty")
                return []

        return list(delegates)

    def resolve_payroll_vault_balance(self, info, **kwargs):
        """Return payroll escrow balance for the payroll asset (per business vault box, normalized to token units)."""
        user = getattr(info.context, 'user', None)
        ok, _ = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return 0
        try:
            biz_acct = _payroll_business_account(info, user)
            if not biz_acct:
                return 0

            # The escrow the payout actually spends. Reading the Algorand box
            # for a business funded on BSC reported $0.00 next to a working
            # "Agregar fondos" button.
            from . import bsc_flow
            if bsc_flow.display_rail(biz_acct) == 'bsc':
                # May be None (node unreachable, nothing cached). Null travels
                # to the client as "—"; 0.0 would be a claim we cannot make.
                return bsc_flow.escrow_usd((biz_acct.bsc_address or '').lower())

            if not biz_acct.algorand_address:
                return 0

            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS, headers={"User-Agent": "py-algorand-sdk"})
            box_name = b"VAULT" + algo_encoding.decode_address(biz_acct.algorand_address)
            box = algod_client.application_box_by_name(settings.ALGORAND_PAYROLL_APP_ID, box_name)
            import base64
            data = base64.b64decode(box.get('value', ''))
            if len(data) >= 8:
                amt = int.from_bytes(data[:8], 'big')
                return float(amt) / 1_000_000
            return 0
        except Exception:
            return 0

    def resolve_payroll_rail_status(self, info, **kwargs):
        user = getattr(info.context, 'user', None)
        ok, _ = Query._kyc_aml_ok(self, user, 'send_money')
        if not ok:
            return None
        biz_acct = _payroll_business_account(info, user)
        if not biz_acct:
            return None

        from . import bsc_flow
        # Where the money IS drives the label and the balance; where new work
        # RUNS drives the token a fresh run would carry. They differ only
        # inside the kill-switch window, and there the honest answer is
        # "your float is in cUSD+, but a new run would be created in cUSD".
        rail = bsc_flow.display_rail(biz_acct)
        exec_rail = bsc_flow.execution_rail(biz_acct)

        # WHO the delegates are is the same question payrollDelegates answers,
        # and it has always required send_funds in a real business context.
        # Serving it here at KYC-only would have handed the employer's signer
        # roster to any employee — a cashier included — purely because this
        # field happened to be new.
        may_see_delegates = bool(get_jwt_business_context_with_validation(
            info, required_permission='send_funds'))
        # Balances follow view_balance. The client masks them with "••••" for
        # a revoked employee, but masking in the UI while the GraphQL response
        # carries the number is not a permission — it is a curtain. In a
        # personal (delegate) context there is no business JWT to check, which
        # is the pre-existing shape of payrollVaultBalance; the NEW field
        # (fundable) stays business-context-only regardless.
        in_business_ctx = bool(get_jwt_business_context_with_validation(
            info, required_permission=None)) and (
                (get_jwt_business_context_with_validation(info, required_permission=None) or {})
                .get('account_type') == 'business')
        may_see_balance = (
            bool(get_jwt_business_context_with_validation(
                info, required_permission='view_balance'))
            if in_business_ctx else True)
        vault_usd = None
        fundable_usd = None
        delegate_ids = []

        if rail == 'bsc':
            biz_addr = (biz_acct.bsc_address or '').lower()
            vault_usd = bsc_flow.escrow_usd(biz_addr)
            try:
                from cusd_plus import vault as cp_vault
                # What a top-up spends — in the asset this business can
                # actually park. Reporting the cUSD+ position unconditionally
                # told an Ondo-blocked employer it had $0.00 to fund with
                # while it held thousands in cUSD, and the funding call
                # then failed "insufficient balance" on money it owned.
                # Same answer prepare_bsc_payroll_admin builds the batch from.
                funding_token = bsc_flow.funding_token(biz_acct, user)
                # Per-pool, because the pools are not fungible: a business
                # holding both can only move one per operation, and a single
                # summed figure let the top-up screen validate a withdrawal
                # against money the chosen pool did not have (audit
                # 2026-08-02, [P1]). fundable_usd stays as the DEFAULT pool's
                # figure so older clients keep working.
                escrow_split = bsc_flow.escrow_split_usd(biz_addr)
                fundable_split = bsc_flow.fundable_split_usd(biz_addr)
                fundable_usd = fundable_split.get(funding_token)
            except Exception:  # noqa: BLE001
                funding_token = None
                fundable_usd = None
                escrow_split = {}
                fundable_split = {}
            # One eth_call per candidate, so only enumerate when the answer is
            # actually going to be sent. When it is not, the two addresses that
            # settle `activated` are enough.
            candidates = _delegate_candidates(biz_acct) if may_see_delegates else []
            probe = [biz_addr] + [addr for _e, addr in candidates]
            if not may_see_delegates:
                signer = _caller_signer_address(user)
                if signer:
                    probe.append(signer)
            allowed, degraded = bsc_flow.onchain_delegates(
                biz_addr, probe, with_status=True)
            allowed = set(allowed)
            delegate_ids = [eid for eid, addr in candidates if addr in allowed]
            # The business EOA counts as a signer the contract accepts even
            # though no employee row carries that address.
            #
            # None, not False, when the chain did not answer: `activated`
            # drives the "Activar nómina" hero, and showing a working
            # business the setup wizard because an RPC call timed out would
            # invite them to re-run activation they already paid for.
            activated = True if allowed else (None if degraded else False)
        else:
            vault_usd = Query.resolve_payroll_vault_balance(self, info)
            # fundable_balance_usd stays null on the legacy rail: that number
            # is the permission-gated accountBalance the client already asks
            # for, and duplicating its view_balance check here would be a
            # second place to get it wrong.
            fundable_usd = None
            funding_token = None
            escrow_split = {}
            fundable_split = {}
            addrs = {
                (a or '').strip().upper()
                for a in (Query.resolve_payroll_delegates(self, info) or [])
            }
            delegate_ids = (_algorand_delegate_employee_ids(biz_acct, addrs)
                            if may_see_delegates else [])
            activated = bool(addrs)

        return PayrollRailStatusType(
            rail=rail,
            token_type=bsc_flow.rail_token(exec_rail, biz_acct, user),
            execution_rail=exec_rail,
            funding_token=funding_token if in_business_ctx else None,
            vault_balance_usd=vault_usd if may_see_balance else None,
            fundable_balance_usd=(fundable_usd
                                  if (may_see_balance and in_business_ctx) else None),
            # Same permission gate as the aggregates they break down: a
            # revoked employee must not read the figures through the split.
            escrow_cusd_plus_usd=(escrow_split.get('CUSD_PLUS')
                                  if may_see_balance else None),
            escrow_usdt_usd=(escrow_split.get('USDT') if may_see_balance else None),
            escrow_cusd_usd=(escrow_split.get('CUSD') if may_see_balance else None),
            fundable_cusd_plus_usd=(fundable_split.get('CUSD_PLUS')
                                    if (may_see_balance and in_business_ctx) else None),
            fundable_usdt_usd=(fundable_split.get('USDT')
                               if (may_see_balance and in_business_ctx) else None),
            fundable_cusd_usd=(fundable_split.get('CUSD')
                               if (may_see_balance and in_business_ctx) else None),
            activated=activated,
            delegate_employee_ids=delegate_ids,
        )


# ═══════════════════ BSC payroll (ConfioPayrollVault) ═══════════════════
# Phase 2 W3 of the cUSD phase-out: escrow + delegate-signed payouts on
# BSC. Two mutation pairs — admin ops (business EOA, 7702 batch rebuilt
# server-side from integer params) and payouts (delegate signs the
# EIP-712 Payout digest with their OWN key; the KMS sponsor broadcasts).


class BscPayrollCallType(graphene.ObjectType):
    """One call of a business admin batch (server-built)."""
    to = graphene.String()
    value_wei = graphene.String()
    data = graphene.String()


class BscPayrollAuthorizationInput(graphene.InputObjectType):
    """A signed EIP-7702 authorization tuple (first use only)."""
    chain_id = graphene.Int(required=True)
    address = graphene.String(required=True)
    nonce = graphene.String(required=True)
    y_parity = graphene.Int(required=True)
    r = graphene.String(required=True)
    s = graphene.String(required=True)


class PrepareBscPayrollAdmin(graphene.Mutation):
    """Business escrow ops: fund / withdraw / set_delegate. Returns the
    canonical batch for the BUSINESS EOA to sign as one 7702 intent."""

    class Arguments:
        action = graphene.String(required=True, description="fund | withdraw | set_delegate")
        amount = graphene.Decimal(required=False, description="USD, for fund/withdraw")
        delegate_user_id = graphene.ID(required=False)
        delegate_user_ids = graphene.List(
            graphene.ID, required=False,
            description="Allowlist several delegates in ONE batch (activation)")
        include_self = graphene.Boolean(
            required=False,
            description="Also allowlist the caller's own signer — activation does this")
        allowed = graphene.Boolean(required=False)
        token_type = graphene.String(
            required=False,
            description="Which escrow pool to fund/withdraw: CUSD_PLUS, CUSD_BSC, or legacy USDT. "
                        "Omit to use the business's default pool.")

    success = graphene.Boolean()
    error = graphene.String()
    error_name = graphene.String(description="Who the error is about, when it names someone")
    calls = graphene.List(BscPayrollCallType)
    shares = graphene.String()
    asset = graphene.Int(
        description="Escrow pool: 0 = cUSD+ shares, 1 = legacy USDT, 2 = cUSD")
    token_type = graphene.String(
        description="The same pool by name — what the top-up is denominated in")
    delegate_address = graphene.String()
    delegate_addresses = graphene.List(graphene.String)
    intent_id = graphene.String()  # bytes32 the client binds into its signature

    def mutate(self, info, action, amount=None, delegate_user_id=None,
               delegate_user_ids=None, include_self=False, allowed=True,
               token_type=None):
        from . import bsc_flow

        jwt_ctx = get_jwt_business_context_with_validation(
            info, required_permission='send_funds')
        if not jwt_ctx:
            return PrepareBscPayrollAdmin(success=False, error='permission_denied')
        result = bsc_flow.prepare_bsc_payroll_admin(
            info.context.user, jwt_ctx, action, amount=amount,
            delegate_user_id=delegate_user_id,
            delegate_user_ids=delegate_user_ids,
            include_self=bool(include_self), allowed=bool(allowed),
            token_type=token_type or '')
        if not result.get('success'):
            return PrepareBscPayrollAdmin(
                success=False, error=result.get('error'),
                error_name=result.get('delegate_name'))
        return PrepareBscPayrollAdmin(
            success=True,
            calls=[
                BscPayrollCallType(to=c['to'], value_wei=c['value'], data=c['data'])
                for c in result['calls']
            ],
            shares=result.get('shares'),
            asset=result.get('asset'),
            token_type=result.get('token_type'),
            delegate_address=result.get('delegate_address'),
            delegate_addresses=result.get('delegate_addresses'),
            intent_id=result.get('intent_id'),
        )


class SubmitBscPayrollAdmin(graphene.Mutation):
    """The business signature over the batch — rebuilt server-side from the
    integer params, so tampered calldata simply fails signature recovery."""

    class Arguments:
        action = graphene.String(required=True)
        shares = graphene.String(required=False)
        asset = graphene.Int(
            required=False,
            description="Echo prepare's asset. Safe to take from the client: it "
                        "goes into the rebuilt calls the business signed, so a "
                        "different pool fails signature recovery.")
        delegate_address = graphene.String(required=False)
        delegate_addresses = graphene.List(graphene.String, required=False)
        allowed = graphene.Boolean(required=False)
        nonce = graphene.String(required=True, description="Delegate intent nonce (nonces())")
        deadline = graphene.String(required=True, description="Unix seconds")
        intent_signature = graphene.String(required=True, description="65-byte r‖s‖v hex")
        authorization = BscPayrollAuthorizationInput(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    transaction_hash = graphene.String()

    def mutate(self, info, action, nonce, deadline, intent_signature,
               shares=None, asset=None, delegate_address='',
               delegate_addresses=None, allowed=True, authorization=None):
        from . import bsc_flow

        jwt_ctx = get_jwt_business_context_with_validation(
            info, required_permission='send_funds')
        if not jwt_ctx:
            return SubmitBscPayrollAdmin(success=False, error='permission_denied')
        result = bsc_flow.submit_bsc_payroll_admin(
            info.context.user, jwt_ctx, action, nonce, deadline,
            intent_signature, authorization=authorization, shares=shares,
            asset=int(asset or 0),
            delegate_address=delegate_address or '',
            delegate_addresses=delegate_addresses, allowed=bool(allowed))
        return SubmitBscPayrollAdmin(
            success=result.get('success', False),
            error=result.get('error'),
            authorization_required=result.get('authorization_required', False),
            transaction_hash=result.get('transaction_hash'),
        )


class PrepareBscPayrollPayout(graphene.Mutation):
    """Step 1 of a BSC payout: gates + eligibility branch server-side,
    stores the exact Payout struct on the item, returns the EIP-712 digest
    the executing delegate signs with their OWN personal EVM key."""

    class Arguments:
        payroll_item_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    digest = graphene.String()
    deadline = graphene.Int()
    redeem_to_usdt = graphene.Boolean()

    def mutate(self, info, payroll_item_id):
        from . import bsc_flow

        jwt_ctx = get_jwt_business_context_with_validation(
            info, required_permission='send_funds')
        if not jwt_ctx:
            return PrepareBscPayrollPayout(success=False, error='permission_denied')
        item = PayrollItem.objects.filter(
            internal_id=payroll_item_id, deleted_at__isnull=True,
        ).select_related('run__business', 'recipient_user', 'recipient_account').first()
        if not item:
            return PrepareBscPayrollPayout(success=False, error='item_not_found')
        result = bsc_flow.prepare_bsc_payroll_payout(info.context.user, jwt_ctx, item)
        if not result.get('success'):
            return PrepareBscPayrollPayout(success=False, error=result.get('error'))
        return PrepareBscPayrollPayout(
            success=True,
            digest=result['digest'],
            deadline=result['deadline'],
            redeem_to_usdt=result['redeem_to_usdt'],
        )


class SubmitBscPayrollPayout(graphene.Mutation):
    """Step 2: the delegate's signature over the STORED Payout. The server
    recovers the signer, re-checks the on-chain allowlist, and broadcasts
    payout() as a plain KMS-sponsor transaction."""

    class Arguments:
        payroll_item_id = graphene.String(required=True)
        signature = graphene.String(required=True, description="65-byte r‖s‖v hex")

    success = graphene.Boolean()
    error = graphene.String()
    transaction_hash = graphene.String()

    def mutate(self, info, payroll_item_id, signature):
        from . import bsc_flow

        jwt_ctx = get_jwt_business_context_with_validation(
            info, required_permission='send_funds')
        if not jwt_ctx:
            return SubmitBscPayrollPayout(success=False, error='permission_denied')
        item = PayrollItem.objects.filter(
            internal_id=payroll_item_id, deleted_at__isnull=True,
        ).select_related('run__business', 'recipient_user', 'recipient_account').first()
        if not item:
            return SubmitBscPayrollPayout(success=False, error='item_not_found')
        result = bsc_flow.submit_bsc_payroll_payout(
            info.context.user, jwt_ctx, item, signature)
        return SubmitBscPayrollPayout(
            success=result.get('success', False),
            error=result.get('error'),
            transaction_hash=result.get('transaction_hash'),
        )


class Mutation(graphene.ObjectType):
    create_payroll_run = CreatePayrollRun.Field()
    prepare_payroll_item_payout = PreparePayrollItemPayout.Field()
    submit_payroll_item_payout = SubmitPayrollItemPayout.Field()
    prepare_payroll_vault_funding = PreparePayrollVaultFunding.Field()
    submit_payroll_vault_funding = SubmitPayrollVaultFunding.Field()
    prepare_payroll_vault_withdrawal = PreparePayrollVaultWithdrawal.Field()
    submit_payroll_vault_withdrawal = SubmitPayrollVaultWithdrawal.Field()
    set_business_delegates = SetBusinessDelegates.Field()
    set_business_delegates_by_employee = SetBusinessDelegatesByEmployee.Field()
    # Payroll recipients mutations to be added when ready
    create_payroll_recipient = CreatePayrollRecipient.Field()
    delete_payroll_recipient = DeletePayrollRecipient.Field()
    # BSC payroll (ConfioPayrollVault)
    prepare_bsc_payroll_admin = PrepareBscPayrollAdmin.Field()
    submit_bsc_payroll_admin = SubmitBscPayrollAdmin.Field()
    prepare_bsc_payroll_payout = PrepareBscPayrollPayout.Field()
    submit_bsc_payroll_payout = SubmitBscPayrollPayout.Field()
