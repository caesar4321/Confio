from payments.models import PaymentTransaction, Invoice

def check_specific():
    inv_id = 'KJRXWY9J'
    print(f"Checking Invoice {inv_id}")
    try:
        inv = Invoice.objects.get(invoice_id=inv_id)
        print(f"Invoice found: PK={inv.pk} Status={inv.status}")
        pts = PaymentTransaction.objects.filter(invoice=inv)
        print(f"Linked Payments: {pts.count()}")
        for p in pts:
            print(f" - PT {p.internal_id} Status={p.status}")
            
        print(f"Checking PaymentTransaction with internal_id='{inv_id}'")
        pt_direct = PaymentTransaction.objects.filter(internal_id=inv_id).first()
        if pt_direct:
            print(f"Found PT by direct ID match: Status={pt_direct.status}, Linked Invoice={pt_direct.invoice.invoice_id}")
        else:
            print("No PT found with this internal_id")
            
    except Invoice.DoesNotExist:
        print("Invoice not found")

if __name__ == '__main__':
    check_specific()
check_specific()
