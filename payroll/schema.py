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

from security.utils import graphql_require_kyc, graphql_require_aml
from security.utils import check_kyc_required, perform_aml_check
from send.validators import validate_transaction_amount
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account, Business
from .models import PayrollRun, PayrollItem, PayrollRecipient
from blockchain.payroll_transaction_builder import PayrollTransactionBuilder


DECIMAL_QUANT = Decimal('0.000001')  # 6 decimals for ASA amounts


class PayrollItemType(DjangoObjectType):
    class Meta:
        model = PayrollItem
        fields = (
            'id',
            'item_id',
            'run',
            'recipient_user',
            'recipient_account',
            'token_type',
            'net_amount',
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
        token_type = graphene.String(required=False, default_value='CUSD')
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
    def mutate(cls, root, info, items, token_type='CUSD', period_seconds=None, cap_amount=None, scheduled_at=None):
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

        normalized_token = 'CUSD' if str(token_type).upper() == 'CUSD' else str(token_type).upper()

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
                    if not account or not account.algorand_address:
                        raise ValueError("Recipient account invalid or missing Algorand address")

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
        payroll_item_id = graphene.String(required=True, description="Payroll item_id to prepare payout for")
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
            item = PayrollItem.objects.select_related('run', 'recipient_account', 'recipient_user').get(item_id=payroll_item_id, deleted_at__isnull=True)
        except PayrollItem.DoesNotExist:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["Payroll item not found"])

        # Ensure item belongs to a business the user can operate on
        if item.run.business_id not in allowed_business_ids:
            return PreparePayrollItemPayout(item=None, run=None, success=False, errors=["No access to this payroll item"])

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
                payroll_item_id=item.item_id,
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
        payroll_item_id = graphene.String(required=True, description="Payroll item_id to submit payout for")
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
            item = PayrollItem.objects.select_related('run').get(item_id=payroll_item_id, deleted_at__isnull=True)
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
                confirm_payroll_item_payout.delay(item.item_id, tx_hash)
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
            tx_id = algod_client.send_raw_transaction(combined_b64)
            tx_hash = tx_id if isinstance(tx_id, str) else tx_id.get('txId') if isinstance(tx_id, dict) else None
            return SubmitPayrollVaultFunding(success=True, errors=None, transaction_hash=tx_hash)
        except Exception as e:
            msg = str(e)
            friendly = None
            if "logic eval error" in msg and ("fund" in msg or "vault" in msg or "balance" in msg):
                friendly = "Saldo insuficiente o rechazo del contrato al fondear la bóveda. Verifica el monto y vuelve a intentar."
            return SubmitPayrollVaultFunding(success=False, errors=[friendly or f"Broadcast failed: {e}"], transaction_hash=None)


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
                tx_id = algod_client.send_raw_transaction(stx_b64)
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

            txn = builder.build_set_business_delegates(
                business_account=business_account,
                add=list(add_set),
                remove=list(remove_set),
                suggested_params=sp,
            )
            unsigned_b64 = algo_encoding.msgpack_encode(txn)
        except Exception as e:
            try:
                cls.logger.exception("[Payroll] set_business_delegates_by_employee build failed biz=%s add=%s remove=%s", business_account, add_set, remove_set)
            except Exception:
                pass
            return SetBusinessDelegatesByEmployee(success=False, errors=[f"Build failed: {e}"], unsigned_transaction_b64=None, transaction_hash=None)

        if signed_transaction:
            try:
                stx_str = str(signed_transaction or "").strip()
                stx_str = stx_str.replace('-', '+').replace('_', '/')
                if len(stx_str) % 4 != 0:
                    stx_str = stx_str + ('=' * ((4 - (len(stx_str) % 4)) % 4))
                stx_bytes = base64.b64decode(stx_str)
            except Exception:
                return SetBusinessDelegatesByEmployee(success=False, errors=["Invalid base64 transaction"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

            try:
                algod_client = builder.algod_client
                stx_b64 = base64.b64encode(stx_bytes).decode('utf-8')
                tx_id = algod_client.send_raw_transaction(stx_b64)
                try:
                    cls.logger.info("[Payroll] set_business_delegates_by_employee broadcast ok tx_id=%s biz=%s add=%s remove=%s", tx_id, business_account, add_set, remove_set)
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

                return SetBusinessDelegatesByEmployee(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=tx_id)
            except Exception as e:
                try:
                    cls.logger.exception("[Payroll] set_business_delegates_by_employee broadcast failed biz=%s add=%s remove=%s err=%s", business_account, add_set, remove_set, e)
                except Exception:
                    pass
                return SetBusinessDelegatesByEmployee(success=False, errors=[f"Broadcast failed: {e}"], unsigned_transaction_b64=unsigned_b64, transaction_hash=None)

        return SetBusinessDelegatesByEmployee(success=True, errors=None, unsigned_transaction_b64=unsigned_b64, transaction_hash=None)


class Query(graphene.ObjectType):
    payroll_runs = graphene.List(PayrollRunType)
    pending_payroll_items = graphene.List(PayrollItemType, description="Pending payroll items for delegate user")
    payroll_recipients = graphene.List(PayrollRecipientType, description="Saved payroll recipients for the current business")
    payroll_delegates = graphene.List(graphene.String, description="Delegates for the current business account")
    payroll_vault_balance = graphene.Float(description="Balance of payroll vault for this business (token units)")

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

        # If caller is in a business context (owner/admin), return that business' items
        ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
            return PayrollItem.objects.filter(
                run__business_id=ctx['business_id'],
                status__in=['PENDING', 'PREPARED'],
                deleted_at__isnull=True
            ).select_related('run', 'recipient_account', 'recipient_user')

        # Otherwise, fall back to delegate view (employee of any business)
        from users.models_employee import BusinessEmployee
        biz_ids = BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).values_list('business_id', flat=True)

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
        if not biz_acct or not biz_acct.algorand_address:
            return []

        logger = logging.getLogger(__name__)
        biz_addr = biz_acct.algorand_address
        delegates = set([biz_addr])
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
                print(f"[Payroll DEBUG] Fallback: Found biz||biz box, returning [biz_addr]")
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
            from users.models import Account
            biz_id = None
            # Primary: business context (no permission requirement; delegates/owners allowed)
            ctx = get_jwt_business_context_with_validation(info, required_permission=None)
            if ctx and ctx.get('account_type') == 'business' and ctx.get('business_id'):
                emp_rec = ctx.get('employee_record')
                # Only allow owners or active delegates (even if send_funds is false)
                if emp_rec and not emp_rec.is_active:
                    return 0
                biz_id = ctx['business_id']
            # Fallback: any active business account owned by this user
            if not biz_id:
                biz_acct_owned = Account.objects.filter(
                    user=user,
                    account_type='business',
                    deleted_at__isnull=True
                ).order_by('account_index').first()
                if biz_acct_owned and biz_acct_owned.business_id:
                    biz_id = biz_acct_owned.business_id
            # Fallback: employee/delegate business
            if not biz_id:
                try:
                    from users.models_employee import BusinessEmployee
                    emp = BusinessEmployee.objects.filter(
                        user=user,
                        is_active=True,
                        deleted_at__isnull=True
                    ).order_by('business_id').first()
                    if emp:
                        biz_id = emp.business_id
                except Exception:
                    biz_id = None
            if not biz_id:
                return 0
            biz_acct = Account.objects.filter(
                business_id=biz_id,
                account_type='business',
                deleted_at__isnull=True
            ).order_by('account_index').first()
            if not biz_acct or not biz_acct.algorand_address:
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


class Mutation(graphene.ObjectType):
    create_payroll_run = CreatePayrollRun.Field()
    prepare_payroll_item_payout = PreparePayrollItemPayout.Field()
    submit_payroll_item_payout = SubmitPayrollItemPayout.Field()
    prepare_payroll_vault_funding = PreparePayrollVaultFunding.Field()
    submit_payroll_vault_funding = SubmitPayrollVaultFunding.Field()
    set_business_delegates = SetBusinessDelegates.Field()
    set_business_delegates_by_employee = SetBusinessDelegatesByEmployee.Field()
    # Payroll recipients mutations to be added when ready
    create_payroll_recipient = CreatePayrollRecipient.Field()
    delete_payroll_recipient = DeletePayrollRecipient.Field()
