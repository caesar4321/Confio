import graphene
from graphene_django import DjangoObjectType
import json
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db.models import F
from .models import Invoice, PaymentTransaction
from send.validators import validate_transaction_amount
from django.conf import settings
from security.utils import graphql_require_kyc, graphql_require_aml

class InvoiceInput(graphene.InputObjectType):
    """Input type for creating a new invoice"""
    amount = graphene.String(required=True, description="Amount to request (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to request (e.g., 'cUSD', 'CONFIO')")
    description = graphene.String(description="Optional description for the invoice")
    expires_in_hours = graphene.Int(description="Hours until expiration (default: 24)")

class PaymentTransactionType(DjangoObjectType):
    """GraphQL type for PaymentTransaction model"""
    # Explicitly declare to force using our resolver instead of default ORM mapping
    blockchain_data = graphene.JSONString()
    class Meta:
        model = PaymentTransaction
        fields = (
            'id',
            'internal_id',
            'payer_user', 
            'merchant_account_user',
            'payer_account',
            'merchant_account',
            'payer_business',
            'merchant_business',
            'payer_type',
            'merchant_type',
            'payer_display_name',
            'merchant_display_name',
            'payer_phone',
            'payer_address',
            'merchant_address', 
            'amount', 
            'token_type', 
            'description', 
            'status', 
            'transaction_hash',
            'error_message',
            'created_at', 
            'updated_at',
            'invoice'
        )

    # Return ephemeral override when present to include transactions in mutation response
    def resolve_blockchain_data(self, info):
        try:
            # 1) If the instance already has the response-time dict with transactions, return it
            if isinstance(self.blockchain_data, dict) and 'transactions' in self.blockchain_data:
                logger.debug(f"resolve_blockchain_data: using instance data for {self.internal_id} (transactions present)")
                return self.blockchain_data

            # 2) Otherwise, try cross-request override cache
            if self.internal_id:
                key = f"ptx:override:{self.internal_id}"
                override = cache.get(key)
                if override is not None:
                    logger.debug(f"resolve_blockchain_data: using override for {self.internal_id} with keys: {list(override.keys())}")
                    return override
        except Exception as e:
            logger.error(f"Error resolving blockchain_data for {self.internal_id}: {e}")
            pass
        try:
            # Log fallback case for diagnostics
            truncated = str(self.blockchain_data)
            if isinstance(self.blockchain_data, (dict, list)):
                logger.debug(f"resolve_blockchain_data: fallback dict/list for {self.internal_id}")
            else:
                logger.debug(f"resolve_blockchain_data: fallback string for {self.internal_id}: {truncated[:120]}...")
        except Exception as e:
            logger.error(f"Error logging fallback blockchain_data for {self.internal_id}: {e}")
            pass
        return self.blockchain_data

class InvoiceType(DjangoObjectType):
    """GraphQL type for Invoice model"""
    class Meta:
        model = Invoice
        fields = (
            'id',
            'invoice_id',
            'created_by_user',
            'merchant_account',
            'paid_by_user',
            'merchant_business',
            'merchant_type',
            'merchant_display_name',
            'paid_by_business',
            'amount',
            'token_type',
            'description',
            'status',
            'paid_at',
            'expires_at',
            'created_at',
            'updated_at'
        )
    
    # Add custom fields
    is_expired = graphene.Boolean()
    qr_code_data = graphene.String()
    payment_transactions = graphene.List(PaymentTransactionType)
    
    def resolve_is_expired(self, info):
        """Resolve is_expired property"""
        return self.is_expired
    
    def resolve_qr_code_data(self, info):
        """Resolve qr_code_data property"""
        return self.qr_code_data
    
    def resolve_payment_transactions(self, info):
        """Resolve payment transactions for this invoice"""
        return self.payment_transactions.all()

class CreateInvoice(graphene.Mutation):
    """Mutation for creating a new invoice"""
    class Arguments:
        input = InvoiceInput(required=True)

    invoice = graphene.Field(InvoiceType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('accept_payments')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateInvoice(
                invoice=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Validate the amount
            validate_transaction_amount(input.amount)

            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='accept_payments')
            if not jwt_context:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["No access or permission to create invoices"]
                )
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            # Get the user's active account using JWT context
            from users.models import Account
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT (ignore index; employees may have index mismatch)
                active_account = Account.objects.filter(
                    account_type='business',
                    business_id=business_id
                ).order_by('account_index').first()
            else:
                # For personal accounts
                active_account = user.accounts.filter(
                    account_type=account_type,
                    account_index=account_index
                ).first()
            
            if not active_account:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["Cuenta activa no encontrada"]
                )

            # Set expiration time (default 24 hours)
            expires_in_hours = input.expires_in_hours or 24
            expires_at = timezone.now() + timedelta(hours=expires_in_hours)

            # Only businesses can create invoices
            if account_type != 'business' or not business_id:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["Solo las cuentas de negocio pueden crear facturas"]
                )
            
            # Get the business directly using the business_id from JWT
            from users.models import Business
            merchant_business = Business.objects.filter(id=business_id).first()
            if not merchant_business:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["Negocio no encontrado"]
                )
            merchant_type = 'business'
            merchant_display_name = merchant_business.name

            # Normalize token type to canonical uppercase for DB/network
            normalized_token = 'CUSD' if str(input.token_type).upper() == 'CUSD' else str(input.token_type).upper()

            # Create the invoice
            invoice = Invoice.objects.create(
                created_by_user=user,
                merchant_account=active_account,
                merchant_business=merchant_business,
                merchant_type=merchant_type,
                merchant_display_name=merchant_display_name,
                amount=input.amount,
                token_type=normalized_token,
                description=input.description or '',
                expires_at=expires_at,
                status='PENDING'
            )
            
            # Log activity if user is an employee
            from users.models_employee import BusinessEmployee, EmployeeActivityLog
            employee_record = BusinessEmployee.objects.filter(
                business=merchant_business,
                user=user,
                is_active=True
            ).first()
            
            if employee_record:
                EmployeeActivityLog.log_activity(
                    business=merchant_business,
                    employee=user,
                    action='invoice_created',
                    request=info.context,
                    invoice_id=invoice.invoice_id,
                    amount=input.amount,
                    details={
                        'token_type': input.token_type,
                        'description': input.description or ''
                    }
                )

            return CreateInvoice(
                invoice=invoice,
                success=True,
                errors=None
            )

        except ValidationError as e:
            return CreateInvoice(
                invoice=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return CreateInvoice(
                invoice=None,
                success=False,
                errors=[str(e)]
            )

class GetInvoice(graphene.Mutation):
    """Mutation for getting an invoice by ID"""
    class Arguments:
        invoice_id = graphene.String(required=True)

    invoice = graphene.Field(InvoiceType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, invoice_id):
        try:
            invoice = Invoice.objects.get(
                invoice_id=invoice_id,
                status='PENDING'
            )
            
            # Check if expired
            if invoice.is_expired:
                invoice.status = 'EXPIRED'
                invoice.save()
                return GetInvoice(
                    invoice=None,
                    success=False,
                    errors=["Invoice has expired"]
                )

            return GetInvoice(
                invoice=invoice,
                success=True,
                errors=None
            )

        except Invoice.DoesNotExist:
            return GetInvoice(
                invoice=None,
                success=False,
                errors=["Invoice not found"]
            )
        except Exception as e:
            return GetInvoice(
                invoice=None,
                success=False,
                errors=[str(e)]
            )

class PayInvoice(graphene.Mutation):
    """Mutation for paying an invoice"""
    class Arguments:
        invoice_id = graphene.String(required=True)
        idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate payments")

    invoice = graphene.Field(InvoiceType)
    payment_transaction = graphene.Field(PaymentTransactionType)
    # Transient fields to carry signing payload back to client without persisting
    transactions = graphene.JSONString(description="Array of 4 transactions (sponsor pre-signed, user-signed required)")
    group_id = graphene.String()
    gross_amount = graphene.Float()
    net_amount = graphene.Float()
    fee_amount = graphene.Float()
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, invoice_id, idempotency_key=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PayInvoice(
                invoice=None,
                payment_transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        # Debug logging
        logger.debug(f"PayInvoice: User {user.id} attempting to pay invoice {invoice_id}")
        logger.debug(f"PayInvoice: Idempotency key: {idempotency_key or 'NOT PROVIDED'}")

        # Use atomic transaction with SELECT FOR UPDATE to prevent race conditions
        try:
            with transaction.atomic():
                # Get the invoice with row-level locking
                invoice = Invoice.objects.select_for_update().get(
                    invoice_id=invoice_id,
                    status='PENDING'
                )
                
                # Check if expired
                if invoice.is_expired:
                    invoice.status = 'EXPIRED'
                    invoice.save()
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Invoice has expired"]
                    )

                # Check if user is trying to pay their own invoice
                if invoice.created_by_user == user:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Cannot pay your own invoice"]
                    )

                # Get JWT context with validation and permission check
                from users.jwt_context import get_jwt_business_context_with_validation
                jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
                if not jwt_context:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["No access or permission to pay invoices"]
                    )
                    
                account_type = jwt_context['account_type']
                account_index = jwt_context['account_index']
                business_id = jwt_context.get('business_id')

                # After locking the invoice row, re-check idempotency to avoid race
                if idempotency_key:
                    logger.debug(f"PayInvoice: Post-lock idempotency check for key: {idempotency_key}")
                    existing_payment = PaymentTransaction.objects.filter(
                        invoice=invoice,
                        payer_user=user,
                        idempotency_key=idempotency_key,
                        deleted_at__isnull=True
                    ).first()
                    if existing_payment:
                        logger.debug(f"PayInvoice: Found existing payment {existing_payment.id} after lock, returning it")
                        return PayInvoice(
                            invoice=existing_payment.invoice,
                            payment_transaction=existing_payment,
                            success=True,
                            errors=None
                        )
                
                # Debug: Log the JWT account context being used
                logger.debug(f"PayInvoice - JWT account context: {account_type}_{account_index}, business_id={business_id}")
                logger.debug(f"PayInvoice - User ID: {user.id}")
                logger.debug(f"PayInvoice - Available accounts for user: {list(user.accounts.values_list('account_type', 'account_index', 'algorand_address'))}")
                
                # Get the payer's active account using JWT context
                if account_type == 'business' and business_id:
                    # For business accounts, find by business_id from JWT (ignore index; employees may have index mismatch)
                    from users.models import Account
                    payer_account = Account.objects.filter(
                        account_type='business',
                        business_id=business_id
                    ).order_by('account_index').first()
                else:
                    # For personal accounts
                    payer_account = user.accounts.filter(
                        account_type=account_type,
                        account_index=account_index
                    ).first()
                
                logger.debug(f"PayInvoice - Found payer account: {payer_account}")
                
                if not payer_account or not payer_account.algorand_address:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Payer account not found or missing Algorand address"]
                    )

                # Check if merchant has Algorand address
                if not invoice.merchant_account.algorand_address:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Merchant account missing Algorand address"]
                    )

                # Determine payer type and business details
                payer_business = None
                payer_type = 'user'  # default to personal
                payer_display_name = f"{user.first_name} {user.last_name}".strip()
                # Fallback to username if no first/last name
                if not payer_display_name:
                    payer_display_name = user.username or f"User {user.id}"
                payer_phone = f"{user.phone_country}{user.phone_number}" if user.phone_country and user.phone_number else ""
                
                if payer_account.account_type == 'business' and payer_account.business:
                    payer_business = payer_account.business
                    payer_type = 'business'
                    payer_display_name = payer_account.business.name
                
                # Determine merchant type and business details  
                # Merchants are ALWAYS businesses for payments
                merchant_business = invoice.merchant_business or invoice.merchant_account.business
                merchant_type = 'business'  # Always business for payments
                merchant_display_name = merchant_business.name if merchant_business else ''

                # Generate a temporary unique transaction hash to avoid constraint violations
                import time
                import uuid
                microsecond_timestamp = int(time.time() * 1000000)
                unique_id = str(uuid.uuid4())[:8]
                temp_transaction_hash = f"temp_{invoice.invoice_id}_{microsecond_timestamp}_{unique_id}"
                
                # Create the payment transaction (normalize token type to backend canonical form)
                normalized_token_type = 'CUSD' if str(invoice.token_type).upper() == 'CUSD' else str(invoice.token_type).upper()
                payment_transaction = PaymentTransaction.objects.create(
                    payer_user=user,
                    payer_account=payer_account,
                    merchant_account=invoice.merchant_account,
                    payer_business=payer_business,
                    merchant_business=merchant_business,
                    merchant_account_user=invoice.created_by_user,
                    payer_type=payer_type,
                    merchant_type=merchant_type,
                    payer_display_name=payer_display_name,
                    merchant_display_name=merchant_display_name,
                    payer_phone=payer_phone,
                    payer_address=payer_account.algorand_address,
                    merchant_address=invoice.merchant_account.algorand_address,
                    amount=invoice.amount,
                    token_type=normalized_token_type,
                    description=invoice.description,
                    status='PENDING',
                    transaction_hash=temp_transaction_hash,  # Set temporary hash to avoid unique constraint violation
                    invoice=invoice,
                    idempotency_key=idempotency_key
                )

                # Don't mark invoice as PAID yet - wait for blockchain confirmation
                # Store the payment info for later use
                invoice_payment_info = {
                    'paid_by_user': user,
                    'paid_by_business': payer_business,
                    'paid_at': timezone.now()
                }

                # Execute blockchain payment through sponsored payment contract
                # The recipient business is already determined from the invoice
                blockchain_success = False
                blockchain_tx_id = None
                blockchain_error = None
                
                try:
                    logger.info(f"PayInvoice: Attempting to create blockchain transactions for payment {payment_transaction.internal_id}")
                    logger.debug(f"PayInvoice: Merchant business: {merchant_business.id if merchant_business else 'None'}")
                    logger.debug(f"PayInvoice: Amount: {invoice.amount} {invoice.token_type}")
                    
                    from blockchain.payment_mutations import CreateSponsoredPaymentMutation, SubmitSponsoredPaymentMutation
                    from blockchain.algorand_utils import create_payment_transactions
                    from decimal import Decimal
                    import json
                    
                    # Convert amount to proper format
                    amount_decimal = Decimal(str(invoice.amount))
                    
                    # Determine asset type (normalize to canonical uppercase)
                    asset_type = 'CUSD' if str(invoice.token_type).upper() == 'CUSD' else str(invoice.token_type).upper()
                    
                    # Create sponsored payment transaction
                    # Note: The recipient business is already in JWT context
                    # We need to temporarily inject the merchant business ID into context
                    request = info.context
                    original_meta = request.META.copy()
                    
                    # Add recipient business ID to JWT context
                    # This is a temporary approach - in production, the JWT should already contain this
                    request.META['HTTP_X_RECIPIENT_BUSINESS_ID'] = str(merchant_business.id) if merchant_business else ''
                    
                    logger.debug(f"PayInvoice: Creating sponsored payment mutation...")
                    
                    # Create the sponsored payment
                    create_result = CreateSponsoredPaymentMutation.mutate(
                        root=None,
                        info=info,
                        amount=float(amount_decimal),
                        asset_type=asset_type,
                        payment_id=payment_transaction.internal_id,
                        note=f"Payment for invoice {invoice.invoice_id}",
                        create_receipt=True
                    )
                    
                    # Restore original META
                    request.META = original_meta
                    
                    logger.debug(f"PayInvoice: Create result - success: {create_result.success}, has transactions: {bool(create_result.transactions)}")
                    if not create_result.success:
                        logger.debug(f"PayInvoice: Create error: {create_result.error}")
                    
                    if create_result.success and create_result.transactions:
                        logger.debug(f"PayInvoice: Created blockchain payment transactions")
                        
                        # Mark as pending blockchain confirmation
                        payment_transaction.status = 'PENDING_BLOCKCHAIN'
                        
                        # Set a temporary transaction hash (will be replaced with real one after blockchain confirmation)
                        import time
                        import uuid
                        microsecond_timestamp = int(time.time() * 1000000)
                        unique_id = str(uuid.uuid4())[:8]
                        payment_transaction.transaction_hash = f"pending_blockchain_{payment_transaction.id}_{microsecond_timestamp}_{unique_id}"
                        
                        # Solution 1: Server creates ALL 4 transactions at once, sends to client
                        # No need to store transactions in DB - client will sign and return them immediately
                        all_txns = json.loads(create_result.transactions) if isinstance(create_result.transactions, str) else create_result.transactions
                        
                        # Save minimal tracking info to DB (no transactions persisted)
                        payment_transaction.blockchain_data = {
                            'payment_id': payment_transaction.internal_id,
                            'status': 'pending_signature'
                        }
                        # Persist status + placeholder hash so merchants can react immediately
                        payment_transaction.save(update_fields=['status', 'transaction_hash', 'blockchain_data', 'updated_at'])

                        # After saving, attach full transactions ONLY on the response instance (not persisted)
                        payment_transaction.blockchain_data = {
                            'transactions': all_txns,
                            'group_id': create_result.group_id,
                            'gross_amount': float(create_result.gross_amount),
                            'net_amount': float(create_result.net_amount),
                            'fee_amount': float(create_result.fee_amount),
                        }

                        # Prepare transient signing payload (do not persist) and cache override for immediate response
                        response_transactions = all_txns
                        response_group_id = create_result.group_id
                        response_gross = float(create_result.gross_amount)
                        response_net = float(create_result.net_amount)
                        response_fee = float(create_result.fee_amount)
                        cache.set(
                            f"ptx:override:{payment_transaction.internal_id}",
                            {
                                'transactions': response_transactions,
                                'group_id': response_group_id,
                                'gross_amount': response_gross,
                                'net_amount': response_net,
                                'fee_amount': response_fee,
                            },
                            timeout=300
                        )
                        
                        # DON'T mark invoice as PAID yet - wait for blockchain confirmation
                        # The invoice will be marked as PAID in SubmitSponsoredPayment mutation
                        print(f"PayInvoice: Payment created with blockchain data, waiting for client signing")
                        
                        blockchain_success = True
                        print(f"PayInvoice: Payment ready for client signing")
                    else:
                        blockchain_error = create_result.error or "Failed to create blockchain payment"
                        print(f"PayInvoice: Blockchain payment creation failed: {blockchain_error}")
                        
                except Exception as e:
                    blockchain_error = str(e)
                    print(f"PayInvoice: Blockchain payment error: {blockchain_error}")
                    import traceback
                    traceback.print_exc()
                
                # If blockchain was attempted but failed, the entire payment should fail
                if not blockchain_success:
                    print(f"PayInvoice: Blockchain payment failed, rolling back")
                    # Delete the payment transaction - it failed
                    payment_transaction.delete()
                    # Don't mark invoice as paid
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=[f"Blockchain payment failed: {blockchain_error}"]
                    )
                
                # DON'T create notifications here - wait for blockchain confirmation
                # Notifications will be created in SubmitSponsoredPayment after blockchain success
                print(f"PayInvoice: Skipping notifications - will be sent after blockchain confirmation")
                
                # Log activity if merchant is an employee accepting payment
                from users.models_employee import BusinessEmployee, EmployeeActivityLog
                
                # Check if the merchant account user is an employee
                if invoice.merchant_account.user == invoice.created_by_user:
                    # Owner accepting their own payment, check if they're acting as an employee
                    employee_record = BusinessEmployee.objects.filter(
                        business=merchant_business,
                        user=invoice.created_by_user,
                        is_active=True
                    ).first()
                    
                    if employee_record:
                        EmployeeActivityLog.log_activity(
                            business=merchant_business,
                            employee=invoice.created_by_user,
                            action='payment_accepted',
                            request=info.context,
                            invoice_id=invoice.invoice_id,
                            transaction_id=payment_transaction.transaction_hash,
                            amount=invoice.amount,
                            details={
                                'token_type': invoice.token_type,
                                'payer': payer_display_name,
                                'payment_type': 'digital'
                            }
                        )

                # Return transient transactions alongside DB object
                return PayInvoice(
                    invoice=invoice,
                    payment_transaction=payment_transaction,
                    transactions=response_transactions if blockchain_success else None,
                    group_id=response_group_id if blockchain_success else None,
                    gross_amount=response_gross if blockchain_success else None,
                    net_amount=response_net if blockchain_success else None,
                    fee_amount=response_fee if blockchain_success else None,
                    success=True,
                    errors=None
                )

        except Invoice.DoesNotExist:
            return PayInvoice(
                invoice=None,
                payment_transaction=None,
                success=False,
                errors=["Invoice not found"]
            )
        except Exception as e:
            return PayInvoice(
                invoice=None,
                payment_transaction=None,
                success=False,
                errors=[str(e)]
            )

class Query(graphene.ObjectType):
    """Query definitions for invoices and payment transactions"""
    invoice = graphene.Field(InvoiceType, invoice_id=graphene.String())
    invoices = graphene.List(InvoiceType)
    payment_transactions = graphene.List(PaymentTransactionType)
    payment_transaction = graphene.Field(PaymentTransactionType, id=graphene.ID(required=True))
    payment_transactions_with_friend = graphene.List(
        PaymentTransactionType,
        friend_user_id=graphene.ID(required=True),
        limit=graphene.Int()
    )

    def resolve_invoice(self, info, invoice_id):
        # Anyone can view an invoice by ID
        try:
            return Invoice.objects.get(invoice_id=invoice_id)
        except Invoice.DoesNotExist:
            return None

    def resolve_invoices(self, info):
        # Users can only view their own invoices for the active account
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Filter by user and active account
        return Invoice.objects.filter(
            created_by_user=user,
            merchant_account__account_type=account_type,
            merchant_account__account_index=account_index
        )

    def resolve_payment_transactions(self, info):
        """Resolve all payment transactions for the authenticated user"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        from django.db import models
        return PaymentTransaction.objects.filter(
            models.Q(payer_user=user) | models.Q(merchant_account_user=user)
        ).order_by('-created_at')

    def resolve_payment_transaction(self, info, id):
        """Resolve a single payment transaction by ID (internal_id or pk)"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        from django.db import models
        try:
            # Check internal_id (UUID) or PK
            if len(str(id)) >= 32:
                q = models.Q(internal_id=id)
            else:
                q = models.Q(id=id)

            # Ensure user is party to transaction checks
            # 1. User is payer
            # 2. User is merchant account owner
            # 3. User is employee of payer business
            # 4. User is employee of merchant business
            
            # Simple check first:
            base_q = q & (models.Q(payer_user=user) | models.Q(merchant_account_user=user))
            
            try:
                return PaymentTransaction.objects.get(base_q)
            except PaymentTransaction.DoesNotExist:
                # If simple check fails, check business permissions if applicable
                # (This can be expanded if needed, for now start with direct association)
                raise
                
        except (PaymentTransaction.DoesNotExist, ValueError):
            return None


    def resolve_payment_transactions_with_friend(self, info, friend_user_id, limit=None):
        """Resolve payment transactions between current user's active account and a specific friend"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        from django.db import models
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Get the user's active account
        try:
            from users.models import Account
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT
                # This will find the business account regardless of who owns it
                user_account = Account.objects.get(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                )
            else:
                # For personal accounts
                user_account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
            
            if not user_account.algorand_address:
                return []
                
        except Account.DoesNotExist:
            return []
        
        # Get all accounts for the friend user
        friend_accounts = Account.objects.filter(user_id=friend_user_id).values_list('algorand_address', flat=True)
        friend_addresses = list(friend_accounts)
        
        if not friend_addresses:
            return []
        
        # Get transactions where either:
        # 1. Current user's account paid friend's business account
        # 2. Friend's account paid current user's business account
        queryset = PaymentTransaction.objects.filter(
            (models.Q(payer_address=user_account.algorand_address) & models.Q(merchant_address__in=friend_addresses)) |
            (models.Q(payer_address__in=friend_addresses) & models.Q(merchant_address=user_account.algorand_address))
        ).order_by('-created_at')
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

class Mutation(graphene.ObjectType):
    """Mutation definitions for invoices"""
    create_invoice = CreateInvoice.Field()
    get_invoice = GetInvoice.Field()
    pay_invoice = PayInvoice.Field() 
