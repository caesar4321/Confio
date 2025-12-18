import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from presale.models import PresalePurchase
from users.models_unified import UnifiedTransactionTable
from django.db import transaction


def backfill_presale_unified():
    total = PresalePurchase.objects.count()
    linked = 0
    created = 0
    for purchase in PresalePurchase.objects.iterator():
        try:
            # Try to find existing UnifiedTransactionTable entry
            unified = UnifiedTransactionTable.objects.filter(
                presale_purchase_id=purchase.id
            ).first()
            if unified:
                if unified.presale_purchase_id != purchase.id:
                    unified.presale_purchase = purchase
                    unified.save(update_fields=['presale_purchase'])
                linked += 1
                continue
            # No existing entry, create one
            with transaction.atomic():
                UnifiedTransactionTable.objects.create(
                    transaction_type='presale',
                    amount=str(purchase.cusd_amount),
                    token_type='CUSD',
                    status=purchase.status,
                    transaction_hash=purchase.transaction_hash or '',
                    from_address=purchase.from_address or '',
                    to_address='',
                    presale_purchase=purchase,
                    transaction_date=purchase.created_at,
                )
                created += 1
        except Exception as e:
            print(f"Error processing PresalePurchase {purchase.id}: {e}")
    print(f"Backfill complete: {total} total, {linked} linked, {created} created new UnifiedTransactionTable entries.")

if __name__ == '__main__':
    backfill_presale_unified()
