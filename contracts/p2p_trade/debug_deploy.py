import sys
print("DEBUG: Starting imports", file=sys.stderr)
import os
print("DEBUG: os imported", file=sys.stderr)
import base64
print("DEBUG: base64 imported", file=sys.stderr)
from pathlib import Path
print("DEBUG: pathlib imported", file=sys.stderr)

# Ensure project root on path for blockchain imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
print(f"DEBUG: Added {ROOT} to sys.path", file=sys.stderr)

try:
    from algosdk import account, mnemonic, logic
    print("DEBUG: algosdk core imported", file=sys.stderr)
    from algosdk.v2client import algod
    print("DEBUG: algosdk.v2client imported", file=sys.stderr)
    from algosdk.transaction import (
        ApplicationCreateTxn,
        ApplicationCallTxn,
        PaymentTxn,
        OnComplete,
        StateSchema,
        wait_for_confirmation,
        assign_group_id,
    )
    print("DEBUG: algosdk.transaction imported", file=sys.stderr)
    from algosdk.abi import Method, Returns, Argument
    print("DEBUG: algosdk.abi imported", file=sys.stderr)
    from algosdk.encoding import decode_address
    print("DEBUG: algosdk.encoding imported", file=sys.stderr)
except Exception as e:
    print(f"DEBUG: Error importing algosdk: {e}", file=sys.stderr)

try:
    from blockchain.kms_manager import KMSSigner
    print("DEBUG: blockchain.kms_manager imported", file=sys.stderr)
except Exception as e:
    print(f"DEBUG: Error importing blockchain.kms_manager: {e}", file=sys.stderr)

# Allow importing the contract module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from p2p_trade import app as p2p_app
    print("DEBUG: p2p_trade imported", file=sys.stderr)
except Exception as e:
    print(f"DEBUG: Error importing p2p_trade: {e}", file=sys.stderr)

print("DEBUG: All imports successful", file=sys.stderr)
