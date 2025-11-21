#!/usr/bin/env python3
"""Create a test referral box in the NEW rewards contract."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address
from algosdk import account, encoding, mnemonic, transaction
from algosdk.v2client import algod
from algosdk.logic import get_application_address

# Get Algorand client
algod_client = algod.AlgodClient(
    "",
    "https://testnet-api.4160.nodely.dev"
)

# Get admin credentials
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"
admin_sk = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_sk)

sponsor_sk = admin_sk
sponsor_addr = admin_addr

# Get users
referee = User.objects.get(username='user_4923eef3')
referrer = User.objects.get(username='julianmoonluna')

referee_addr = get_primary_algorand_address(referee)
referrer_addr = get_primary_algorand_address(referrer)

print(f"Referee: {referee.username} - {referee_addr}")
print(f"Referrer: {referrer.username} - {referrer_addr}")
print()

# New app ID
app_id = 749685745
app_address = get_application_address(app_id)
confio_asset_id = 749148838

# Reward amounts (20 CONFIO = 20_000_000 micro-units)
referee_reward = 20_000_000
referrer_reward = 20_000_000

print(f"Creating referral box in app {app_id}")
print(f"Admin: {admin_addr}")
print(f"Sponsor: {sponsor_addr}")
print()

# Build the mark_eligible transaction
params = algod_client.suggested_params()

# Payment for box MBR
box_price = 180_000  # As set in the contract
pay_txn = transaction.PaymentTxn(
    sender=sponsor_addr,
    receiver=app_address,
    amt=box_price,
    sp=params,
)

# Application call
call_params = algod_client.suggested_params()
call_params.flat_fee = True
call_params.fee = 2000

referee_key = encoding.decode_address(referee_addr)
referrer_key = encoding.decode_address(referrer_addr)

# mark_eligible expects:
# app_args[0] = "mark_eligible"
# app_args[1] = referee reward (cUSD micro-units, will be converted to CONFIO)
# app_args[2] = referee address (32 bytes)
# app_args[3] = referrer reward (cUSD micro-units, optional)
# accounts[1] = referee (if different from admin)
# accounts[2] = referrer (if ref_amount > 0)

# For testing, we'll use a fixed cUSD price of 250_000 micro-cUSD per CONFIO
# confio_reward = reward_cusd * CONFIO_DECIMALS / price
# CONFIO_DECIMALS = 1_000_000, price = 250_000
# Vault has 100 CONFIO, 20 already committed, so 80 available
# To get 5_000_000 CONFIO (5 CONFIO): reward_cusd = 5_000_000 * 250_000 / 1_000_000 = 1_250_000_000
# So $1.25 cUSD = 1_250_000_000 micro-cUSD → 5 CONFIO
referee_cusd = 1_250_000_000  # $1.25 cUSD → 5 CONFIO
referrer_cusd = 1_250_000_000  # $1.25 cUSD → 5 CONFIO

app_txn = transaction.ApplicationNoOpTxn(
    sender=admin_addr,
    index=app_id,
    sp=call_params,
    app_args=[
        b"mark_eligible",
        referee_cusd.to_bytes(8, "big"),
        referee_key,
        referrer_cusd.to_bytes(8, "big"),
    ],
    accounts=[referee_addr, referrer_addr],  # referee at [1], referrer at [2]
    foreign_assets=[confio_asset_id],
    boxes=[transaction.BoxReference(0, referee_key)],
)

# Group the transactions
transaction.assign_group_id([pay_txn, app_txn])

# Sign
signed_pay = pay_txn.sign(sponsor_sk)
signed_app = app_txn.sign(admin_sk)

# Send
print("Sending mark_eligible transaction...")
tx_id = algod_client.send_transactions([signed_pay, signed_app])
print(f"Transaction ID: {tx_id}")

# Wait for confirmation
result = transaction.wait_for_confirmation(algod_client, tx_id, 6)
print(f"✅ Confirmed in round {result.get('confirmed-round')}")
print()

# Verify the box was created
print("Verifying box creation...")
from blockchain.rewards_service import ConfioRewardsService
service = ConfioRewardsService()

box_data = service._read_user_box(referee_key)
print(f"✅ Box created successfully!")
print(f"   Referee amount: {box_data['referee_amount'] / 1_000_000} CONFIO (claimed: {box_data['referee_claimed']})")
print(f"   Referrer amount: {box_data['referrer_amount'] / 1_000_000} CONFIO (claimed: {box_data['referrer_claimed']})")
print(f"   Referrer address: {box_data['referrer_address']}")
print(f"   Round created: {box_data['round_created']}")
