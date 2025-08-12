"""
Blockchain-related GraphQL mutations
"""
import graphene
import logging
from decimal import Decimal
from typing import Optional
from users.models import Account
from .algorand_account_manager import AlgorandAccountManager
from .algorand_sponsor_service import algorand_sponsor_service
import asyncio

logger = logging.getLogger(__name__)


class EnsureAlgorandReadyMutation(graphene.Mutation):
    """
    Ensures the current user's Algorand account is ready with proper opt-ins.
    This can be called anytime to ensure the user is ready for CONFIO/cUSD operations.
    """
    
    success = graphene.Boolean()
    error = graphene.String()
    algorand_address = graphene.String()
    opted_in_assets = graphene.List(graphene.Int)
    newly_opted_in = graphene.List(graphene.Int)
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Use the AlgorandAccountManager to ensure account is ready
            result = AlgorandAccountManager.ensure_user_algorand_ready(user)
            
            if not result['account']:
                return cls(
                    success=False,
                    error='Failed to setup Algorand account',
                    errors=result['errors']
                )
            
            # Get current opt-ins
            current_opt_ins = AlgorandAccountManager._check_opt_ins(result['algorand_address'])
            
            # Determine newly opted in assets
            newly_opted_in = []
            if result['created']:
                newly_opted_in = result['opted_in_assets']
            
            return cls(
                success=True,
                algorand_address=result['algorand_address'],
                opted_in_assets=current_opt_ins,
                newly_opted_in=newly_opted_in,
                errors=result['errors']
            )
            
        except Exception as e:
            logger.error(f'Error ensuring Algorand ready: {str(e)}')
            return cls(success=False, error=str(e))


class GenerateOptInTransactionsMutation(graphene.Mutation):
    """
    Generate unsigned opt-in transactions for multiple assets.
    Used by frontend after Web3Auth login to opt-in to CONFIO and cUSD.
    """
    
    class Arguments:
        asset_ids = graphene.List(graphene.Int, required=False)  # If not provided, uses default assets
    
    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString()  # List of unsigned transactions with metadata
    
    @classmethod
    def mutate(cls, root, info, asset_ids=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get user's account
            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Generate unsigned transactions
            from algosdk.v2client import algod
            from algosdk.transaction import AssetTransferTxn
            import base64
            import msgpack
            
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            # Check current opt-ins
            account_info = algod_client.account_info(account.algorand_address)
            current_assets = [asset['asset-id'] for asset in account_info.get('assets', [])]
            
            # Default assets if not specified - only include assets user hasn't opted into
            if not asset_ids:
                asset_ids = []
                # Only add CONFIO if it exists and user hasn't opted in
                if AlgorandAccountManager.CONFIO_ASSET_ID and AlgorandAccountManager.CONFIO_ASSET_ID not in current_assets:
                    asset_ids.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                # Only add cUSD if it exists and user hasn't opted in
                if AlgorandAccountManager.CUSD_ASSET_ID and AlgorandAccountManager.CUSD_ASSET_ID not in current_assets:
                    asset_ids.append(AlgorandAccountManager.CUSD_ASSET_ID)
            
            # Filter out assets already opted into
            assets_to_opt_in = [aid for aid in asset_ids if aid not in current_assets]
            
            if not assets_to_opt_in:
                logger.info(f"User already opted into all requested assets")
                return cls(
                    success=True,
                    transactions=[]
                )
            
            # Create atomic sponsored opt-in for all needed assets
            from blockchain.algorand_sponsor_service import algorand_sponsor_service
            from algosdk.transaction import calculate_group_id
            import asyncio
            
            params = algod_client.suggested_params()
            transactions = []
            user_txns = []
            
            # Create opt-in transactions with 0 fee for each asset
            for asset_id in assets_to_opt_in:
                opt_in_txn = AssetTransferTxn(
                    sender=account.algorand_address,
                    sp=params,
                    receiver=account.algorand_address,
                    amt=0,
                    index=asset_id
                )
                opt_in_txn.fee = 0  # User pays no fee
                user_txns.append(opt_in_txn)
            
            # Create sponsor fee payment transaction
            from algosdk.transaction import PaymentTxn
            total_fee = params.min_fee * (len(user_txns) + 1)  # Fee for all txns
            
            fee_payment_txn = PaymentTxn(
                sender=AlgorandAccountManager.SPONSOR_ADDRESS,
                sp=params,
                receiver=account.algorand_address,
                amt=0,  # No ALGO transfer, just paying fees
                note=b"Multi opt-in fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            txn_group = user_txns + [fee_payment_txn]
            group_id = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = group_id
            
            # Sign sponsor transaction
            from algosdk import mnemonic
            sponsor_private_key = mnemonic.to_private_key(AlgorandAccountManager.SPONSOR_MNEMONIC)
            signed_fee_txn = fee_payment_txn.sign(sponsor_private_key)
            
            # Encode transactions for frontend
            for i, (asset_id, user_txn) in enumerate(zip(assets_to_opt_in, user_txns)):
                unsigned_txn = base64.b64encode(
                    msgpack.packb(user_txn.dictify())
                ).decode()
                
                # Determine asset name
                asset_name = "Unknown"
                if asset_id == AlgorandAccountManager.CONFIO_ASSET_ID:
                    asset_name = "CONFIO"
                elif asset_id == AlgorandAccountManager.USDC_ASSET_ID:
                    asset_name = "USDC"
                elif asset_id == AlgorandAccountManager.CUSD_ASSET_ID:
                    asset_name = "cUSD"
                
                transactions.append({
                    'assetId': asset_id,
                    'assetName': asset_name,
                    'transaction': unsigned_txn,
                    'type': 'opt-in'
                })
            
            # Add the signed sponsor transaction
            sponsor_txn_encoded = base64.b64encode(
                msgpack.packb(signed_fee_txn.dictify())
            ).decode()
            
            transactions.append({
                'assetId': 0,  # Not an asset transaction
                'assetName': 'Sponsor Fee',
                'transaction': sponsor_txn_encoded,
                'type': 'sponsor',
                'signed': True  # This one is already signed
            })
            
            logger.info(f"Created atomic opt-in group for {len(assets_to_opt_in)} assets with group ID: {group_id}")
            
            return cls(
                success=True,
                transactions=transactions
            )
            
        except Exception as e:
            logger.error(f'Error generating opt-in transactions: {str(e)}')
            return cls(success=False, error=str(e))


class OptInToAssetMutation(graphene.Mutation):
    """
    Request opt-in to a specific asset (like USDC for traders).
    Note: This generates an unsigned transaction that the user must sign.
    """
    
    class Arguments:
        asset_id = graphene.Int(required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    unsigned_transaction = graphene.String()  # Base64 encoded unsigned transaction
    message = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, asset_id):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get user's account
            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(account.algorand_address)
            assets = account_info.get('assets', [])
            
            if any(asset['asset-id'] == asset_id for asset in assets):
                return cls(
                    success=True,
                    message=f'Already opted into asset {asset_id}'
                )
            
            # Generate unsigned opt-in transaction
            from algosdk.transaction import AssetTransferTxn
            import base64
            import msgpack
            
            params = algod_client.suggested_params()
            
            opt_in_txn = AssetTransferTxn(
                sender=account.algorand_address,
                sp=params,
                receiver=account.algorand_address,
                amt=0,
                index=asset_id
            )
            
            # Encode transaction for client
            unsigned_txn = base64.b64encode(
                msgpack.packb(opt_in_txn.dictify())
            ).decode()
            
            # Determine asset name
            asset_name = "Unknown"
            if asset_id == AlgorandAccountManager.CONFIO_ASSET_ID:
                asset_name = "CONFIO"
            elif asset_id == AlgorandAccountManager.USDC_ASSET_ID:
                asset_name = "USDC"
            elif asset_id == AlgorandAccountManager.CUSD_ASSET_ID:
                asset_name = "cUSD"
            
            return cls(
                success=True,
                unsigned_transaction=unsigned_txn,
                message=f'Please sign this transaction to opt into {asset_name} (Asset ID: {asset_id})'
            )
            
        except Exception as e:
            logger.error(f'Error generating opt-in transaction: {str(e)}')
            return cls(success=False, error=str(e))


class CheckAssetOptInsQuery(graphene.ObjectType):
    """
    Query to check which assets a user is opted into
    """
    algorand_address = graphene.String()
    opted_in_assets = graphene.List(graphene.Int)
    asset_details = graphene.JSONString()
    
    def resolve_algorand_address(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return None
        
        account = Account.objects.filter(
            user=user,
            account_type='personal',
            deleted_at__isnull=True
        ).first()
        
        return account.algorand_address if account else None
    
    def resolve_opted_in_assets(self, info):
        address = self.resolve_algorand_address(info)
        if not address or len(address) != 58:
            return []
        
        return AlgorandAccountManager._check_opt_ins(address)
    
    def resolve_asset_details(self, info):
        opted_in = self.resolve_opted_in_assets(info)
        details = {}
        
        for asset_id in opted_in:
            if asset_id == AlgorandAccountManager.CONFIO_ASSET_ID:
                details[asset_id] = {
                    'name': 'CONFIO',
                    'symbol': 'CONFIO',
                    'decimals': 6
                }
            elif asset_id == AlgorandAccountManager.USDC_ASSET_ID:
                details[asset_id] = {
                    'name': 'USD Coin',
                    'symbol': 'USDC',
                    'decimals': 6
                }
            elif asset_id == AlgorandAccountManager.CUSD_ASSET_ID:
                details[asset_id] = {
                    'name': 'Confío Dollar',
                    'symbol': 'cUSD',
                    'decimals': 6
                }
        
        return details


class AlgorandSponsoredSendMutation(graphene.Mutation):
    """
    Create a sponsored send transaction where the server pays for fees.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    Handles recipient resolution from user_id, phone, or direct address.
    """
    
    class Arguments:
        # Recipient identification - provide ONE of these
        recipient_address = graphene.String(required=False, description="Algorand address (58 chars) for external wallets")
        recipient_user_id = graphene.ID(required=False, description="User ID for Confío recipients")
        recipient_phone = graphene.String(required=False, description="Phone number for any recipient")
        
        amount = graphene.Float(required=True)
        asset_type = graphene.String(required=False, default_value='CUSD')  # CUSD, CONFIO, or USDC
        note = graphene.String(required=False)
    
    success = graphene.Boolean()
    error = graphene.String()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    total_fee = graphene.Int()
    fee_in_algo = graphene.Float()
    transaction_id = graphene.String()  # After submission
    
    @classmethod
    def mutate(cls, root, info, recipient_address=None, recipient_user_id=None, recipient_phone=None, amount=None, asset_type='CUSD', note=None):
        try:
            # Debug logging to see what parameters are received
            logger.info(f"AlgorandSponsoredSend received parameters:")
            logger.info(f"  recipient_address: {recipient_address}")
            logger.info(f"  recipient_user_id: {recipient_user_id}")
            logger.info(f"  recipient_phone: {recipient_phone}")
            logger.info(f"  amount: {amount}")
            logger.info(f"  asset_type: {asset_type}")
            logger.info(f"  note: {note}")
            
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get JWT context for account determination
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not jwt_context:
                return cls(success=False, error='No access or permission to send funds')
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            # Get the sender's account based on JWT context
            if account_type == 'business' and business_id:
                from users.models import Business
                try:
                    business = Business.objects.get(id=business_id)
                    account = Account.objects.get(
                        business=business,
                        account_type='business'
                    )
                except (Business.DoesNotExist, Account.DoesNotExist):
                    return cls(success=False, error='Business account not found')
            else:
                # Personal account
                account = Account.objects.filter(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()
            
            if not account or not account.algorand_address:
                return cls(success=False, error='Sender Algorand address not found')
            
            # Validate sender's address format
            if len(account.algorand_address) != 58:
                return cls(success=False, error='Invalid sender Algorand address format')
            
            # Resolve recipient address based on input type
            # Note: recipient_address might already be set from the parameter
            resolved_recipient_address = None
            
            # Priority 1: User ID lookup (Confío users)
            if recipient_user_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    recipient_user = User.objects.get(id=recipient_user_id)
                    # Get recipient's personal account
                    recipient_account = recipient_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_account and recipient_account.algorand_address:
                        resolved_recipient_address = recipient_account.algorand_address
                        logger.info(f"Resolved recipient address from user_id {recipient_user_id}: {resolved_recipient_address[:10]}...")
                    else:
                        return cls(success=False, error="Recipient's Algorand address not found")
                except User.DoesNotExist:
                    return cls(success=False, error='Recipient user not found')
            
            # Priority 2: Phone number lookup
            elif recipient_phone:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                # Clean phone number - remove all non-digits (normalized format)
                cleaned_phone = ''.join(filter(str.isdigit, recipient_phone))
                logger.info(f"Looking up user by phone: original='{recipient_phone}', cleaned='{cleaned_phone}'")
                
                # Exact match only - phones should be stored normalized (digits only, with country code)
                found_user = User.objects.filter(phone_number=cleaned_phone).first()
                
                if found_user:
                    # Get recipient's personal account
                    recipient_account = found_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_account and recipient_account.algorand_address:
                        resolved_recipient_address = recipient_account.algorand_address
                        logger.info(f"Resolved recipient address from phone {recipient_phone}: {resolved_recipient_address[:10]}...")
                    else:
                        return cls(success=False, error="Recipient's Algorand address not found")
                else:
                    # Non-Confío user - create invitation (not supported for Algorand yet)
                    return cls(success=False, error='Phone number not registered with Confío. Please ask them to sign up first.')
            
            # Priority 3: Direct Algorand address
            elif recipient_address:
                # Validate it's an Algorand address (58 chars, uppercase letters and numbers 2-7)
                import re
                if len(recipient_address) != 58 or not re.match(r'^[A-Z2-7]{58}$', recipient_address):
                    return cls(success=False, error='Invalid recipient Algorand address format')
                resolved_recipient_address = recipient_address
                logger.info(f"Using direct Algorand address: {resolved_recipient_address[:10]}...")
            
            else:
                return cls(success=False, error='Recipient identification required (user_id, phone, or address)')
            
            # Determine asset ID based on type
            asset_id = None
            if asset_type == 'CONFIO':
                asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
            elif asset_type == 'USDC':
                asset_id = AlgorandAccountManager.USDC_ASSET_ID
            elif asset_type == 'CUSD':
                # For now, using USDC as cUSD placeholder
                asset_id = AlgorandAccountManager.USDC_ASSET_ID
            elif asset_type == 'ALGO':
                asset_id = None  # Native ALGO transfer
            else:
                return cls(success=False, error=f'Unsupported asset type: {asset_type}')
            
            # Check if user has opted into the asset (if it's an ASA)
            if asset_id:
                from algosdk.v2client import algod
                algod_client = algod.AlgodClient(
                    AlgorandAccountManager.ALGOD_TOKEN,
                    AlgorandAccountManager.ALGOD_ADDRESS
                )
                
                account_info = algod_client.account_info(account.algorand_address)
                assets = account_info.get('assets', [])
                
                if not any(asset['asset-id'] == asset_id for asset in assets):
                    return cls(
                        success=False,
                        error=f'You need to opt into {asset_type} before sending. Please use the opt-in feature first.'
                    )
                
                # Check balance
                asset_balance = next((asset['amount'] for asset in assets if asset['asset-id'] == asset_id), 0)
                asset_info = algod_client.asset_info(asset_id)
                decimals = asset_info['params'].get('decimals', 0)
                balance_formatted = asset_balance / (10 ** decimals)
                
                if balance_formatted < Decimal(str(amount)):
                    return cls(
                        success=False,
                        error=f'Insufficient {asset_type} balance. You have {balance_formatted} but trying to send {amount}'
                    )
            
            # Create sponsored transaction using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create the sponsored transfer (returns unsigned user txn and signed sponsor txn)
                result = loop.run_until_complete(
                    algorand_sponsor_service.create_sponsored_transfer(
                        sender=account.algorand_address,
                        recipient=resolved_recipient_address,  # Use the resolved address
                        amount=Decimal(str(amount)),
                        asset_id=asset_id,
                        note=note
                    )
                )
            finally:
                loop.close()
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create sponsored transaction'))
            
            # Return the transactions for client signing
            # The client will sign the user transaction and call SubmitSponsoredGroup
            logger.info(
                f"Created sponsored {asset_type} transfer for user {user.id}: "
                f"{amount} from {account.algorand_address[:10]}... to {resolved_recipient_address[:10]}... (awaiting client signature)"
            )
            
            return cls(
                success=True,
                user_transaction=result['user_transaction'],  # Base64 encoded unsigned transaction
                sponsor_transaction=result['sponsor_transaction'],  # Base64 encoded signed transaction
                group_id=result['group_id'],
                total_fee=result['total_fee'],
                fee_in_algo=result['total_fee'] / 1_000_000  # Convert to ALGO
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored send: {str(e)}')
            return cls(success=False, error=str(e))


class SubmitSponsoredGroupMutation(graphene.Mutation):
    """
    Submit a complete sponsored transaction group after client signing.
    """
    
    class Arguments:
        signed_user_txn = graphene.String(required=True)  # Base64 encoded signed user transaction
        signed_sponsor_txn = graphene.String(required=True)  # Base64 encoded signed sponsor transaction
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()
    fees_saved = graphene.Float()
    
    @classmethod
    def mutate(cls, root, info, signed_user_txn, signed_sponsor_txn):
        try:
            logger.info(f"SubmitSponsoredGroupMutation called")
            logger.info(f"User transaction size: {len(signed_user_txn)} chars")
            logger.info(f"Sponsor transaction size: {len(signed_sponsor_txn)} chars")
            
            user = info.context.user
            if not user.is_authenticated:
                logger.warning(f"Unauthenticated request to submit sponsored group")
                return cls(success=False, error='Not authenticated')
            
            logger.info(f"Submitting sponsored group for user {user.id}")
            
            # Submit the sponsored group using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                logger.info(f"Calling algorand_sponsor_service.submit_sponsored_group...")
                result = loop.run_until_complete(
                    algorand_sponsor_service.submit_sponsored_group(
                        signed_user_txn=signed_user_txn,
                        signed_sponsor_txn=signed_sponsor_txn
                    )
                )
                logger.info(f"submit_sponsored_group returned: {result}")
            finally:
                loop.close()
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to submit transaction'))
            
            logger.info(
                f"Submitted sponsored transaction for user {user.id}: "
                f"TxID: {result['tx_id']}, Round: {result['confirmed_round']}"
            )
            
            return cls(
                success=True,
                transaction_id=result['tx_id'],
                confirmed_round=result['confirmed_round'],
                fees_saved=result['fees_saved']
            )
            
        except Exception as e:
            logger.error(f'Error submitting sponsored group: {str(e)}')
            return cls(success=False, error=str(e))



class OptInToAssetByTypeMutation(graphene.Mutation):
    """
    Create a sponsored opt-in transaction for an asset by type name (USDC, CONFIO, CUSD).
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        asset_type = graphene.String(required=True)  # "USDC", "CONFIO", or "CUSD"
    
    success = graphene.Boolean()
    error = graphene.String()
    already_opted_in = graphene.Boolean()
    requires_user_signature = graphene.Boolean()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    asset_id = graphene.Int()
    asset_name = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, asset_type):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Map asset type to asset ID
            asset_type_upper = asset_type.upper()
            if asset_type_upper == 'USDC':
                asset_id = AlgorandAccountManager.USDC_ASSET_ID
            elif asset_type_upper == 'CONFIO':
                asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
            elif asset_type_upper == 'CUSD':
                asset_id = AlgorandAccountManager.CUSD_ASSET_ID
            else:
                return cls(success=False, error=f'Unknown asset type: {asset_type}')
            
            if not asset_id:
                return cls(success=False, error=f'{asset_type} not configured on this network')
            
            # Get user's account
            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Check if account needs additional funding for MBR
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(account.algorand_address)
            current_balance = account_info['amount']  # in microAlgos
            num_assets = len(account_info.get('assets', []))
            
            # Calculate required minimum balance
            # Base: 0.1 ALGO, Per asset: 0.1 ALGO
            # Need one more asset slot for USDC
            required_mbr = 100_000 + ((num_assets + 1) * 100_000)  # in microAlgos
            
            # If balance is insufficient, fund the difference plus a small buffer
            if current_balance < required_mbr:
                funding_needed = required_mbr - current_balance + 10_000  # Add 0.01 ALGO buffer
                logger.info(
                    f"Account needs {funding_needed / 1_000_000} ALGO for USDC opt-in. "
                    f"Current: {current_balance / 1_000_000}, Required: {required_mbr / 1_000_000}"
                )
                
                # Fund the account with the needed amount
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # First fund the account
                    funding_result = loop.run_until_complete(
                        algorand_sponsor_service.fund_account(
                            account.algorand_address,
                            funding_needed
                        )
                    )
                    
                    if not funding_result.get('success'):
                        logger.error(f"Failed to fund account: {funding_result.get('error')}")
                        return cls(success=False, error='Failed to fund account for opt-in')
                    
                    logger.info(f"Successfully funded account with {funding_needed / 1_000_000} ALGO")
                    
                    # Now execute the opt-in
                    result = loop.run_until_complete(
                        algorand_sponsor_service.execute_server_side_opt_in(
                            user_address=account.algorand_address,
                            asset_id=asset_id
                        )
                    )
                finally:
                    loop.close()
            else:
                # Account has sufficient balance, proceed with opt-in
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result = loop.run_until_complete(
                        algorand_sponsor_service.execute_server_side_opt_in(
                            user_address=account.algorand_address,
                            asset_id=asset_id
                        )
                    )
                finally:
                    loop.close()
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create opt-in transaction'))
            
            # Log the opt-in request
            logger.info(
                f"Created sponsored opt-in for user {user.id}: "
                f"Asset {asset_type} (ID: {asset_id}), Address: {account.algorand_address[:10]}..."
            )
            
            if result.get('already_opted_in'):
                return cls(
                    success=True,
                    already_opted_in=True,
                    asset_id=asset_id,
                    asset_name=asset_type
                )
            
            return cls(
                success=True,
                already_opted_in=False,
                requires_user_signature=result.get('requires_user_signature', True),
                user_transaction=result.get('user_transaction'),
                sponsor_transaction=result.get('sponsor_transaction'),
                group_id=result.get('group_id'),
                asset_id=asset_id,
                asset_name=asset_type
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored opt-in for {asset_type}: {str(e)}')
            return cls(success=False, error=str(e))


class AlgorandSponsoredOptInMutation(graphene.Mutation):
    """
    Create a sponsored opt-in transaction for an asset.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        asset_id = graphene.Int(required=False)  # Defaults to CONFIO
    
    success = graphene.Boolean()
    error = graphene.String()
    already_opted_in = graphene.Boolean()
    requires_user_signature = graphene.Boolean()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    asset_id = graphene.Int()
    asset_name = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, asset_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get user's account
            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Default to CONFIO if no asset specified
            if not asset_id:
                asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
                
            if not asset_id:
                return cls(success=False, error='No asset ID specified and CONFIO not configured')
            
            # Determine asset name
            asset_name = "Unknown"
            if asset_id == AlgorandAccountManager.CONFIO_ASSET_ID:
                asset_name = "CONFIO"
            elif asset_id == AlgorandAccountManager.USDC_ASSET_ID:
                asset_name = "USDC"
            elif asset_id == AlgorandAccountManager.CUSD_ASSET_ID:
                asset_name = "cUSD"
            
            # Execute sponsored opt-in using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    algorand_sponsor_service.execute_server_side_opt_in(
                        user_address=account.algorand_address,
                        asset_id=asset_id
                    )
                )
            finally:
                loop.close()
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create opt-in transaction'))
            
            # Log the opt-in request
            logger.info(
                f"Created sponsored opt-in for user {user.id}: "
                f"Asset {asset_name} (ID: {asset_id}), Address: {account.algorand_address[:10]}..."
            )
            
            if result.get('already_opted_in'):
                return cls(
                    success=True,
                    already_opted_in=True,
                    asset_id=asset_id,
                    asset_name=asset_name
                )
            
            return cls(
                success=True,
                already_opted_in=False,
                requires_user_signature=result.get('requires_user_signature', True),
                user_transaction=result.get('user_transaction'),
                sponsor_transaction=result.get('sponsor_transaction'),
                group_id=result.get('group_id'),
                asset_id=asset_id,
                asset_name=asset_name
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored opt-in: {str(e)}')
            return cls(success=False, error=str(e))


class CheckSponsorHealthQuery(graphene.ObjectType):
    """
    Query to check sponsor service health and availability
    """
    sponsor_available = graphene.Boolean()
    sponsor_balance = graphene.Float()
    estimated_transactions = graphene.Int()
    warning_message = graphene.String()
    
    def resolve_sponsor_available(self, info):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            health = loop.run_until_complete(algorand_sponsor_service.check_sponsor_health())
            return health['can_sponsor']
        finally:
            loop.close()
    
    def resolve_sponsor_balance(self, info):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            health = loop.run_until_complete(algorand_sponsor_service.check_sponsor_health())
            return float(health['balance'])
        finally:
            loop.close()
    
    def resolve_estimated_transactions(self, info):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            health = loop.run_until_complete(algorand_sponsor_service.check_sponsor_health())
            return health.get('estimated_transactions', 0)
        finally:
            loop.close()
    
    def resolve_warning_message(self, info):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            health = loop.run_until_complete(algorand_sponsor_service.check_sponsor_health())
            if health.get('warning'):
                return health.get('recommendations', ['Low sponsor balance'])[0]
            return None
        finally:
            loop.close()