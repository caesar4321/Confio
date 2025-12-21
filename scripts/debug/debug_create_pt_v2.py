from payments.models import PaymentTransaction, Invoice
from users.models import Account, User, Business
from decimal import Decimal

def debug_create():
    inv_id = 'KJRXWY9J'
    print(f"Attempting to create PT for {inv_id}")
    invoice = Invoice.objects.get(invoice_id=inv_id)
    recipient_business = invoice.merchant_business
    if not recipient_business:
        print("No merchant business on invoice")
        return

    print(f"Invoice Merchant: {recipient_business.name}")
    
    # Needs a real account
    recipient_account = Account.objects.get(business=recipient_business, account_type='business')
    print(f"Recipient Account: {recipient_account.pk}")

    # Need a sender account (any user account)
    # Just picking the first available user account for valid FK
    sender_account = Account.objects.filter(account_type='user').first()
    sender_user = sender_account.user

    defaults = {
         'payer_user': sender_user,
         'payer_type': 'user', 
         'merchant_type': 'business',
         'payer_display_name': 'Debug Payer',
         'merchant_display_name': recipient_business.name,
         'payer_phone': '',
         'merchant_account': recipient_account, # CRITICAL: MUST BE SET
         'payer_account': sender_account,       # CRITICAL: MUST BE SET
         'payer_address': sender_account.algorand_address or 'test_addr',
         'merchant_address': recipient_account.algorand_address or 'test_addr',
         'amount': Decimal('0.10'),
         'token_type': 'CONFIO',
         'description': 'Test Debug Corrected',
         'status': 'PENDING_BLOCKCHAIN',
         'transaction_hash': f"pending_debug2_{inv_id}",
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
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    debug_create()
debug_create()
