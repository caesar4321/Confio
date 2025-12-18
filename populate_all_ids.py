import os
import django
import uuid
import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from send.models import SendTransaction
from achievements.models import ReferralRewardEvent, ConfioRewardTransaction
from p2p_exchange.models import P2PTrade
from presale.models import PresalePurchase
# Import others if needed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def populate_ids():
    # 1. SendTransaction
    try:
        qs = SendTransaction.objects.all()
        count = qs.count()
        logger.info(f"Processing {count} SendTransaction records...")
        updated = 0
        for obj in qs:
            obj.internal_id = uuid.uuid4().hex
            obj.save(update_fields=['internal_id'])
            updated += 1
            if updated % 100 == 0:
                logger.info(f"Updated {updated} SendTransactions...")
        logger.info(f"Done with SendTransaction.")
    except Exception as e:
        logger.error(f"Error processing SendTransaction: {e}")

    # 2. Key: ConfioRewardTransaction
    try:
        qs = ConfioRewardTransaction.objects.all()
        count = qs.count()
        logger.info(f"Processing {count} ConfioRewardTransaction records...")
        updated = 0
        for obj in qs:
            obj.internal_id = uuid.uuid4().hex
            obj.save(update_fields=['internal_id'])
            updated += 1
        logger.info(f"Done with ConfioRewardTransaction.")
    except Exception as e:
        logger.error(f"Error processing ConfioRewardTransaction: {e}")

    # 3. ReferralRewardEvent (Already done but ensuring)
    try:
        qs = ReferralRewardEvent.objects.all()
        count = qs.count()
        logger.info(f"Processing {count} ReferralRewardEvent records...")
        updated = 0
        for obj in qs:
            # Only update if looks like default/dup (optional check, or just overwrite all)
            # Overwriting is safer to ensure uniqueness
            obj.internal_id = uuid.uuid4().hex
            obj.save(update_fields=['internal_id'])
            updated += 1
        logger.info(f"Done with ReferralRewardEvent.")
    except Exception as e:
        logger.error(f"Error processing ReferralRewardEvent: {e}")
        
    # 4. P2PTrade (Just in case)
    try:
        qs = P2PTrade.objects.all()
        count = qs.count()
        logger.info(f"Processing {count} P2PTrade records...")
        for obj in qs:
            # Check if likely dup or empty? Migration usually handles this but if failed...
            # Just overwrite to be safe.
            obj.internal_id = uuid.uuid4().hex
            obj.save(update_fields=['internal_id'])
        logger.info("Done with P2PTrade.")
    except Exception as e:
        logger.error(f"Error processing P2PTrade: {e}")

    # 5. PresalePurchase (Just in case)
    try:
        qs = PresalePurchase.objects.all()
        count = qs.count()
        logger.info(f"Processing {count} PresalePurchase records...")
        for obj in qs:
            obj.internal_id = uuid.uuid4().hex
            obj.save(update_fields=['internal_id'])
        logger.info("Done with PresalePurchase.")
    except Exception as e:
        logger.error(f"Error processing PresalePurchase: {e}")

if __name__ == "__main__":
    populate_ids()
