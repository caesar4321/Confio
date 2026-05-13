"""
Audit: find pre-V2 accounts falsely marked is_keyless_migrated=True.

Pre-V2 = account created before Dec 13 2025 (when is_keyless_migrated was deployed).
These accounts were born with is_keyless_migrated=False.  If they now show True
WITHOUT backup_verified_at, the flag was likely set manually (falsified) rather
than through proper V1->V2 migration.

Risk: any deposit (Koywe, P2P, direct) goes to the V1 address the user cannot
sign for with V2 logic, stranding the funds.
"""
import sys, os, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from datetime import datetime, timezone
from users.models import Account
from users.migration_safety import inspect_address_migration_risk
from algosdk.v2client import algod
from django.conf import settings

V2_DEPLOY = datetime(2025, 12, 13, tzinfo=timezone.utc)

def get_algod_client():
    token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
    url = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', '')
    headers = {"X-API-Key": token} if token else {}
    return algod.AlgodClient(token, url, headers=headers)

def run_audit():
    client = get_algod_client()

    suspects = Account.objects.filter(
        is_keyless_migrated=True,
        account_type='personal',
        account_index=0,
        user__date_joined__lt=V2_DEPLOY,
        user__backup_verified_at__isnull=True,
    ).select_related('user').order_by('user__date_joined')

    total_pre_v2 = Account.objects.filter(
        is_keyless_migrated=True,
        account_type='personal',
        account_index=0,
        user__date_joined__lt=V2_DEPLOY,
    ).count()

    with_backup = Account.objects.filter(
        is_keyless_migrated=True,
        account_type='personal',
        account_index=0,
        user__date_joined__lt=V2_DEPLOY,
        user__backup_verified_at__isnull=False,
    ).count()

    print("Pre-V2 accounts (before Dec 13 2025) now marked migrated: %d" % total_pre_v2)
    print("  With backup (likely legit): %d" % with_backup)
    print("  WITHOUT backup (SUSPECT):   %d" % suspects.count())
    print("=" * 90)

    results = []
    for acc in suspects:
        if not acc.algorand_address:
            continue
        try:
            risk = inspect_address_migration_risk(client, acc.algorand_address)
        except Exception as e:
            risk = {'has_material_risk': 'ERROR', 'relevant_assets': {}, 'spendable_algo': 0}
        time.sleep(0.15)

        # Also check on-chain: does the address have any opted-in assets?
        try:
            info = client.account_info(acc.algorand_address)
            opted_assets = len(info.get('assets', []))
            total_algo = info.get('amount', 0)
        except Exception:
            opted_assets = -1
            total_algo = 0

        results.append({
            'user_id': acc.user.id,
            'account_id': acc.id,
            'email': acc.user.email,
            'address': acc.algorand_address,
            'date_joined': acc.user.date_joined.strftime('%Y-%m-%d'),
            'has_funds': risk['has_material_risk'],
            'assets': risk['relevant_assets'],
            'spendable_algo': risk['spendable_algo'],
            'opted_assets': opted_assets,
            'total_algo': total_algo,
        })

    print("\nSUSPECT ACCOUNTS (pre-V2, migrated=True, no backup):")
    print("=" * 90)
    for r in results:
        tag = "HAS FUNDS" if r['has_funds'] else "empty"
        print("  [%s] user_id=%d acct=%d" % (tag, r['user_id'], r['account_id']))
        print("    email:       %s" % r['email'])
        print("    address:     %s" % r['address'])
        print("    joined:      %s" % r['date_joined'])
        print("    opted_assets: %d  total_algo: %d microAlgos" % (r['opted_assets'], r['total_algo']))
        if r['has_funds']:
            print("    relevant_assets: %s" % r['assets'])
            print("    spendable_algo:  %d microAlgos" % r['spendable_algo'])
        print()

    with_funds = [r for r in results if r['has_funds']]
    print("SUMMARY:")
    print("  Total suspects:          %d" % len(results))
    print("  With funds (CRITICAL):   %d" % len(with_funds))
    print("  Empty (still at risk):   %d" % (len(results) - len(with_funds)))

if __name__ == "__main__":
    run_audit()
