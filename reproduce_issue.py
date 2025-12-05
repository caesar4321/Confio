
import sys
from unittest.mock import MagicMock, patch

# Mock blockchain.kms_manager
mock_kms = MagicMock()
mock_signer = MagicMock()
mock_signer.address = "TIU6WOJ5CYM6TMOOBOQV4EDPUZ6RVNVEO6MTTULYH6SWW67VR75D6UJAHM" # Dummy sponsor
mock_signer.sign_transaction.return_value = "signed_txn"
mock_signer.sign_transaction_msgpack.return_value = b"signed_txn_bytes"
mock_signer.configure_mock(assert_matches_address=MagicMock(return_value=None))

mock_kms.get_kms_signer_from_settings.return_value = mock_signer
mock_kms.KMSTransactionSigner = MagicMock

sys.modules["blockchain.kms_manager"] = mock_kms

# Also mock secrets to avoid AWS calls
mock_secrets = MagicMock()
mock_secrets.get_secret.side_effect = Exception("Mocked secret failure")
sys.modules["config.secrets"] = mock_secrets

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["USE_KMS_SIGNING"] = "True"
os.environ["ALGORAND_ALGOD_ADDRESS"] = "https://testnet-api.algonode.cloud"
os.environ["ALGORAND_INDEXER_ADDRESS"] = "https://testnet-idx.algonode.cloud"
os.environ["ALGORAND_PAYMENT_APP_ID"] = "123"

# Setup Django
try:
    django.setup()
except Exception as e:
    print(f"Django setup warning: {e}")

from blockchain.p2p_trade_transaction_builder import P2PTradeTransactionBuilder
from django.conf import settings

print(f"App ID: {getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', 'N/A')}")
print(f"Sponsor: {getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', 'N/A')}")

# Mock algod client to avoid network calls and return dummy data
with patch("blockchain.p2p_trade_transaction_builder.algod.AlgodClient") as MockAlgod:
    client = MockAlgod.return_value
    client.suggested_params.return_value = MagicMock(
        min_fee=1000, first=100, last=200, gh="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", gen="gen"
    )
    
    # Test SubmitP2pAcceptTrade mutation logic
    from blockchain.p2p_trade_mutations import SubmitP2pAcceptTrade, MarkP2PTradePaid
    
    # Mock info
    class MockUser:
        is_authenticated = True
        id = 1
    class MockContext:
        user = MockUser()
    class MockInfo:
        context = MockContext()
    
    # Use dummy addresses
    buyer = "TIU6WOJ5CYM6TMOOBOQV4EDPUZ6RVNVEO6MTTULYH6SWW67VR75D6UJAHM"
    trade_id = "test_trade_id"
    payment_ref = ""

    # Mock get_algod_client
    with patch("blockchain.p2p_trade_mutations.get_algod_client", return_value=client):
        # Mock SPONSOR_SIGNER
        with patch("blockchain.p2p_trade_mutations.SPONSOR_SIGNER", mock_signer):
             
             # Let's construct a dummy signed_user_txn
             import msgpack
             import base64
             dummy_txn = {
                 'txn': {
                     'type': 'appl',
                     'snd': b'dummy', # Placeholder
                 }
             }
             # We need valid address bytes
             from algosdk import encoding
             addr_bytes = encoding.decode_address(buyer)
             dummy_txn['txn']['snd'] = addr_bytes
             
             # Add params to dummy txn
             dummy_txn['txn']['fv'] = 100
             dummy_txn['txn']['lv'] = 200
             # gh in msgpack is 32 bytes.
             dummy_txn['txn']['gh'] = base64.b64decode("SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=")
             dummy_txn['txn']['gen'] = "gen"
             
             signed_bytes = msgpack.packb(dummy_txn)
             signed_b64 = base64.b64encode(signed_bytes).decode()
             
             # Pre-calculate expected sponsor txn to pass it
             # We need to use the SAME params
             from algosdk import transaction
             sp = transaction.SuggestedParams(
                fee=1000,
                first=100,
                last=200,
                gh=base64.b64decode("SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=").decode('latin1') if False else "SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
                gen="gen",
                flat_fee=True
             )
             
             builder = P2PTradeTransactionBuilder()
             
             # Let's run build first
             res_build = builder.build_accept_trade_user(buyer, trade_id, params=sp)
             sponsor_txs_input = []
             if res_build.success:
                 import json
                 # Convert to JSON string list as expected by mutation
                 for stx in res_build.sponsor_transactions:
                     # stx has 'txn' (base64) and 'index'
                     t = stx.get('txn')
                     if isinstance(t, bytes):
                         stx['txn'] = t.decode()
                     s = stx.get('signed')
                     if isinstance(s, bytes):
                         stx['signed'] = base64.b64encode(s).decode()
                     sponsor_txs_input.append(json.dumps(stx))
             
             print(f"Generated {len(sponsor_txs_input)} sponsor txns for input")

             # Reset mock calls
             client.suggested_params.reset_mock()
             
             # Simulate client changing fee to 2000 (different from prepare's 1000)
             dummy_txn['txn']['fee'] = 2000
             signed_bytes_mod = msgpack.packb(dummy_txn)
             signed_b64_mod = base64.b64encode(signed_bytes_mod).decode()

             print("Calling SubmitP2pAcceptTrade.mutate with modified fee (2000)...")
             # We pass sponsor_txs_input (generated with fee 1000) and signed_b64_mod (fee 2000)
             # This should succeed with the relaxed check and use fee 2000 for rebuild
             res = SubmitP2pAcceptTrade.mutate(None, MockInfo(), trade_id, signed_b64_mod, sponsor_txs_input)
             
             print(f"Mutation Result (Accept): success={res.success} error={res.error}")
             print(f"Suggested Params Call Count: {client.suggested_params.call_count}")

             # Test MarkP2PTradePaid
             print("Calling MarkP2PTradePaid.mutate...")
             try:
                 # Note: MarkP2PTradePaid logic will likely fail due to mismatching sponsor txns (since we generated accept txns above, not mark_paid txns)
                 # But we just want to verify it doesn't crash with AttributeError
                 res_mark = MarkP2PTradePaid.mutate(None, MockInfo(), trade_id, "ref", signed_b64, sponsor_txs_input)
                 print(f"Mutation Result (MarkPaid): success={res_mark.success} error={res_mark.error}")
             except Exception as e:
                 print(f"Mutation Result (MarkPaid): CRASHED: {e}")
