import os
import django
import asyncio
from django.conf import settings
from blockchain.payment_mutations import CreateSponsoredPaymentMutation, SubmitSponsoredPaymentMutation
from users.models import User, Business, Account
from payments.models import Invoice, PaymentTransaction
from decimal import Decimal
import base64

# Setup
def run_debug():
    print("--- Debugging Payment Flow: Create -> Submit ---")
    
    # 1. Setup Data
    user = User.objects.filter(username='julianmoonluna').first()
    business = Business.objects.get(id=18)  # Sabor de Chicha - has Algorand account
    
    # Get a merchant user
    merchant_user = business.employees.first().user if business.employees.exists() else User.objects.exclude(id=user.id).first()
    merchant_account = Account.objects.filter(user=merchant_user).first()
    if not merchant_account:
        merchant_account = Account.objects.create(user=merchant_user)

    print(f"User: {user} (ID: {user.id})")
    print(f"Merchant: {business} (ID: {business.id})")
    
    # Create Invoice to use as internal_id
    internal_id = "TESTINV02" # New ID
    try:
        from django.utils import timezone
        import datetime
        inv, _ = Invoice.objects.get_or_create(
            invoice_id=internal_id,
            defaults={
                'amount': Decimal('0.1'),
                'token_type': 'CONFIO',
                'description': 'Test Invoice',
                'merchant_business': business,
                'created_by_user': merchant_user,
                'merchant_account': merchant_account,
                'expires_at': timezone.now() + datetime.timedelta(days=1),
                'status': 'PENDING'
            }
        )
        print(f"Invoice: {inv.invoice_id}")
    except Exception as e:
        print(f"Invoice Error: {e}")
        return

    # 2. Setup Context with JWT
    from rest_framework_simplejwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    
    from payments.ws_consumers import _DummyRequest, _DummyInfo
    meta = {}
    meta['HTTP_AUTHORIZATION'] = f"JWT {token}"
    
    dummy_request = _DummyRequest(user=user, meta=meta)
    info = _DummyInfo(context=dummy_request)
    
    # Mock JWT context - typically this is injected into mutation via specialized context or headers
    # But here we rely on the mutation finding the user from info.context.user 
    # AND relying on my recent fix to find recipient business from Invoice ID
    
    print("\n--- Step 1: Create ---")
    res_create = CreateSponsoredPaymentMutation.mutate(
        None,
        info,
        amount=0.1,
        asset_type='CONFIO',
        internal_id=internal_id,
        note="Test Note"
    )
    
    if not res_create.success:
        print(f"Create FAILED: {res_create.error}")
        return
        
    print(f"Create OK. Internal ID: {res_create.internal_id}")
    transactions = res_create.transactions # List of serialized txns
    
    # Verify DB Record
    pt = PaymentTransaction.objects.get(internal_id=internal_id)
    print(f"DB Record Created: ID={pt.id}, InternalID={pt.internal_id}, Status={pt.status}")
    
    # 3. Simulate Client Signing (Dummy)
    # The submit mutation expects signed transactions. We can just pass back the raw ones 
    # wrapped in the format it expects if we disable signature verification or just want to test lookup logic.
    # SubmitSponsoredPaymentMutation parses the `signed_transactions` JSON.
    
    # It expects: [{'index': 0, 'transaction': 'b64...'}, ...]
    # We will just pass the ones we got back, pretending they are signed.
    signed_txns = []
    for tx in transactions:
        # tx is dict {index, transaction, ...}
        signed_txns.append({
            'index': tx['index'],
            'transaction': tx['transaction']
        })
        
    import json
    signed_payload = json.dumps(signed_txns)
    
    print("\n--- Step 2: Submit ---")
    # Call Submit with internal_id
    res_submit = SubmitSponsoredPaymentMutation.mutate(
        None,
        info,
        signed_transactions=signed_payload,
        internal_id=internal_id
    )
    
    if not res_submit.success:
        print(f"Submit FAILED: {res_submit.error}")
        # Even if it fails (due to signature validation), we check if DB lookup was attempted
    else:
        print(f"Submit OK. TxID: {res_submit.transaction_id}")

    # 4. Verify DB Update
    pt.refresh_from_db()
    print(f"Final DB Status: {pt.status}")
    print(f"Final Info: Hash={pt.transaction_hash}")

    if pt.status == 'SUBMITTED' or (pt.status == 'PENDING_BLOCKCHAIN' and res_submit.success == False):
        print("Test Result: Logic sound (or failed expectedly on sigs).")
    else:
        print("Test Result: DB Update MISSED (Status didn't change)")

if __name__ == "__main__":
    run_debug()
run_debug()
