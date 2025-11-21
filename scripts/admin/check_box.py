from algosdk.v2client import algod
from algosdk import encoding
import struct

algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
client = algod.AlgodClient(algod_token, algod_address)

app_id = 749645823
user_9_addr = "TIU6WOJ5CYM6TMOOBOQV4EDPUZ6RVNVEO6MTTULYH6SWW67VR75D6UJAHM"
user_9_bytes = encoding.decode_address(user_9_addr)

try:
    box_response = client.application_box_by_name(app_id, user_9_bytes)
    box_value = box_response['value']

    print(f"Box found for user 9!")
    print(f"Box size: {len(box_value)} bytes")

    # Parse box contents
    amount_offset = 0
    claimed_offset = 8
    round_offset = 16
    ref_addr_offset = 24
    ref_amount_offset = 56
    ref_claimed_offset = 64

    amount = struct.unpack('>Q', box_value[amount_offset:amount_offset+8])[0]
    claimed = struct.unpack('>Q', box_value[claimed_offset:claimed_offset+8])[0]
    ref_address = encoding.encode_address(box_value[ref_addr_offset:ref_addr_offset+32])
    ref_amount = struct.unpack('>Q', box_value[ref_amount_offset:ref_amount_offset+8])[0]
    ref_claimed = struct.unpack('>Q', box_value[ref_claimed_offset:ref_claimed_offset+8])[0]

    print(f"\nBox contents:")
    print(f"  Referee amount: {amount / 1_000_000} CONFIO")
    print(f"  Referee claimed: {claimed / 1_000_000} CONFIO")
    print(f"  Referrer address: {ref_address}")
    print(f"  Referrer amount: {ref_amount / 1_000_000} CONFIO")
    print(f"  Referrer claimed: {ref_claimed / 1_000_000} CONFIO")

except Exception as e:
    print(f"No box found or error: {e}")
