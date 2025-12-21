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
    # Helper to process in batches
    def process_model(ModelClass, name):
        try:
            qs = ModelClass.objects.all()
            count = qs.count()
            logger.info(f"Processing {count} {name} records...")
            
            batch = []
            updated_count = 0
            for obj in qs:
                # Use uuid hex
                obj.internal_id = uuid.uuid4().hex
                batch.append(obj)
                
                if len(batch) >= 1000:
                    ModelClass.objects.bulk_update(batch, ['internal_id'])
                    updated_count += len(batch)
                    batch = []
                    logger.info(f"Updated {updated_count} {name} records...")
            
            if batch:
                ModelClass.objects.bulk_update(batch, ['internal_id'])
                updated_count += len(batch)
                
            logger.info(f"Done with {name}. Total updated: {updated_count}")
        except Exception as e:
            logger.error(f"Error processing {name}: {e}")

    # 1. SendTransaction
    process_model(SendTransaction, "SendTransaction")

    # 2. ConfioRewardTransaction
    process_model(ConfioRewardTransaction, "ConfioRewardTransaction")

    # 3. ReferralRewardEvent
    process_model(ReferralRewardEvent, "ReferralRewardEvent")
        
    # 4. P2PTrade
    process_model(P2PTrade, "P2PTrade")

    # 5. PresalePurchase
    process_model(PresalePurchase, "PresalePurchase")

if __name__ == "__main__":
    populate_ids()
