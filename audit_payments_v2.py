import sys
from payments.models import PaymentTransaction, Invoice
from send.models import SendTransaction
from django.db.models import Count
from django.utils import timezone
import datetime

def audit_payments():
    # Helper to print immediately
    def log(msg):
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    log("--- Auditing Confirmed Payments with Pending Invoices ---")
    stuck_payments = PaymentTransaction.objects.filter(
        status='CONFIRMED',
        invoice__status__in=['PENDING', 'SUBMITTED', 'PROCESSING']
    ).select_related('invoice')
    
    log(f"Found {stuck_payments.count()} stuck payments.")
    
    for pt in stuck_payments:
        log(f"Payment {pt.internal_id} (Hash: {pt.transaction_hash}) is CONFIRMED but Invoice {pt.invoice.invoice_id} is {pt.invoice.status}")
        
    log("\n--- Auditing Submitted Payments (potentially confirmed on chain) ---")
    submitted_payments = PaymentTransaction.objects.filter(status='SUBMITTED')
    log(f"Found {submitted_payments.count()} submitted payments.")
    
    log("\n--- Auditing Recent Invoices (Last 24h) ---")
    recent = timezone.now() - datetime.timedelta(hours=24)
    recent_invoices = Invoice.objects.filter(created_at__gte=recent).order_by('-created_at')
    
    for inv in recent_invoices:
        pts = inv.payment_transactions.all()
        log(f"Invoice {inv.invoice_id} ({inv.status}): {pts.count()} payments")
        for p in pts:
            log(f"  - Pay {p.internal_id}: {p.status} (Hash: {p.transaction_hash})")

if __name__ == '__main__':
    audit_payments()
