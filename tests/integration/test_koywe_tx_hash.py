#!/usr/bin/env python3
import os
import django
import logging
from unittest.mock import patch, MagicMock

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from users.models import Account
from conversion.models import Conversion
from ramps.models import RampTransaction
from blockchain.mutations import SubmitAutoSwapTransactionsMutation
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockInfo:
    class Context:
        def __init__(self, user):
            self.user = user
    def __init__(self, user):
        self.context = self.Context(user)

def test_koywe_tx_hash_association():
    """Verify that SubmitAutoSwapTransactionsMutation calls Koywe on-ramp TX hash association."""
    logger.info("🔍 Testing Koywe TX ID association logic...")
    
    User = get_user_model()
    user, _ = User.objects.get_or_create(username='testuser_koywe', email='test@example.com')
    
    account, _ = Account.objects.get_or_create(
        user=user, 
        account_type='personal',
        defaults={'algorand_address': 'V3VHTG6M4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z4Z'}
    )

    # Create a mock conversion
    conv = Conversion.objects.create(
        actor_user=user,
        actor_address=account.algorand_address,
        conversion_type='cusd_to_usdc',
        from_amount=10.0,
        to_amount=10.0,
        status='PENDING_SIG'
    )

    # Create a mock RampTransaction linked to the conversion
    ramp_tx = RampTransaction.objects.create(
        actor_user=user,
        provider='koywe',
        provider_order_id='ord_mock_123',
        direction='off_ramp',
        conversion=conv,
        status='PENDING'
    )

    logger.info(f"Created Conversion {conv.internal_id} and RampTransaction {ramp_tx.provider_order_id}")

    mock_info = MockInfo(user)
    
    # Mock the Algorand client and the Koywe client
    with patch('blockchain.mutations.get_algod_client') as mock_get_algod, \
         patch('ramps.koywe_client.KoyweClient.add_order_tx_hash') as mock_add_hash:
        
        # Setup mock algod client
        mock_algod_inst = MagicMock()
        mock_algod_inst.send_raw_transaction.return_value = "MOCK_TX_ID_12345"
        mock_get_algod.return_value = mock_algod_inst
        
        # Prepare dummy signed/sponsor transactions
        # In reality these would be base64 blobs, but our logic just joins and encodes them
        dummy_signed = ["c2lnbmVkX3R4bg=="] # "signed_txn" in base64
        dummy_sponsor = [{"index": 0, "signed": "c3BvbnNvcl90eG4="}] # "sponsor_txn" in base64

        logger.info("Calling SubmitAutoSwapTransactionsMutation...")
        
        result = SubmitAutoSwapTransactionsMutation.mutate(
            None, 
            mock_info, 
            internal_id=str(conv.internal_id),
            signed_transactions=dummy_signed,
            sponsor_transactions=[json.dumps(s) for s in dummy_sponsor]
        )

        if not result.success:
            logger.error(f"❌ Mutation failed: {result.error}")
            return False

        logger.info(f"✅ Mutation reported success. TXID: {result.txid}")

        # ASSERTIONS
        # 1. Check if KoyweClient.add_order_tx_hash was called
        try:
            mock_add_hash.assert_called_once_with(
                order_id='ord_mock_123',
                tx_hash='MOCK_TX_ID_12345',
                email='test@example.com'
            )
            logger.info("✅ SUCCESS: KoyweClient.add_order_tx_hash was called with correct arguments!")
        except AssertionError as e:
            logger.error(f"❌ FAILURE: KoyweClient.add_order_tx_hash not called correctly: {e}")
            return False

        # 2. Check if conversion status was updated
        conv.refresh_from_db()
        if conv.status == 'SUBMITTED' and conv.to_transaction_hash == 'MOCK_TX_ID_12345':
            logger.info("✅ SUCCESS: Conversion status and hash updated in DB.")
        else:
            logger.error(f"❌ FAILURE: Conversion status ({conv.status}) or hash ({conv.to_transaction_hash}) incorrect.")
            return False

    return True

if __name__ == '__main__':
    import json
    try:
        if test_koywe_tx_hash_association():
            logger.info("\n🎉 All tests passed!")
        else:
            logger.info("\n❌ Tests failed.")
            exit(1)
    finally:
        # Cleanup
        User = get_user_model()
        User.objects.filter(username='testuser_koywe').delete()
