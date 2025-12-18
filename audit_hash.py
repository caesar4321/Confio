import sys
from payments.models import PaymentTransaction
from send.models import SendTransaction
from users.models_unified import UnifiedTransactionTable

def find_transaction(partial_hash):
    with open('audit_results_hash.txt', 'w') as f:
        def log(msg):
            f.write(msg + "\n")
            print(msg)

        log(f"--- Searching for hash starting with {partial_hash} ---")
        
        # PaymentTransaction
        pts = PaymentTransaction.objects.filter(transaction_hash__startswith=partial_hash)
        log(f"Found {pts.count()} PaymentTransactions")
        for pt in pts:
            log(f"PAYMENT: ID={pt.internal_id} Status={pt.status} Invoice={pt.invoice_id if pt.invoice else 'None'}")
            if pt.invoice:
                 log(f"  Invoice Status: {pt.invoice.status}")
        
        # SendTransaction
        sts = SendTransaction.objects.filter(transaction_hash__startswith=partial_hash)
        log(f"Found {sts.count()} SendTransactions")
        for st in sts:
            log(f"SEND: ID={st.internal_id} Status={st.status}")
            
        # UnifiedTransactionTable
        uts = UnifiedTransactionTable.objects.filter(transaction_hash__startswith=partial_hash)
        log(f"Found {uts.count()} UnifiedTransactions")
        for ut in uts:
            log(f"UNIFIED: ID={ut.internal_id} Type={ut.transaction_type} Status={ut.status}")

find_transaction('76O4CR77')
