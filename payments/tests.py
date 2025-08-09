from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import Invoice, PaymentTransaction
from users.models import Account, Business

User = get_user_model()

class PayInvoiceTestCase(TestCase):
    def setUp(self):
        # Create test users with unique firebase_uid values
        self.merchant_user = User.objects.create_user(
            username='merchant',
            email='merchant@test.com',
            password='testpass123',
            firebase_uid='test_firebase_uid_merchant_123'
        )
        
        self.payer_user = User.objects.create_user(
            username='payer',
            email='payer@test.com',
            password='testpass123',
            firebase_uid='test_firebase_uid_payer_456'
        )
        
        # Create a business for the merchant
        self.business = Business.objects.create(
            name='Test Business',
            description='Test business description',
            category='food',
            address='Test Address'
        )
        
        # Create accounts for both users
        self.merchant_account = Account.objects.create(
            user=self.merchant_user,
            account_type='business',
            account_index=0,
            business=self.business,
            algorand_address='0x1234567890123456789012345678901234567890123456789012345678901234'
        )
        
        self.payer_account = Account.objects.create(
            user=self.payer_user,
            account_type='personal',
            account_index=0,
            algorand_address='0x9876543210987654321098765432109876543210987654321098765432109876'
        )
        
        # Create test invoice
        self.invoice = Invoice.objects.create(
            merchant_user=self.merchant_user,
            merchant_account=self.merchant_account,
            amount='10.50',
            token_type='cUSD',
            description='Test invoice',
            status='PENDING',
            expires_at=timezone.now() + timedelta(hours=24)
        )

    def test_pay_invoice_updates_statuses(self):
        """Test that PayInvoice mutation updates both invoice and payment transaction statuses"""
        from .schema import PayInvoice
        
        # Mock the GraphQL context
        class MockContext:
            def __init__(self, user, active_account_type, active_account_index):
                self.user = user
                self.active_account_type = active_account_type
                self.active_account_index = active_account_index
        
        # Mock the GraphQL info object
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext(self.payer_user, 'personal', 0)
        info = MockInfo(context)
        
        # Call the mutation
        result = PayInvoice.mutate(None, info, self.invoice.invoice_id)
        
        # Verify the result
        self.assertTrue(result.success)
        self.assertIsNotNone(result.invoice)
        self.assertIsNotNone(result.payment_transaction)
        
        # Refresh from database
        self.invoice.refresh_from_db()
        payment_transaction = PaymentTransaction.objects.get(id=result.payment_transaction.id)
        
        # Verify invoice status
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.paid_by_user, self.payer_user)
        self.assertIsNotNone(self.invoice.paid_at)
        
        # Verify payment transaction status
        self.assertEqual(payment_transaction.status, 'CONFIRMED')
        self.assertEqual(payment_transaction.payer_user, self.payer_user)
        self.assertEqual(payment_transaction.merchant_user, self.merchant_user)
        self.assertEqual(payment_transaction.amount, '10.50')
        self.assertEqual(payment_transaction.token_type, 'cUSD')
        self.assertEqual(payment_transaction.description, 'Test invoice')
        self.assertIsNotNone(payment_transaction.transaction_hash)
        self.assertEqual(payment_transaction.invoice, self.invoice)
