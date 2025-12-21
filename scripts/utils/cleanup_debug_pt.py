from payments.models import PaymentTransaction
def cleanup():
    try:
        pt = PaymentTransaction.objects.get(internal_id='KJRXWY9J')
        print(f"Deleting debug PT: {pt}")
        pt.delete() # Hard delete or soft? Soft is default.
        # Actually for debug cleanup I might want hard delete to avoid confusion?
        # But soft is safer.
        print("Deleted.")
    except PaymentTransaction.DoesNotExist:
        print("PT not found.")

if __name__ == '__main__':
    cleanup()
cleanup()
