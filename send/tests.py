from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import SendTransaction
from users.models import Account

User = get_user_model()

class CreateSendTransactionTestCase(TestCase):
    def setUp(self):
        # Create test users with unique firebase_uid values
        self.sender_user = User.objects.create_user(
            username='sender',
            email='sender@test.com',
            password='testpass123',
            firebase_uid='test_firebase_uid_sender_123'
        )
        
        self.recipient_user = User.objects.create_user(
            username='recipient',
            email='recipient@test.com',
            password='testpass123',
            firebase_uid='test_firebase_uid_recipient_456'
        )
        
        # Create accounts for both users
        self.sender_account = Account.objects.create(
            user=self.sender_user,
            account_type='personal',
            account_index=0,
            sui_address='0x1234567890123456789012345678901234567890123456789012345678901234'
        )
        
        self.recipient_account = Account.objects.create(
            user=self.recipient_user,
            account_type='personal',
            account_index=0,
            sui_address='0x9876543210987654321098765432109876543210987654321098765432109876'
        )

    def test_create_send_transaction_updates_status(self):
        """Test that CreateSendTransaction mutation updates send transaction status correctly"""
        from .schema import CreateSendTransaction
        
        # Mock the GraphQL info object
        class MockContext:
            def __init__(self, user, active_account_type, active_account_index):
                self.user = user
                self.active_account_type = active_account_type
                self.active_account_index = active_account_index
        
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext(self.sender_user, 'personal', 0)
        info = MockInfo(context)
        
        # Create input object
        class MockInput:
            def __init__(self, recipient_address, amount, token_type, memo):
                self.recipient_address = recipient_address
                self.amount = amount
                self.token_type = token_type
                self.memo = memo
        
        input_data = MockInput(
            recipient_address=self.recipient_account.sui_address,
            amount='25.00',
            token_type='cUSD',
            memo='Test send transaction'
        )
        
        # Call the mutation
        result = CreateSendTransaction.mutate(None, info, input_data)
        
        # Verify the result
        self.assertTrue(result.success)
        self.assertIsNotNone(result.send_transaction)
        
        # Verify the send transaction was created correctly
        send_transaction = SendTransaction.objects.get(id=result.send_transaction.id)
        self.assertEqual(send_transaction.status, 'CONFIRMED')
        self.assertEqual(send_transaction.sender_user, self.sender_user)
        self.assertEqual(send_transaction.recipient_user, self.recipient_user)
        self.assertEqual(send_transaction.amount, '25.00')
        self.assertEqual(send_transaction.token_type, 'cUSD')
        self.assertEqual(send_transaction.memo, 'Test send transaction')
        self.assertIsNotNone(send_transaction.transaction_hash)
        self.assertTrue(send_transaction.transaction_hash.startswith('test_send_tx_'))
