import sys
from algosdk import encoding
from blockchain.rewards_service import ConfioRewardsService

if len(sys.argv) != 2:
    print("usage: read_box.py <base64-address>")
    sys.exit(1)

addr = sys.argv[1]
service = ConfioRewardsService()
box = service._read_user_box(encoding.decode_address(addr))
print(box)
