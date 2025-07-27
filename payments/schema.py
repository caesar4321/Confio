import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db.models import F
from .models import Invoice, PaymentTransaction
from send.validators import validate_transaction_amount
from django.conf import settings

class InvoiceInput(graphene.InputObjectType):
    """Input type for creating a new invoice"""
    amount = graphene.String(required=True, description="Amount to request (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to request (e.g., 'cUSD', 'CONFIO')")
    description = graphene.String(description="Optional description for the invoice")
    expires_in_hours = graphene.Int(description="Hours until expiration (default: 24)")

class PaymentTransactionType(DjangoObjectType):
    """GraphQL type for PaymentTransaction model"""
    class Meta:
        model = PaymentTransaction
        fields = (
            'id',
            'payment_transaction_id',
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

            # Get the user's active account
            active_account = user.accounts.filter(
                account_type=info.context.active_account_type,
                account_index=info.context.active_account_index
            ).first()
            
            if not active_account:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["Active account not found"]
                )

            # Set expiration time (default 24 hours)
            expires_in_hours = input.expires_in_hours or 24
            expires_at = timezone.now() + timedelta(hours=expires_in_hours)

            # Only businesses can create invoices
            if active_account.account_type != 'business' or not active_account.business:
                return CreateInvoice(
                    invoice=None,
                    success=False,
                    errors=["Only business accounts can create invoices"]
                )
                
            merchant_business = active_account.business
            merchant_type = 'business'
            merchant_display_name = merchant_business.name

            # Create the invoice
            invoice = Invoice.objects.create(
                created_by_user=user,
                merchant_account=active_account,
                merchant_business=merchant_business,
                merchant_type=merchant_type,
                merchant_display_name=merchant_display_name,
                amount=input.amount,
                token_type=input.token_type,
                description=input.description or '',
                expires_at=expires_at,
                status='PENDING'
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
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
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
        print(f"PayInvoice: User {user.id} attempting to pay invoice {invoice_id}")
        print(f"PayInvoice: Idempotency key: {idempotency_key or 'NOT PROVIDED'}")

        # Use atomic transaction with SELECT FOR UPDATE to prevent race conditions
        try:
            with transaction.atomic():
                # Check for existing payment with same idempotency key
                if idempotency_key:
                    print(f"PayInvoice: Checking for existing payment with idempotency key: {idempotency_key}")
                    existing_payment = PaymentTransaction.objects.filter(
                        invoice__invoice_id=invoice_id,
                        payer_user=user,
                        idempotency_key=idempotency_key
                    ).first()
                    
                    if existing_payment:
                        print(f"PayInvoice: Found existing payment {existing_payment.id}, returning it")
                        # Return existing payment to prevent duplicate
                        return PayInvoice(
                            invoice=existing_payment.invoice,
                            payment_transaction=existing_payment,
                            success=True,
                            errors=None
                        )
                    else:
                        print(f"PayInvoice: No existing payment found, proceeding with creation")
                else:
                    print(f"PayInvoice: No idempotency key provided")
                
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

                # Debug: Log the active account context being used
                print(f"PayInvoice - Active account context: {info.context.active_account_type}_{info.context.active_account_index}")
                print(f"PayInvoice - User ID: {user.id}")
                print(f"PayInvoice - Available accounts for user: {list(user.accounts.values_list('account_type', 'account_index', 'sui_address'))}")
                
                # Get the payer's active account
                payer_account = user.accounts.filter(
                    account_type=info.context.active_account_type,
                    account_index=info.context.active_account_index
                ).first()
                
                print(f"PayInvoice - Found payer account: {payer_account}")
                
                if not payer_account or not payer_account.sui_address:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Payer account not found or missing Sui address"]
                    )

                # Check if merchant has Sui address
                if not invoice.merchant_account.sui_address:
                    return PayInvoice(
                        invoice=None,
                        payment_transaction=None,
                        success=False,
                        errors=["Merchant account missing Sui address"]
                    )

                # Determine payer type and business details
                payer_business = None
                payer_type = 'user'  # default to personal
                payer_display_name = f"{user.first_name} {user.last_name}".strip()
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

                # Create the payment transaction
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
                    payer_address=payer_account.sui_address,
                    merchant_address=invoice.merchant_account.sui_address,
                    amount=invoice.amount,
                    token_type=invoice.token_type,
                    description=invoice.description,
                    status='PENDING',
                    invoice=invoice,
                    idempotency_key=idempotency_key
                )

                # Update invoice with proper paid_by fields
                invoice.status = 'PAID'
                invoice.paid_by_user = user
                invoice.paid_by_business = payer_business  # Set if payer is business
                invoice.paid_at = timezone.now()
                invoice.save()

                # TODO: Implement sponsored transaction logic here
                # This will be handled by a background task
                # TEMPORARY: For testing, we're marking as PAID immediately
                # In production, this would wait for blockchain confirmation
                
                # TEMPORARY: Mark payment transaction as CONFIRMED for testing
                # This ensures the UI shows the correct status
                payment_transaction.status = 'CONFIRMED'
                # Generate a unique transaction hash using ID, microsecond timestamp, and UUID
                import time
                import uuid
                microsecond_timestamp = int(time.time() * 1000000)  # Microsecond precision
                unique_id = str(uuid.uuid4())[:8]  # First 8 characters of UUID
                payment_transaction.transaction_hash = f"test_pay_tx_{payment_transaction.id}_{microsecond_timestamp}_{unique_id}"
                payment_transaction.save()

                return PayInvoice(
                    invoice=invoice,
                    payment_transaction=payment_transaction,
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
    payment_transactions_by_account = graphene.List(
        PaymentTransactionType,
        account_type=graphene.String(required=True),
        account_index=graphene.Int(required=True),
        limit=graphene.Int()
    )
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
        
        # Get active account context
        account_type = getattr(info.context, 'active_account_type', 'personal')
        account_index = getattr(info.context, 'active_account_index', 0)
        
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

    def resolve_payment_transactions_by_account(self, info, account_type, account_index, limit=None):
        """Resolve payment transactions for a specific account"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        from users.models import Account
        from django.db import models
        
        # Get the account for this user
        try:
            account = user.accounts.get(
                account_type=account_type,
                account_index=account_index
            )
        except Account.DoesNotExist:
            return []
        
        # If account has no Sui address, return empty (account not set up yet)
        if not account.sui_address:
            return []
        
        # Filter transactions by account's Sui address
        queryset = PaymentTransaction.objects.filter(
            models.Q(payer_address=account.sui_address) | 
            models.Q(merchant_address=account.sui_address)
        ).order_by('-created_at')
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

    def resolve_payment_transactions_with_friend(self, info, friend_user_id, limit=None):
        """Resolve payment transactions between current user's active account and a specific friend"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        from django.db import models
        
        # Get active account context
        account_type = getattr(info.context, 'active_account_type', 'personal')
        account_index = getattr(info.context, 'active_account_index', 0)
        
        # Get the user's active account
        try:
            from users.models import Account
            user_account = Account.objects.get(
                user=user,
                account_type=account_type,
                account_index=account_index
            )
            
            if not user_account.sui_address:
                return []
                
        except Account.DoesNotExist:
            return []
        
        # Get all accounts for the friend user
        friend_accounts = Account.objects.filter(user_id=friend_user_id).values_list('sui_address', flat=True)
        friend_addresses = list(friend_accounts)
        
        if not friend_addresses:
            return []
        
        # Get transactions where either:
        # 1. Current user's account paid friend's business account
        # 2. Friend's account paid current user's business account
        queryset = PaymentTransaction.objects.filter(
            (models.Q(payer_address=user_account.sui_address) & models.Q(merchant_address__in=friend_addresses)) |
            (models.Q(payer_address__in=friend_addresses) & models.Q(merchant_address=user_account.sui_address))
        ).order_by('-created_at')
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

class Mutation(graphene.ObjectType):
    """Mutation definitions for invoices"""
    create_invoice = CreateInvoice.Field()
    get_invoice = GetInvoice.Field()
    pay_invoice = PayInvoice.Field() 