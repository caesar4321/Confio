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
    
    # Mock defaults from mutation
    defaults = {
         'payer_type': 'user', 
         'merchant_type': 'business',
         'payer_display_name': '',
         'merchant_display_name': recipient_business.name,
         'payer_phone': '',
         'amount': Decimal('0.10'),
         'token_type': 'CONFIO',
         'description': 'Test Debug',
         'status': 'PENDING_BLOCKCHAIN',
         'transaction_hash': f"pending_debug_{inv_id}",
         'blockchain_data': [{'mock': 'data'}],
         'idempotency_key': None,
         'invoice': invoice
    }
    
    try:
        pt, created = PaymentTransaction.objects.get_or_create(
            internal_id=inv_id,
            defaults=defaults
        )
        print(f"Success! Created: {created}, ID: {pt.internal_id}")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    debug_create()
debug_create()
