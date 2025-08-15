"""
Payment Transaction Builder for Confío
Handles sponsored payments through the payment smart contract
"""

import os
from typing import Optional, Tuple, List, Dict
from algosdk import transaction, encoding, logic
from algosdk.transaction import SuggestedParams
from algosdk.v2client import algod
from algosdk.abi import Method, Returns, Argument
import base64
from django.conf import settings

class PaymentTransactionBuilder:
    """Builds sponsored payment transactions through the payment contract"""
    
    def __init__(self, network: str = 'testnet'):
        self.network = network
        
        # Always use Django settings for Algod configuration
        # This allows switching providers (e.g., Nodely, Algonode, localnet)
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = settings.ALGORAND_ALGOD_TOKEN
        
        # Initialize Algod client
        self.algod_client = algod.AlgodClient(self.algod_token, self.algod_address)
        
        # Contract and asset IDs from Django settings - MUST be in .env
        self.payment_app_id = settings.BLOCKCHAIN_CONFIG['ALGORAND_PAYMENT_APP_ID']
        self.cusd_asset_id = settings.BLOCKCHAIN_CONFIG['ALGORAND_CUSD_ASSET_ID']
        self.confio_asset_id = settings.BLOCKCHAIN_CONFIG['ALGORAND_CONFIO_ASSET_ID']
        
        # Sponsor configuration - MUST be set in environment
        self.sponsor_address = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_ADDRESS')
        if not self.sponsor_address:
            raise ValueError("ALGORAND_SPONSOR_ADDRESS not configured. Must be set in environment variables.")
        
        # Debug logging for sponsor address
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"PaymentTransactionBuilder initialized with sponsor address: {self.sponsor_address}")
        logger.info(f"Algod endpoint: {self.algod_address}")
        
        # Get app address
        self.app_address = logic.get_application_address(self.payment_app_id)
    
    def build_sponsored_payment_cusd_style(
        self,
        sender_address: str,
        recipient_address: str,
        amount: int,
        asset_id: int,
        payment_id: Optional[str] = None,
        note: Optional[str] = None
    ):
        """
        Build a sponsored payment transaction group with direct payments and fee split
        
        Transaction structure (4 txns with fee enforcement):
        [Payment(sponsor→payer,0), AXFER(payer→merchant), AXFER(payer→fee_recipient), AppCall(sponsor)]
        
        Args:
            sender_address: User's Algorand address (payer)
            recipient_address: Recipient's Algorand address (merchant)
            amount: Total amount to send in base units (6 decimals for cUSD/CONFIO)
            asset_id: Asset ID (cUSD or CONFIO)
            payment_id: Not used (kept for compatibility)
            note: Optional transaction note
        
        Returns:
            Dict with transactions and metadata like cUSD pattern
        """
        
        try:
            # Set up logger first
            import logging
            logger = logging.getLogger(__name__)
            
            # Validate asset
            if asset_id not in [self.cusd_asset_id, self.confio_asset_id]:
                return {
                    'success': False,
                    'error': f"Invalid asset ID. Must be cUSD ({self.cusd_asset_id}) or CONFIO ({self.confio_asset_id})"
                }
            
            # Get suggested parameters
            params = self.algod_client.suggested_params()
            
            # Determine method based on asset
            if asset_id == self.cusd_asset_id:
                method_name = "pay_with_cusd"
            else:
                method_name = "pay_with_confio"

            # Preflight checks to mirror on-chain assertions for clearer failures
            # 0) Validate sponsor address matches on-chain config
            app_info = self.algod_client.application_info(self.payment_app_id)
            global_state = {base64.b64decode(e["key"]).decode(): e["value"] for e in app_info["params"]["global-state"]}
            sp_b64 = global_state.get("sponsor_address", {}).get("bytes")
            onchain_sponsor = encoding.encode_address(base64.b64decode(sp_b64)) if sp_b64 else ""
            if onchain_sponsor != self.sponsor_address:
                return {
                    'success': False,
                    'error': f"Payment app sponsor mismatch: on-chain={onchain_sponsor}, backend={self.sponsor_address}. Run set_sponsor for app {self.payment_app_id}."
                }
            
            # 1) App must be opted-in to the asset (setup_assets done)
            try:
                _ = self.algod_client.account_asset_info(self.app_address, asset_id)
            except Exception:
                return {
                    'success': False,
                    'error': f"Payment app {self.payment_app_id} is not opted-in to asset {asset_id}. Run setup_assets for the payment app before sending payments."
                }
            
            # 2) Recipient must be opted-in to the asset (inner transfer requires it)
            skip_recipient_check = bool(settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SKIP_RECIPIENT_OPTIN_CHECK', False))
            if not skip_recipient_check:
                try:
                    _ = self.algod_client.account_asset_info(recipient_address, asset_id)
                except Exception:
                    return {
                        'success': False,
                        'error': f"Recipient {recipient_address} is not opted-in to asset {asset_id}. Ask the recipient to opt-in to the asset before paying."
                    }
            else:
                import logging
                logging.getLogger(__name__).warning(
                    "Skipping recipient opt-in preflight check by configuration. "
                    "If recipient is not opted-in, the on-chain inner transfer will fail."
                )
            
            # Create method selector for simplified 2-arg signature
            # The new contract accesses transactions directly by group index
            from algosdk.abi import Method, Returns, Argument
            method = Method(
                name=method_name,
                args=[
                    Argument(arg_type="address", name="recipient"),
                    Argument(arg_type="string", name="payment_id")
                ],
                returns=Returns(arg_type="void")
            )
            
            # Calculate fee split (0.9% = 90 basis points)
            FEE_BPS = 90
            BASIS_POINTS = 10000
            
            # Calculate fee amount (using ceiling division for exact match with contract)
            fee_amount = (amount * FEE_BPS + BASIS_POINTS - 1) // BASIS_POINTS
            net_amount = amount - fee_amount
            
            # Ensure positive amounts
            if net_amount <= 0 or fee_amount <= 0:
                return {
                    'success': False,
                    'error': f"Amount too small to process. Net: {net_amount}, Fee: {fee_amount}"
                }
            
            logger.info(f"Payment split - Total: {amount}, Net to merchant: {net_amount}, Fee: {fee_amount}")
            
            # Get fee recipient from contract global state
            app_info = self.algod_client.application_info(self.payment_app_id)
            global_state = {base64.b64decode(e["key"]).decode(): e["value"] for e in app_info["params"]["global-state"]}
            fee_recipient_b64 = global_state.get("fee_recipient", {}).get("bytes")
            if not fee_recipient_b64:
                return {
                    'success': False,
                    'error': f"Payment app {self.payment_app_id} has no fee_recipient configured"
                }
            fee_recipient = encoding.encode_address(base64.b64decode(fee_recipient_b64))
            logger.info(f"Fee recipient: {fee_recipient}")
            
            # Get current balances and check MBR requirement
            account_info = self.algod_client.account_info(sender_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            # Calculate MBR top-up needed (atomic with payment for security)
            mbr_topup = 0
            if current_balance < min_balance_required:
                mbr_topup = min(min_balance_required - current_balance, 100_000)  # Cap at 0.1 ALGO
                logger.info(f"MBR top-up needed: {mbr_topup} microAlgos")
            
            # Fee planning
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            sponsor_payment_fee = min_fee * 3   # Pays for itself + 2 user AXFERs
            # Some deployed approvals may require extra budget; use 2x min fee
            app_call_fee = min_fee * 2           # App call funds base + headroom
            
            # Transaction 0: Sponsor payment (MUST be first per contract requirements)
            sponsor_params = SuggestedParams(
                fee=sponsor_payment_fee,  # Covers 3 transactions
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            sponsor_payment = transaction.PaymentTxn(
                sender=self.sponsor_address,
                sp=sponsor_params,
                receiver=sender_address,
                amt=mbr_topup,  # 0 or MBR top-up (max 0.1 ALGO per contract)
                note=b"Sponsored payment with MBR" if mbr_topup > 0 else b"Sponsored payment"
            )
            
            # Transaction 1: Asset transfer from user to MERCHANT (0 fee - sponsored)
            asset_params = SuggestedParams(
                fee=0,  # Sponsored by payment transaction
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            merchant_transfer = transaction.AssetTransferTxn(
                sender=sender_address,
                sp=asset_params,
                receiver=recipient_address,  # Direct to merchant!
                amt=net_amount,  # Net amount after fee
                index=asset_id
            )
            
            # Transaction 2: Asset transfer from user to FEE RECIPIENT (0 fee - sponsored)
            fee_transfer = transaction.AssetTransferTxn(
                sender=sender_address,
                sp=asset_params,  # Same params, 0 fee
                receiver=fee_recipient,  # To fee treasury
                amt=fee_amount,  # Fee amount
                index=asset_id
            )
            
            # Transaction 3: App call (SENT BY SPONSOR)
            app_params = SuggestedParams(
                fee=app_call_fee,  # App call MUST fund its inner transaction budget
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Get the ABI method selector
            selector = method.get_selector()
            
            # Log critical details before building app call
            logger.info(f"=== PAYMENT APP CALL DETAILS (4-TXN GROUP) ===")
            logger.info(f"App call sender (sponsor): {self.sponsor_address}")
            logger.info(f"Payment app ID: {self.payment_app_id}")
            logger.info(f"Accounts array: [0]={sender_address}, [1]={recipient_address}")
            logger.info(f"Fee recipient: {fee_recipient}")
            logger.info(f"Asset ID: {asset_id}")
            logger.info(f"Method: {method_name}")
            logger.info(f"Total amount: {amount}, Net: {net_amount}, Fee: {fee_amount}")
            logger.info(f"===============================================")
            
            # Properly ABI-encode the arguments
            from algosdk.abi import ABIType
            string_type = ABIType.from_string("string")
            
            # Encode the arguments
            recipient_arg = encoding.decode_address(recipient_address)  # Address is just 32 bytes
            payment_id_arg = string_type.encode(payment_id if payment_id else "")  # String needs ABI encoding
            
            # SPONSOR sends the app call (true sponsorship)
            # The deployed contract's caster reads recipient from app_args[1] and payment_id from app_args[2]
            # Transaction references are computed automatically by the caster from group structure
            app_call = transaction.ApplicationCallTxn(
                sender=self.sponsor_address,  # SPONSOR is sender!
                sp=app_params,
                index=self.payment_app_id,
                on_complete=transaction.OnComplete.NoOpOC,
                # The caster expects only recipient and payment_id, no transaction references
                app_args=[
                    selector,
                    recipient_arg,  # Recipient address at app_args[1] (32 bytes)
                    payment_id_arg  # ABI-encoded payment ID at app_args[2]
                ],
                accounts=[sender_address, recipient_address],  # Pass user and recipient as account references
                foreign_assets=[asset_id]
            )
            
            # Group transactions: [sponsor_payment, merchant_transfer, fee_transfer, app_call]
            # Order MUST match contract expectations!
            group_id = transaction.calculate_group_id([sponsor_payment, merchant_transfer, fee_transfer, app_call])
            sponsor_payment.group = group_id
            merchant_transfer.group = group_id
            fee_transfer.group = group_id
            app_call.group = group_id
            
            # Sign sponsor transactions if we have the key
            from algosdk import mnemonic
            from algosdk import encoding as algo_encoding
            sponsor_payment_signed = None
            app_call_signed = None
            
            sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if sponsor_mnemonic:
                sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
                sponsor_payment_signed = algo_encoding.msgpack_encode(sponsor_payment.sign(sponsor_private_key))
                app_call_signed = algo_encoding.msgpack_encode(app_call.sign(sponsor_private_key))
            
            # Encode transactions for client - user signs BOTH asset transfers (index 1 and 2)
            transactions_to_sign = [
                {
                    'txn': algo_encoding.msgpack_encode(merchant_transfer),
                    'signers': [sender_address],
                    'message': f'Payment to merchant ({net_amount} micro-units)'
                },
                {
                    'txn': algo_encoding.msgpack_encode(fee_transfer),
                    'signers': [sender_address],
                    'message': f'Fee payment ({fee_amount} micro-units)'
                }
            ]
            
            return {
                'success': True,
                'transactions_to_sign': transactions_to_sign,
                'sponsor_transactions': [
                    {
                        'txn': algo_encoding.msgpack_encode(sponsor_payment),
                        'signed': sponsor_payment_signed,
                        'index': 0  # Sponsor payment at index 0
                    },
                    {
                        'txn': algo_encoding.msgpack_encode(app_call),
                        'signed': app_call_signed,
                        'index': 3  # Sponsor app call at index 3 (last in 4-txn group)
                    }
                ],
                'group_id': base64.b64encode(group_id).decode('utf-8'),
                'total_fee': str(sponsor_payment_fee + app_call_fee),  # Total fees (4 * min_fee)
                'payment_amount': str(amount),
                'net_amount': str(net_amount),
                'fee_amount': str(fee_amount)
            }
            
        except Exception as e:
            import traceback
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error building payment transactions: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }

    def validate_payment_app(self, asset_id: int) -> dict:
        """Preflight checks for payment app compatibility and configuration.

        Returns a dict: {success: bool, error?: str, info?: dict}
        """
        try:
            app_info = self.algod_client.application_info(self.payment_app_id)
            params = app_info.get('params', {})
            # Decode global state to a readable map
            import base64, hashlib
            def decode_key(b64k: str) -> str:
                try:
                    return base64.b64decode(b64k).decode('utf-8')
                except Exception:
                    return ''
            gstate = params.get('global-state', [])
            state_map = {decode_key(e.get('key', '')): e.get('value', {}) for e in gstate}

            def get_uint(name: str) -> int:
                v = state_map.get(name)
                if isinstance(v, dict) and v.get('type') == 2:
                    return int(v.get('uint', 0))
                return 0

            def get_addr_from_bytes(name: str) -> str:
                from algosdk import encoding
                v = state_map.get(name)
                if isinstance(v, dict) and v.get('type') == 1:  # bytes
                    b = base64.b64decode(v.get('bytes', ''))
                    if len(b) == 32:
                        return encoding.encode_address(b)
                return ''

            confio_id = get_uint('confio_asset_id')
            cusd_id = get_uint('cusd_asset_id')
            fee_recipient = get_addr_from_bytes('fee_recipient')
            onchain_sponsor = get_addr_from_bytes('sponsor_address')

            # Basic sanity checks
            if not onchain_sponsor:
                return {'success': False, 'error': f'Payment app {self.payment_app_id} has no sponsor configured'}
            if onchain_sponsor != self.sponsor_address:
                return {
                    'success': False,
                    'error': (
                        f'Payment app sponsor mismatch: on-chain={onchain_sponsor}, '
                        f'backend={self.sponsor_address}. Run set_sponsor for app {self.payment_app_id}.'
                    )
                }
            if not fee_recipient:
                return {'success': False, 'error': f'Payment app {self.payment_app_id} has no fee_recipient configured'}
            if confio_id == 0 and cusd_id == 0:
                return {'success': False, 'error': 'Payment app has no assets configured (run setup_assets)'}
            if asset_id not in (confio_id, cusd_id):
                return {'success': False, 'error': f'Asset {asset_id} not configured in payment app (confio={confio_id}, cusd={cusd_id})'}

            # App must be opted-in to the asset
            try:
                _ = self.algod_client.account_asset_info(self.app_address, asset_id)
            except Exception as e:
                return {'success': False, 'error': f'Payment app not opted-in to asset {asset_id}: {e}'}

            # Hash approval program for diagnostics
            approval_b64 = params.get('approval-program')
            approval_sha256 = ''
            if approval_b64:
                try:
                    ab = base64.b64decode(approval_b64)
                    approval_sha256 = hashlib.sha256(ab).hexdigest()
                except Exception:
                    pass

            return {
                'success': True,
                'info': {
                    'app_id': self.payment_app_id,
                    'confio_asset_id': confio_id,
                    'cusd_asset_id': cusd_id,
                    'fee_recipient': fee_recipient,
                    'sponsor_address': onchain_sponsor,
                    'approval_sha256': approval_sha256,
                }
            }
        except Exception as e:
            return {'success': False, 'error': f'Failed to validate payment app: {e}'}
    
    def build_direct_payment(
        self,
        sender_address: str,
        recipient_address: str,
        amount: int,
        asset_id: int,
        payment_id: Optional[str] = None,
        note: Optional[str] = None
    ) -> Tuple[List[transaction.Transaction], List[int]]:
        """
        Build a direct (non-sponsored) payment transaction group
        User pays all fees themselves
        
        Args:
            sender_address: User's Algorand address (payer)
            recipient_address: Recipient's Algorand address
            amount: Amount to send in base units
            asset_id: Asset ID (cUSD or CONFIO)
            payment_id: Optional payment ID for receipt tracking
            note: Optional transaction note
        
        Returns:
            Tuple of (transactions list, signing indexes for user)
        """
        
        # Validate asset
        if asset_id not in [self.cusd_asset_id, self.confio_asset_id]:
            raise ValueError(f"Invalid asset ID. Must be cUSD ({self.cusd_asset_id}) or CONFIO ({self.confio_asset_id})")
        
        # Get suggested parameters
        params = self.algod_client.suggested_params()
        
        transactions = []
        user_signing_indexes = []
        
        # Determine method based on asset
        if asset_id == self.cusd_asset_id:
            method_name = "pay_with_cusd"
        else:
            method_name = "pay_with_confio"
        
        # Create method selector
        method = Method(
            name=method_name,
            args=[
                Argument(arg_type="axfer", name="payment"),
                Argument(arg_type="address", name="recipient"),
                Argument(arg_type="string", name="payment_id")
            ],
            returns=Returns(arg_type="void")
        )
        
        # Calculate if we need a receipt
        needs_receipt = payment_id is not None and len(payment_id) > 0
        
        if needs_receipt:
            # With receipt: need MBR payment first
            mbr_amount = 58_100
            
            # Transaction 0: User pays MBR to app
            mbr_payment = transaction.PaymentTxn(
                sender=sender_address,
                sp=params,
                receiver=self.app_address,
                amt=mbr_amount,
                note=note.encode() if note else None
            )
            transactions.append(mbr_payment)
            user_signing_indexes.append(0)
        
        # Asset transfer transaction
        asset_transfer = transaction.AssetTransferTxn(
            sender=sender_address,
            sp=params,
            receiver=self.app_address,
            amt=amount,
            index=asset_id,
            note=note.encode() if note else None
        )
        transactions.append(asset_transfer)
        user_signing_indexes.append(len(transactions) - 1)
        
        # App call from user
        # Create new params for app call
        app_params = SuggestedParams(
            fee=2000 if not needs_receipt else 4500,  # Higher fee for box operations
            first=params.first,
            last=params.last,
            gh=params.gh,
            gen=params.gen,
            flat_fee=True
        )
        
        # Build box references if needed
        box_refs = []
        if needs_receipt:
            import hashlib
            key_prefix = b"p:" + asset_id.to_bytes(8, 'big') + b":"
            payment_hash = hashlib.sha256(payment_id.encode()).digest()
            box_key = key_prefix + payment_hash
            box_refs.append((self.payment_app_id, box_key))
        
        # ABI encoding: transaction reference
        txn_ref_index = len(transactions) - 1  # Reference the asset transfer
        
        app_call = transaction.ApplicationCallTxn(
            sender=sender_address,  # User sends the app call
            sp=app_params,
            index=self.payment_app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                method.get_selector(),
                (txn_ref_index).to_bytes(1, 'big'),  # Transaction reference as uint8
                encoding.decode_address(recipient_address),  # Recipient address as bytes
                (payment_id.encode() if payment_id else b"")  # Payment ID as bytes
            ],
            accounts=[sender_address, recipient_address],
            foreign_assets=[asset_id],
            boxes=box_refs if box_refs else None
        )
        transactions.append(app_call)
        user_signing_indexes.append(len(transactions) - 1)
        
        # Group transactions
        transaction.assign_group_id(transactions)
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== SPONSORED PAYMENT TRANSACTION GROUP ===")
        logger.info(f"Sender (payer): {sender_address}")
        logger.info(f"Recipient: {recipient_address}")
        logger.info(f"Sponsor: {self.sponsor_address}")
        logger.info(f"Asset ID: {asset_id}")
        
        for i, txn in enumerate(transactions):
            logger.info(f"Txn {i}: Type={type(txn).__name__}")
            if hasattr(txn, 'sender'):
                logger.info(f"        Sender={txn.sender}")
            if hasattr(txn, 'receiver'):
                logger.info(f"        Receiver={txn.receiver}")
            if hasattr(txn, 'amount'):
                logger.info(f"        Amount={txn.amount}")
            if hasattr(txn, 'index') and txn.index:
                if type(txn).__name__ == 'ApplicationCallTxn':
                    logger.info(f"        AppID={txn.index}")
                else:
                    logger.info(f"        AssetID={txn.index}")
            if hasattr(txn, 'accounts'):
                logger.info(f"        Accounts={txn.accounts}")
            if hasattr(txn, 'fee'):
                logger.info(f"        Fee={txn.fee}")
                
        logger.info(f"User signing indexes: {user_signing_indexes}")
        if len(transactions) > 2:
            logger.info(f"CRITICAL CHECK: Txn[1].sender ({transactions[1].sender}) should equal accounts[0] ({transactions[2].accounts[0] if transactions[2].accounts else 'None'})")
        logger.info(f"==========================================")
        
        return transactions, user_signing_indexes
    
    def calculate_net_amount(self, gross_amount: int) -> Tuple[int, int]:
        """
        Calculate net amount after 0.9% fee
        
        Args:
            gross_amount: Total amount user wants to pay
        
        Returns:
            Tuple of (net_amount, fee_amount)
        """
        fee_bps = 90  # 0.9% = 90 basis points
        basis_points = 10000
        
        fee_amount = (gross_amount * fee_bps) // basis_points
        net_amount = gross_amount - fee_amount
        
        return net_amount, fee_amount
