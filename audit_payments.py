from payments.models import PaymentTransaction, Invoice
from send.models import SendTransaction
from django.db.models import Count

def audit_payments():
    # 1. Find Confirmed Payments with Pending Invoices
    print("--- Auditing Confirmed Payments with Pending Invoices ---")
    stuck_payments = PaymentTransaction.objects.filter(
        status='CONFIRMED',
        invoice__status__in=['PENDING', 'SUBMITTED', 'PROCESSING']
    ).select_related('invoice')
    
    print(f"Found {stuck_payments.count()} stuck payments.")
    
    for pt in stuck_payments:
        print(f"Payment {pt.internal_id} (Hash: {pt.transaction_hash}) is CONFIRMED but Invoice {pt.invoice.invoice_id} is {pt.invoice.status}")
        
    # 2. Find Submitted Payments that are actually confirmed on chain (but stuck in SUBMITTED)
    print("\n--- Auditing Submitted Payments (potentially confirmed on chain) ---")
    submitted_payments = PaymentTransaction.objects.filter(status='SUBMITTED')
    print(f"Found {submitted_payments.count()} submitted payments.")
    
    # 3. Check for recently created invoices with NO payments
    print("\n--- Auditing Recent Invoices (Last 24h) ---")
    from django.utils import timezone
    import datetime
    recent = timezone.now() - datetime.timedelta(hours=24)
    recent_invoices = Invoice.objects.filter(created_at__gte=recent).order_by('-created_at')
    
    for inv in recent_invoices:
        pts = inv.payment_transactions.all()
        print(f"Invoice {inv.invoice_id} ({inv.status}): {pts.count()} payments")
        for p in pts:
            print(f"  - Pay {p.internal_id}: {p.status} (Hash: {p.transaction_hash})")

if __name__ == '__main__':
    audit_payments()
