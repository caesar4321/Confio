from payments.models import PaymentTransaction, Invoice
from users.models import Account, User, Business
from decimal import Decimal
import traceback

def debug_create():
    inv_id = 'KJRXWY9J'
    print(f"Attempting to create PT for {inv_id}")
    try:
        invoice = Invoice.objects.get(invoice_id=inv_id)
    except Invoice.DoesNotExist:
        print("Invoice not found!")
        return

    recipient_business = invoice.merchant_business
    if not recipient_business:
        print("No merchant business on invoice")
        return

    print(f"Invoice Merchant: {recipient_business.name}")
    
    try:
        recipient_account = Account.objects.get(business=recipient_business, account_type='business')
    except Account.DoesNotExist:
        print("Recipient Account not found!")
        return
        
    print(f"Recipient Account: {recipient_account.pk}")

    sender_user = recipient_account.user
    if not sender_user:
        sender_user = User.objects.first()
    
    if not sender_user:
        print("No user found at all!")
        return
        
    sender_account = Account.objects.filter(user=sender_user).first()
    if not sender_account:
        print("No sender account found for user!")
        return

    defaults = {
         'payer_user': sender_user,
         'payer_type': 'user', 
         'merchant_type': 'business',
         'payer_display_name': 'Debug Payer',
         'merchant_display_name': recipient_business.name,
         'payer_phone': '',
         'merchant_business': recipient_business, # ADDED THIS
         'merchant_account': recipient_account, 
         'payer_account': sender_account,       
         'payer_address': sender_account.algorand_address or 'test_addr',
         'merchant_address': recipient_account.algorand_address or 'test_addr',
         'amount': Decimal('0.10'),
         'token_type': 'CONFIO',
         'description': 'Test Debug Corrected V4',
         'status': 'PENDING_BLOCKCHAIN',
         'transaction_hash': f"pending_debug4_{inv_id}",
         'blockchain_data': [{'mock': 'data'}],
         'idempotency_key': None,
         'invoice': invoice
    }
    
    try:
        pt, created = PaymentTransaction.objects.get_or_create(
            internal_id=inv_id,
            defaults=defaults
        )
        print(f"Success! Created: {created}, ID: {pt.internal_id}, Status: {pt.status}")
    except Exception as e:
        print(f"FAILED: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    debug_create()
debug_create()
