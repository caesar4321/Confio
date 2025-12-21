
import os
import django
import sys
import graphene
from unittest.mock import MagicMock

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.schema import UserType
from send.schema import SendTransactionType
from payments.schema import InvoiceType
from users.models import User

class SecurityVerifier:
    def create_mock_info(self, user_id, is_authenticated=True):
        info = MagicMock()
        user = MagicMock()
        user.is_authenticated = is_authenticated
        user.id = user_id
        info.context.user = user
        return info

    def run_verification(self):
        print("CORE: Testing GraphQL Security Fixes (Updated)...")
        
        # 1. Inspect UserType fields
        print("\n1. Inspecting UserType fields...")
        user_fields = UserType._meta.fields
        
        # Check if fields exist
        has_phone = 'phone_number' in user_fields
        has_email = 'email' in user_fields
        has_masked = 'phone_number_masked' in user_fields
        
        print(f"   - phone_number field present: {has_phone}")
        print(f"   - email field present: {has_email}")
        print(f"   - phone_number_masked field present: {has_masked}")
        
        if not (has_phone and has_email):
            print("❌ FAILED: Missing required fields on UserType")
        else:
            print("   ✅ UserType has required fields")
        
        if has_masked:
            print("❌ FAILED: Masked field should have been REMOVED")
        else:
            print("   ✅ SUCCESS: Masked field removed from UserType")

        # 2. Test Resolver Logic
        print("\n2. Testing Access Control Logic...")
        
        # Test Case A: Accessing OWN data
        print("   [Case A] User 1 accessing User 1's data:")
        
        user_data_instance = MagicMock()
        user_data_instance.id = 1
        user_data_instance.phone_number = "+1234567890"
        user_data_instance.email = "test@confio.com"
        
        info_a = self.create_mock_info(user_id=1)
        
        # Call resolvers
        phone_result = UserType.resolve_phone_number(user_data_instance, info_a)
        email_result = UserType.resolve_email(user_data_instance, info_a)
        
        print(f"     - phone_number: {phone_result}")
        print(f"     - email: {email_result}")
        
        if phone_result == "+1234567890" and email_result == "test@confio.com":
            print("     ✅ SUCCESS: Own data is accessible")
        else:
            print("     ❌ FAILED: Own data is NOT accessible")

        # Test Case B: Accessing OTHER's data (ARBITRARY QUERYING CHECK)
        print("   [Case B] User 2 accessing User 1's data:")
        info_b = self.create_mock_info(user_id=2)
        
        phone_result_b = UserType.resolve_phone_number(user_data_instance, info_b)
        email_result_b = UserType.resolve_email(user_data_instance, info_b)
        
        print(f"     - phone_number: {phone_result_b}")
        print(f"     - email: {email_result_b}")
        
        if phone_result_b is None and email_result_b is None:
            print("     ✅ SUCCESS: Arbitrary querying blocked (hidden)")
        else:
            print("     ❌ FAILED: Arbitrary querying POSSIBLE (leaked)")

        # 4. Test SendTransactionType
        print("\n4. Inspecting SendTransactionType masked fields...")
        tx_fields = SendTransactionType._meta.fields
        has_tx_masked_sender = 'sender_phone_masked' in tx_fields
        has_tx_masked_recipient = 'recipient_phone_masked' in tx_fields
        
        print(f"   - sender_phone_masked present: {has_tx_masked_sender}")
        print(f"   - recipient_phone_masked present: {has_tx_masked_recipient}")

        if not has_tx_masked_sender and not has_tx_masked_recipient:
            print("     ✅ SUCCESS: Masked fields removed from transaction schema")
        else:
            print("     ❌ FAILED: Masked fields still present on SendTransactionType")

    def test_invoice_payment_transactions_security(self):
        """
        Verify that InvoiceType.resolve_payment_transactions restricts access correctly:
        - Merchant (Owner): Sees All
        - Payer: Sees Only Own
        - Random User: Sees None
        """
        print("\n--- Testing InvoiceType.resolve_payment_transactions Security ---")
        
        # Mocks
        merchant = MagicMock(spec=User)
        merchant.id = 100
        merchant.is_authenticated = True
        
        payer = MagicMock(spec=User)
        payer.id = 200
        payer.is_authenticated = True
        
        random_user = MagicMock(spec=User)
        random_user.id = 300
        random_user.is_authenticated = True
        
        invoice = MagicMock()
        invoice.created_by_user = merchant
        invoice.merchant_business = None # Simplify for now
        
        # Mock payment transactions manager
        txn1 = MagicMock()
        txn1.payer_user = payer
        txn2 = MagicMock()
        txn2.payer_user = MagicMock() # someone else
        
        all_txns = [txn1, txn2]
        
        # Mock .all()
        invoice.payment_transactions.all.return_value = all_txns
        
        # Mock .filter(payer_user=user)
        def mock_filter(payer_user=None):
            return [t for t in all_txns if t.payer_user == payer_user]
            
        invoice.payment_transactions.filter.side_effect = mock_filter

        # 1. Test Merchant Access
        info = MagicMock()
        info.context.user = merchant
        result = InvoiceType.resolve_payment_transactions(invoice, info)
        print(f"Merchant sees {len(result)} transactions (Expected 2)")
        if len(result) != 2:
             print("FAILURE: Merchant should see all transactions")
        else:
             print("SUCCESS: Merchant sees all")

        # 2. Test Payer Access
        info.context.user = payer
        result = InvoiceType.resolve_payment_transactions(invoice, info)
        print(f"Payer sees {len(result)} transactions (Expected 1)")
        
        if len(result) != 1 or result[0] != txn1:
             print("FAILURE: Payer should see only their own transaction")
        else:
             print("SUCCESS: Payer sees own only")

        # 3. Test Random User Access
        info.context.user = random_user
        result = InvoiceType.resolve_payment_transactions(invoice, info)
        print(f"Random User sees {len(result)} transactions (Expected 0)")
        if len(result) != 0:
             print("FAILURE: Random user should see zero transactions")
        else:
             print("SUCCESS: Random user sees none")

if __name__ == "__main__":
    try:
        verifier = SecurityVerifier()
        verifier.run_verification()
        verifier.test_invoice_payment_transactions_security()
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
