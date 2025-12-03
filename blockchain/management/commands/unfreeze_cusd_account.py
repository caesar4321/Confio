"""
Unfreeze a cUSD account via KMS admin signer.

Usage:
  python manage.py unfreeze_cusd_account --address <ALGOWALLET>
"""
import json
from pathlib import Path

from algosdk.abi import Contract
from algosdk.atomic_transaction_composer import AtomicTransactionComposer
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from algosdk.v2client import algod

from blockchain.kms_manager import KMSTransactionSigner, get_kms_signer_from_settings


class Command(BaseCommand):
    help = "Unfreeze a cUSD account using the cUSD app admin (KMS-backed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--address",
            required=True,
            help="Algorand address to unfreeze",
        )

    def handle(self, *args, **options):
        target = options["address"]
        app_id = getattr(settings, "ALGORAND_CUSD_APP_ID", None)
        asset_id = getattr(settings, "ALGORAND_CUSD_ASSET_ID", None)
        algod_addr = getattr(settings, "ALGORAND_ALGOD_ADDRESS", None)
        algod_token = getattr(settings, "ALGORAND_ALGOD_TOKEN", "")

        if not app_id or not asset_id or not algod_addr:
            raise CommandError("Missing ALGORAND_CUSD_APP_ID/ALGORAND_CUSD_ASSET_ID/ALGORAND_ALGOD_ADDRESS")

        # Load ABI
        try:
            abi_path = Path("contracts/cusd/contract.json")
            contract_json = json.loads(abi_path.read_text())
            contract = Contract.from_json(json.dumps(contract_json))
            method_unfreeze = contract.get_method_by_name("unfreeze_address")
        except Exception as exc:
            raise CommandError(f"Failed to load cUSD ABI: {exc}")

        # KMS admin signer (role=admin)
        kms_signer = KMSTransactionSigner(get_kms_signer_from_settings(role="admin"))
        admin_addr = kms_signer.kms_signer.address

        client = algod.AlgodClient(algod_token, algod_addr)

        # Build transaction
        sp = client.suggested_params()
        sp.flat_fee = True
        sp.fee = 2000  # covers inner freeze txn

        atc = AtomicTransactionComposer()
        atc.add_method_call(
            app_id=int(app_id),
            method=method_unfreeze,
            sender=admin_addr,
            sp=sp,
            signer=kms_signer,
            method_args=[target],
        )

        try:
            res = atc.execute(client, 4)
            txid = res.tx_ids[0] if getattr(res, "tx_ids", None) else "unknown"
            self.stdout.write(self.style.SUCCESS(f"Unfroze {target} in cUSD app {app_id}. TxID: {txid}"))
        except Exception as exc:
            raise CommandError(f"Failed to unfreeze address: {exc}")
