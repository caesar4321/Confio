"""
Transfer cUSD app admin to the KMS-backed sponsor address and opt that address
into the cUSD ASA. Intended for one-time migrations.
"""
import base64
import json
from pathlib import Path
from typing import Optional

from algosdk import account, encoding, mnemonic, transaction
from algosdk.abi import Contract
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.v2client import algod
from django.conf import settings
from django.core.management.base import BaseCommand

from blockchain.kms_manager import KMSTransactionSigner, get_kms_signer_from_settings


class Command(BaseCommand):
    help = "Transfer cUSD app admin to the KMS-backed sponsor address and opt it into the cUSD asset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--new-admin",
            dest="new_admin",
            help="Algorand address to set as the new admin (defaults to ALGORAND_SPONSOR_ADDRESS)",
        )
        parser.add_argument(
            "--skip-optin",
            action="store_true",
            help="Skip the ASA opt-in step for the new admin address.",
        )

    def _get_current_admin(self, client: algod.AlgodClient, app_id: int) -> Optional[str]:
        """Read current admin address from global state."""
        try:
            info = client.application_info(app_id)
            gstate = {kv["key"]: kv["value"] for kv in info["params"].get("global-state", [])}
            key = base64.b64encode(b"admin").decode()
            raw = gstate.get(key)
            if not raw or "bytes" not in raw:
                return None
            addr_bytes = base64.b64decode(raw["bytes"])
            if len(addr_bytes) == 32:
                return encoding.encode_address(addr_bytes)
            # Fallback: return raw bytes decoded for visibility
            return addr_bytes.decode(errors="ignore")
        except Exception:
            return None

    def handle(self, *args, **options):
        app_id = getattr(settings, "ALGORAND_CUSD_APP_ID", None)
        asset_id = getattr(settings, "ALGORAND_CUSD_ASSET_ID", None)
        algod_addr = getattr(settings, "ALGORAND_ALGOD_ADDRESS", None)
        algod_token = getattr(settings, "ALGORAND_ALGOD_TOKEN", "")
        admin_mnemonic = getattr(settings, "ALGORAND_ADMIN_MNEMONIC", None)
        new_admin = options.get("new_admin") or getattr(settings, "ALGORAND_SPONSOR_ADDRESS", None)
        skip_optin = options.get("skip_optin", False)

        if not app_id or not asset_id or not algod_addr:
            self.stdout.write(self.style.ERROR("Missing ALGORAND_CUSD_APP_ID/ALGORAND_CUSD_ASSET_ID/ALGORAND_ALGOD_ADDRESS"))
            return
        if not new_admin:
            self.stdout.write(self.style.ERROR("New admin address not provided and ALGORAND_SPONSOR_ADDRESS is unset"))
            return

        client = algod.AlgodClient(algod_token, algod_addr)

        # Load ABI contract
        try:
            abi_path = Path("contracts/cusd/contract.json")
            contract_json = json.loads(abi_path.read_text())
            contract = Contract.from_json(json.dumps(contract_json))
            method_update = contract.get_method_by_name("update_admin")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Failed to load cUSD ABI: {exc}"))
            return

        # Resolve current admin signer (prefer KMS admin if configured)
        admin_signer = None
        admin_addr = None
        if admin_mnemonic:
            admin_sk = mnemonic.to_private_key(admin_mnemonic)
            admin_addr = account.address_from_private_key(admin_sk)
            admin_signer = AccountTransactionSigner(admin_sk)
            signer_label = "mnemonic"
        else:
            kms_admin = get_kms_signer_from_settings(role="admin")
            admin_addr = kms_admin.address
            admin_signer = KMSTransactionSigner(kms_admin)
            signer_label = "KMS(admin)"

        self.stdout.write(f"Current admin signer ({signer_label}): {admin_addr}")
        self.stdout.write(f"Target new admin:    {new_admin}")
        current_admin_onchain = self._get_current_admin(client, int(app_id))
        if current_admin_onchain:
            self.stdout.write(f"On-chain admin:      {current_admin_onchain}")

        # Step 1: Transfer admin if needed
        if current_admin_onchain == new_admin:
            self.stdout.write(self.style.SUCCESS("Admin already set to target address; skipping update_admin"))
        else:
            try:
                sp = client.suggested_params()
                sp.flat_fee = True
                sp.fee = 2000  # cover single app call
                atc = AtomicTransactionComposer()
                atc.add_method_call(
                    app_id=int(app_id),
                    method=method_update,
                    sender=admin_addr,
                    sp=sp,
                    signer=admin_signer,
                    method_args=[new_admin],
                )
                res = atc.execute(client, 4)
                txid = res.tx_ids[0] if getattr(res, "tx_ids", None) else "unknown"
                self.stdout.write(self.style.SUCCESS(f"Admin transferred to {new_admin}. TxID: {txid}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Failed to transfer admin: {exc}"))
                return

        # Step 2: Opt-in new admin to cUSD ASA (asset_id)
        if skip_optin:
            self.stdout.write("Opt-in step skipped by flag.")
            return

        try:
            client.account_asset_info(new_admin, int(asset_id))
            self.stdout.write(self.style.SUCCESS("New admin already opted into cUSD asset; skipping opt-in"))
            return
        except Exception:
            pass

        try:
            kms_signer = KMSTransactionSigner(get_kms_signer_from_settings())
            sp = client.suggested_params()
            sp.flat_fee = True
            sp.fee = 1000  # min fee
            optin_txn = transaction.AssetTransferTxn(
                sender=new_admin,
                sp=sp,
                receiver=new_admin,
                amt=0,
                index=int(asset_id),
                note=b"cUSD admin opt-in",
            )
            atc = AtomicTransactionComposer()
            atc.add_transaction(TransactionWithSigner(optin_txn, kms_signer))
            res = atc.execute(client, 4)
            txid = res.tx_ids[0] if getattr(res, "tx_ids", None) else "unknown"
            self.stdout.write(self.style.SUCCESS(f"Opted new admin into cUSD ASA {asset_id}. TxID: {txid}"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Failed to opt new admin into cUSD asset: {exc}"))
