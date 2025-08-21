"""
Mint cUSD via treasury-backed admin method and send to a recipient.

Usage:
  python manage.py mint_cusd_admin --amount 4000 --recipient <ALGOWALLET>

Notes:
- Uses ALGORAND testnet/mainnet per settings.
- Signs with ALGORAND_SPONSOR_MNEMONIC (must be the admin of the cUSD app on testnet).
- Assumes recipient has already opted in to the cUSD ASA.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from algosdk import mnemonic
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
)
from algosdk.v2client import algod
from algosdk.abi import Contract
from algosdk.transaction import ApplicationOptInTxn, wait_for_confirmation, PaymentTxn
from algosdk.atomic_transaction_composer import TransactionWithSigner
from algosdk.logic import get_application_address


class Command(BaseCommand):
    help = 'Mint cUSD using the treasury-backed admin method to a recipient address.'

    def add_arguments(self, parser):
        parser.add_argument('--amount', type=Decimal, required=True, help='Amount of cUSD to mint (e.g., 4000)')
        parser.add_argument('--recipient', type=str, required=True, help='Recipient Algorand address')

    def handle(self, *args, **options):
        amount: Decimal = options['amount']
        recipient: str = options['recipient']

        # Validate settings
        app_id = getattr(settings, 'ALGORAND_CUSD_APP_ID', None)
        asa_id = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None)
        algod_addr = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
        algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)

        if not app_id:
            self.stdout.write(self.style.ERROR('ALGORAND_CUSD_APP_ID not configured'))
            return
        if not asa_id:
            self.stdout.write(self.style.ERROR('ALGORAND_CUSD_ASSET_ID not configured'))
            return
        if not algod_addr:
            self.stdout.write(self.style.ERROR('ALGORAND_ALGOD_ADDRESS not configured'))
            return
        if not sponsor_mn:
            self.stdout.write(self.style.ERROR('ALGORAND_SPONSOR_MNEMONIC not configured'))
            self.stdout.write('Set ALGORAND_SPONSOR_MNEMONIC to the admin/sponsor mnemonic for testnet.')
            return

        # Derive admin/sponsor account
        try:
            sk = mnemonic.to_private_key(sponsor_mn)
            from algosdk import account
            sender = account.address_from_private_key(sk)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to derive sponsor key: {e}'))
            return

        # Build algod client
        client = algod.AlgodClient(algod_token, algod_addr)

        # Load cUSD app ABI to call mint_admin
        try:
            import json
            from pathlib import Path
            abi_path = Path('contracts/cusd/contract.json')
            with abi_path.open('r') as f:
                contract_json = json.load(f)
            # Contract.from_json expects a JSON string, not a dict
            contract = Contract.from_json(json.dumps(contract_json))
            method = contract.get_method_by_name('mint_admin')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to load cUSD ABI: {e}'))
            return

        # Convert to micro units (6 decimals)
        amt_micro = int(amount * Decimal('1000000'))

        # Suggested params with flat fee for predictable cost
        sp = client.suggested_params()
        sp.flat_fee = True
        sp.fee = 2000  # 2x min fee for 1 inner txn

        # If minting to self (sponsor/admin), ensure address is opted into app first
        if recipient == sender:
            try:
                acct_info = client.account_info(sender)
                opted_in = any(s.get('id') == int(app_id) for s in acct_info.get('apps-local-state', []))
            except Exception:
                opted_in = False
            if not opted_in:
                self.stdout.write('Opting sponsor/admin into cUSD application...')
                try:
                    from algosdk import transaction as txn_mod
                    # Use ABI method call for opt-in so the selector is present in args
                    method_optin = contract.get_method_by_name('opt_in')
                    atc_opt = AtomicTransactionComposer()
                    signer = AccountTransactionSigner(sk)
                    opt_params = client.suggested_params()
                    atc_opt.add_method_call(
                        app_id=int(app_id),
                        method=method_optin,
                        sender=sender,
                        sp=opt_params,
                        signer=signer,
                        method_args=[],
                        on_complete=txn_mod.OnComplete.OptInOC
                    )
                    res = atc_opt.execute(client, 4)
                    txid = res.tx_ids[0] if getattr(res, 'tx_ids', None) else 'unknown'
                    self.stdout.write(self.style.SUCCESS(f'✅ Opt-in complete. TxID: {txid}'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Failed to opt-in sponsor/admin to app: {e}'))
                    return

        # Ensure app has assets configured (setup_assets)
        try:
            app_info = client.application_info(int(app_id))
            gstate = { (gs['key']): gs['value'] for gs in app_info['params'].get('global-state', []) }
            import base64
            def get_uint(key: str):
                b64 = base64.b64encode(key.encode()).decode()
                v = gstate.get(b64)
                return int(v.get('uint', 0)) if v else 0
            cusd_set = get_uint('cusd_asset_id')
            usdc_set = get_uint('usdc_asset_id')
        except Exception:
            cusd_set = 0
            usdc_set = 0

        # Only run setup_assets if not configured
        if not (int(cusd_set) == int(asa_id) and int(usdc_set) == int(settings.ALGORAND_USDC_ASSET_ID)):
            self.stdout.write('Setting up assets in cUSD application (setup_assets)...')
            try:
                method_setup = contract.get_method_by_name('setup_assets')
                atc_setup = AtomicTransactionComposer()
                signer = AccountTransactionSigner(sk)
                # Payment to app for min balance + fees (~0.6 ALGO as per docs)
                app_addr = get_application_address(int(app_id))
                pay_sp = client.suggested_params()
                pay_txn = PaymentTxn(sender=sender, sp=pay_sp, receiver=app_addr, amt=int(0.7 * 1_000_000))
                atc_setup.add_transaction(TransactionWithSigner(pay_txn, signer))
                call_sp = client.suggested_params()
                call_sp.flat_fee = True
                call_sp.fee = 2000
                atc_setup.add_method_call(
                    app_id=int(app_id),
                    method=method_setup,
                    sender=sender,
                    sp=call_sp,
                    signer=signer,
                    method_args=[int(asa_id), int(settings.ALGORAND_USDC_ASSET_ID)],
                )
                res = atc_setup.execute(client, 4)
                txid = res.tx_ids[-1] if getattr(res, 'tx_ids', None) else 'unknown'
                self.stdout.write(self.style.SUCCESS(f'✅ setup_assets complete. TxID: {txid}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to setup assets: {e}'))
                return

        self.stdout.write(self.style.SUCCESS('\n=== cUSD Admin Mint (Treasury-backed) ==='))
        self.stdout.write(f'Network: {algod_addr}')
        self.stdout.write(f'App ID: {app_id}')
        self.stdout.write(f'ASA ID (cUSD): {asa_id}')
        self.stdout.write(f'Sender (admin/sponsor): {sender[:12]}...')
        self.stdout.write(f'Recipient: {recipient[:12]}...')
        self.stdout.write(f'Amount: {amount} cUSD ({amt_micro} micro)')

        try:
            atc = AtomicTransactionComposer()
            signer = AccountTransactionSigner(sk)
            atc.add_method_call(
                app_id=int(app_id),
                method=method,
                sender=sender,
                sp=sp,
                signer=signer,
                method_args=[amt_micro, recipient],
                accounts=[recipient],
                foreign_assets=[int(asa_id), int(settings.ALGORAND_USDC_ASSET_ID)]
            )

            result = atc.execute(client, 4)
            txid = result.tx_ids[0] if getattr(result, 'tx_ids', None) else 'unknown'

            self.stdout.write(self.style.SUCCESS('\n✅ Mint submitted'))
            self.stdout.write(f'TxID: {txid}')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Mint failed: {e}'))
            return
