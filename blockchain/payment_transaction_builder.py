"""
Payment Transaction Builder for Confío
Handles sponsored payments through the payment smart contract
"""

import os
from typing import Optional, Tuple, List
from algosdk import transaction, encoding, logic
from algosdk.v2client import algod
from algosdk.abi import Method, Returns, Argument
import base64

class PaymentTransactionBuilder:
    """Builds sponsored payment transactions through the payment contract"""
    
    def __init__(self, network: str = 'testnet'):
        self.network = network
        
        # Network configuration
        if network == 'testnet':
            self.algod_address = "https://testnet-api.algonode.cloud"
            self.algod_token = ""
        else:  # localnet
            self.algod_address = "http://localhost:4001"
            self.algod_token = "a" * 64
        
        # Initialize Algod client
        self.algod_client = algod.AlgodClient(self.algod_token, self.algod_address)
        
        # Contract and asset IDs from environment
        self.payment_app_id = int(os.environ.get('ALGORAND_PAYMENT_APP_ID', '744210766'))
        self.cusd_asset_id = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '744192921'))
        self.confio_asset_id = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '744150851'))
        
        # Sponsor configuration
        self.sponsor_address = os.environ.get('ALGORAND_SPONSOR_ADDRESS', 
            'PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY')
        
        # Get app address
        self.app_address = logic.get_application_address(self.payment_app_id)
    
    def build_sponsored_payment(
        self,
        sender_address: str,
        recipient_address: str,
        amount: int,
        asset_id: int,
        payment_id: Optional[str] = None,
        note: Optional[str] = None
    ) -> Tuple[List[transaction.Transaction], List[int]]:
        """
        Build a sponsored payment transaction group
        
        Args:
            sender_address: User's Algorand address (payer)
            recipient_address: Recipient's Algorand address
            amount: Amount to send in base units (6 decimals for cUSD/CONFIO)
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
        
        # Calculate if we need a receipt (payment_id provided)
        needs_receipt = payment_id is not None and len(payment_id) > 0
        
        if needs_receipt:
            # With receipt: need MBR payment first
            # Box MBR = 2500 + 400 * (43 + 96) = 58,100 microAlgos
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
        
        # Asset transfer transaction (user sends tokens to app)
        asset_params = params.copy()
        asset_params.fee = 0  # User pays no fee in sponsored mode
        
        asset_transfer = transaction.AssetTransferTxn(
            sender=sender_address,
            sp=asset_params,
            receiver=self.app_address,
            amt=amount,
            index=asset_id,
            note=note.encode() if note else None
        )
        transactions.append(asset_transfer)
        user_signing_indexes.append(len(transactions) - 1)
        
        # App call from sponsor
        app_params = params.copy()
        app_params.fee = 2000  # Sponsor covers fees for group + inner transaction
        
        # Prepare method arguments
        method_args = [
            len(transactions) - 1,  # Reference to the asset transfer transaction
            encoding.decode_address(recipient_address),  # Recipient address
            payment_id.encode() if payment_id else b""  # Payment ID (empty if none)
        ]
        
        # Build box references if needed
        box_refs = []
        if needs_receipt:
            # Box key format: "p:" + asset_id (8 bytes) + ":" + sha256(payment_id)
            import hashlib
            key_prefix = b"p:" + asset_id.to_bytes(8, 'big') + b":"
            payment_hash = hashlib.sha256(payment_id.encode()).digest()
            box_key = key_prefix + payment_hash
            box_refs.append((self.payment_app_id, box_key))
            
            # Increase fee for box reference
            app_params.fee = 4500  # Higher fee for box operations
        
        app_call = transaction.ApplicationCallTxn(
            sender=self.sponsor_address,  # SPONSOR sends the app call
            sp=app_params,
            index=self.payment_app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[method.get_selector()] + [
                base64.b64encode(arg).decode() if isinstance(arg, bytes) else arg 
                for arg in method_args
            ],
            accounts=[sender_address, recipient_address],  # Include both accounts
            foreign_assets=[asset_id],  # Include the asset being transferred
            boxes=box_refs if box_refs else None
        )
        transactions.append(app_call)
        # Sponsor signs this, not included in user signing indexes
        
        # Group transactions
        transaction.assign_group_id(transactions)
        
        return transactions, user_signing_indexes
    
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
        app_params = params.copy()
        app_params.fee = 2000 if not needs_receipt else 4500  # Higher fee for box operations
        
        # Prepare method arguments
        method_args = [
            len(transactions) - 1,  # Reference to the asset transfer transaction
            encoding.decode_address(recipient_address),
            payment_id.encode() if payment_id else b""
        ]
        
        # Build box references if needed
        box_refs = []
        if needs_receipt:
            import hashlib
            key_prefix = b"p:" + asset_id.to_bytes(8, 'big') + b":"
            payment_hash = hashlib.sha256(payment_id.encode()).digest()
            box_key = key_prefix + payment_hash
            box_refs.append((self.payment_app_id, box_key))
        
        app_call = transaction.ApplicationCallTxn(
            sender=sender_address,  # User sends the app call
            sp=app_params,
            index=self.payment_app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[method.get_selector()] + [
                base64.b64encode(arg).decode() if isinstance(arg, bytes) else arg 
                for arg in method_args
            ],
            accounts=[sender_address, recipient_address],
            foreign_assets=[asset_id],
            boxes=box_refs if box_refs else None
        )
        transactions.append(app_call)
        user_signing_indexes.append(len(transactions) - 1)
        
        # Group transactions
        transaction.assign_group_id(transactions)
        
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