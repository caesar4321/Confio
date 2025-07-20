import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
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
            'merchant_user',
            'payer_account',
            'merchant_account',
            'payer_address',
            'merchant_address', 
            'amount', 
            'token_type', 
            'description', 
            'status', 
            'transaction_hash',
            'error_message',
            'created_at', 
            'updated_at'
        )

class InvoiceType(DjangoObjectType):
    """GraphQL type for Invoice model"""
    class Meta:
        model = Invoice
        fields = (
            'id',
            'invoice_id',
            'merchant_user',
            'merchant_account',
            'amount',
            'token_type',
            'description',
            'status',
            'paid_by_user',
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

            # Create the invoice
            invoice = Invoice.objects.create(
                merchant_user=user,
                merchant_account=active_account,
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

    invoice = graphene.Field(InvoiceType)
    payment_transaction = graphene.Field(PaymentTransactionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, invoice_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PayInvoice(
                invoice=None,
                payment_transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get the invoice
            invoice = Invoice.objects.get(
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
            if invoice.merchant_user == user:
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

            # Create the payment transaction
            payment_transaction = PaymentTransaction.objects.create(
                payer_user=user,
                merchant_user=invoice.merchant_user,
                payer_account=payer_account,
                merchant_account=invoice.merchant_account,
                payer_address=payer_account.sui_address,
                merchant_address=invoice.merchant_account.sui_address,
                amount=invoice.amount,
                token_type=invoice.token_type,
                description=invoice.description,
                status='PENDING',
                invoice=invoice
            )

            # Update invoice
            invoice.status = 'PAID'
            invoice.paid_by_user = user
            invoice.paid_at = timezone.now()
            invoice.save()

            # TODO: Implement sponsored transaction logic here
            # This will be handled by a background task
            # TEMPORARY: For testing, we're marking as PAID immediately
            # In production, this would wait for blockchain confirmation
            
            # TEMPORARY: Mark payment transaction as CONFIRMED for testing
            # This ensures the UI shows the correct status
            payment_transaction.status = 'CONFIRMED'
            payment_transaction.transaction_hash = f"test_pay_tx_{payment_transaction.id}_{int(timezone.now().timestamp())}"
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
    """Query definitions for invoices"""
    invoice = graphene.Field(InvoiceType, invoice_id=graphene.String())
    invoices = graphene.List(InvoiceType)

    def resolve_invoice(self, info, invoice_id):
        # Anyone can view an invoice by ID
        try:
            return Invoice.objects.get(invoice_id=invoice_id)
        except Invoice.DoesNotExist:
            return None

    def resolve_invoices(self, info):
        # Users can only view their own invoices
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        return Invoice.objects.filter(
            merchant_user=user
        )

class Mutation(graphene.ObjectType):
    """Mutation definitions for invoices"""
    create_invoice = CreateInvoice.Field()
    get_invoice = GetInvoice.Field()
    pay_invoice = PayInvoice.Field() 