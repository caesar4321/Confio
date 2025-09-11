"""
Blockchain-related GraphQL mutations
"""
import graphene
import logging
from decimal import Decimal
from typing import Optional
from django.conf import settings
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
    # Use String for ASA IDs to avoid GraphQL Int 32-bit limits
    opted_in_assets = graphene.List(graphene.String)
    newly_opted_in = graphene.List(graphene.String)
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
                opted_in_assets=[str(a) for a in current_opt_ins],
                newly_opted_in=[str(a) for a in newly_opted_in],
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
            
            # Determine account context (personal or business)
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            account = None
            if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                business_id = jwt_context.get('business_id')
                account = Account.objects.filter(
                    business_id=business_id,
                    account_type='business',
                    deleted_at__isnull=True
                ).order_by('account_index').first()
            else:
                # Personal account fallback (use account_index from JWT if available)
                account_index = (jwt_context or {}).get('account_index', 0)
                account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()

            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found for account')
            if len(account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Generate unsigned transactions
            from algosdk.v2client import algod
            from algosdk.transaction import AssetTransferTxn
            import base64
            import msgpack
            from blockchain.algorand_client import get_algod_client
            
            algod_client = get_algod_client()
            
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
            
            # Create sponsor fee payment transaction with MBR funding
            from algosdk.transaction import PaymentTxn
            
            # Calculate minimum balance requirement increase
            # Each asset opt-in increases MBR by 100,000 microAlgos (0.1 ALGO)
            mbr_increase = 100_000 * len(user_txns)
            
            # Check user's current balance
            current_balance = account_info.get('amount', 0)
            min_balance = account_info.get('min-balance', 0)
            
            # Calculate new minimum balance after opt-ins
            new_min_balance = min_balance + mbr_increase
            
            # Calculate total fees needed (sponsor pays for all transactions)
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            total_fee = min_fee * (len(user_txns) + 1)  # +1 for sponsor payment itself
            
            # Calculate exact funding needed for MBR increase
            # User needs exactly new_min_balance, nothing more (fees are sponsored)
            funding_needed = 0
            if current_balance < new_min_balance:
                funding_needed = new_min_balance - current_balance
                logger.info(f"User needs {funding_needed} microAlgos for {len(user_txns)} asset opt-ins MBR")
            else:
                logger.info(f"User has sufficient balance for {len(user_txns)} asset opt-ins")
            
            logger.info(f"Asset opt-in funding: balance={current_balance}, min={min_balance}, new_min={new_min_balance}, funding={funding_needed}")
            
            fee_payment_txn = PaymentTxn(
                sender=AlgorandAccountManager.SPONSOR_ADDRESS,
                sp=params,
                receiver=account.algorand_address,
                amt=funding_needed,  # Fund exact MBR increase needed
                note=b"Sponsored asset opt-ins with MBR funding"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group with sponsor payment FIRST
            # This ensures user has funds before opt-in transactions are evaluated
            txn_group = [fee_payment_txn] + user_txns
            group_id = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = group_id
            
            # Sign sponsor transaction
            from algosdk import mnemonic
            sponsor_private_key = mnemonic.to_private_key(AlgorandAccountManager.SPONSOR_MNEMONIC)
            signed_fee_txn = fee_payment_txn.sign(sponsor_private_key)
            
            # Add the signed sponsor transaction FIRST (it's first in the group)
            sponsor_txn_encoded = base64.b64encode(
                msgpack.packb(signed_fee_txn.dictify(), use_bin_type=True)
            ).decode()
            
            transactions.append({
                'assetId': 0,  # Not an asset transaction
                'assetName': 'Sponsor Fee',
                'transaction': sponsor_txn_encoded,
                'type': 'sponsor',
                'signed': True,  # This one is already signed
                'index': 0  # First in group
            })
            
            # Then add user transactions
            for i, (asset_id, user_txn) in enumerate(zip(assets_to_opt_in, user_txns)):
                unsigned_txn = base64.b64encode(
                    msgpack.packb(user_txn.dictify(), use_bin_type=True)
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
                    'type': 'opt-in',
                    'index': i + 1  # After sponsor in group
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
            
            # Determine account context (personal or business)
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            active_account = None
            if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                business_id = jwt_context.get('business_id')
                active_account = Account.objects.filter(
                    business_id=business_id,
                    account_type='business',
                    deleted_at__isnull=True
                ).order_by('account_index').first()
            else:
                account_index = (jwt_context or {}).get('account_index', 0)
                active_account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()

            if not active_account or not active_account.algorand_address:
                return cls(success=False, error='No Algorand address found for account')
            
            # Validate it's an Algorand address
            if len(active_account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(active_account.algorand_address)
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
                sender=active_account.algorand_address,
                sp=params,
                receiver=active_account.algorand_address,
                amt=0,
                index=asset_id
            )
            
            # Encode transaction for client
            unsigned_txn = base64.b64encode(
                msgpack.packb(opt_in_txn.dictify(), use_bin_type=True)
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
    # Use String for ASA IDs to avoid GraphQL Int overflow
    opted_in_assets = graphene.List(graphene.String)
    asset_details = graphene.JSONString()
    
    def resolve_algorand_address(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return None

        # Try to use JWT account context (business or personal)
        try:
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        except Exception:
            jwt_context = None

        # Business context: use the business account's address
        if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
            business_id = jwt_context.get('business_id')
            business_account = Account.objects.filter(
                business_id=business_id,
                account_type='business',
                deleted_at__isnull=True
            ).order_by('account_index').first()
            if business_account and business_account.algorand_address:
                return business_account.algorand_address

        # Fallback: personal account address
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
        
        # Cast to strings to safely cross GraphQL boundary
        return [str(a) for a in AlgorandAccountManager._check_opt_ins(address)]
    
    def resolve_asset_details(self, info):
        opted_in = self.resolve_opted_in_assets(info)
        details = {}

        # Coerce ASA IDs (which may be strings) to ints for comparison
        for aid in opted_in:
            try:
                asset_id_int = int(aid)
            except Exception:
                continue

            if asset_id_int == AlgorandAccountManager.CONFIO_ASSET_ID:
                details[asset_id_int] = {
                    'name': 'CONFIO',
                    'symbol': 'CONFIO',
                    'decimals': 6
                }
            elif asset_id_int == AlgorandAccountManager.USDC_ASSET_ID:
                details[asset_id_int] = {
                    'name': 'USD Coin',
                    'symbol': 'USDC',
                    'decimals': 6
                }
            elif asset_id_int == AlgorandAccountManager.CUSD_ASSET_ID:
                details[asset_id_int] = {
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
                user_account = Account.objects.filter(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()
            
            if not user_account or not user_account.algorand_address:
                return cls(success=False, error='Sender Algorand address not found')
            
            # Validate sender's address format
            if len(user_account.algorand_address) != 58:
                return cls(success=False, error='Invalid sender Algorand address format')
            
            # Resolve recipient address based on input type
            # Note: recipient_address might already be set from the parameter
            resolved_recipient_address = None
            recipient_user = None  # Track the actual recipient user object for notifications
            
            # Priority 1: User ID lookup (Confío users)
            if recipient_user_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    recipient_user = User.objects.get(id=recipient_user_id)
                    # Get recipient's personal account
                    recipient_user_account = recipient_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_user_account and recipient_user_account.algorand_address:
                        resolved_recipient_address = recipient_user_account.algorand_address
                        logger.info(f"Resolved recipient address from user_id {recipient_user_id}: {resolved_recipient_address[:10]}...")
                        logger.info(f"Recipient user found: {recipient_user.id} - {recipient_user.username}")
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
                    recipient_user_account = found_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_user_account and recipient_user_account.algorand_address:
                        resolved_recipient_address = recipient_user_account.algorand_address
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
                asset_id = AlgorandAccountManager.CUSD_ASSET_ID
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
                
                account_info = algod_client.account_info(user_account.algorand_address)
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
                        sender=user_account.algorand_address,
                        recipient=resolved_recipient_address,  # Use the resolved address
                        amount=Decimal(str(amount)),
                        asset_id=asset_id,
                        note=note
                    )
                )
            finally:
                # No event loop used in this path
                pass
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create sponsored transaction'))
            
            # Do not send push/in-app notifications here; use optimistic UI on client.
            # Push notifications will be sent after on-chain confirmation by the worker.
            
            # Return the transactions for client signing
            # The client will sign the user transaction and call SubmitSponsoredGroup
            logger.info(
                f"Created sponsored {asset_type} transfer for user {user.id}: "
                f"{amount} from {user_account.algorand_address[:10]}... to {resolved_recipient_address[:10]}... (awaiting client signature)"
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
    Sponsor transaction is always placed first in the group for proper fee payment.
    """
    
    class Arguments:
        signed_user_txn = graphene.String(required=True)  # Base64 encoded signed user transaction
        signed_sponsor_txn = graphene.String(required=False)  # Base64 encoded signed sponsor transaction (optional for solo txns)
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()
    fees_saved = graphene.Float()
    
    @classmethod
    def mutate(cls, root, info, signed_user_txn, signed_sponsor_txn=None):
        try:
            logger.info(f"SubmitSponsoredGroupMutation called")
            logger.info(f"User transaction size: {len(signed_user_txn)} chars")
            
            if signed_sponsor_txn and signed_sponsor_txn.strip():
                logger.info(f"Sponsor transaction size: {len(signed_sponsor_txn)} chars")
                is_sponsored = True
            else:
                logger.info(f"No sponsor transaction - submitting solo transaction")
                is_sponsored = False
            
            user = info.context.user
            if not user.is_authenticated:
                logger.warning(f"Unauthenticated request to submit transaction")
                return cls(success=False, error='Not authenticated')
            
            logger.info(f"Submitting {'sponsored group' if is_sponsored else 'solo transaction'} for user {user.id}")
            
            # Submit the transaction(s) using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                if is_sponsored:
                    logger.info(f"Calling algorand_sponsor_service.submit_sponsored_group...")
                    result = loop.run_until_complete(
                        algorand_sponsor_service.submit_sponsored_group(
                            signed_user_txn=signed_user_txn,
                            signed_sponsor_txn=signed_sponsor_txn
                        )
                    )
                else:
                    # Submit solo transaction
                    logger.info(f"Submitting solo transaction...")
                    result = loop.run_until_complete(
                        algorand_sponsor_service.submit_solo_transaction(
                            signed_txn=signed_user_txn
                        )
                    )
                logger.info(f"Transaction submission returned: {result}")
            finally:
                # No event loop in this path; keep cleanup safe
                try:
                    loop.close()  # Only if it exists from older paths
                except NameError:
                    pass
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to submit transaction'))

            logger.info(
                f"Submitted sponsored transaction for user {user.id}: "
                f"TxID: {result['tx_id']}, Round: {result['confirmed_round']}"
            )

            # No notifications on submit. Worker sends push after on-chain confirmation.

            # Persist a SendTransaction row with SUBMITTED status so Celery can confirm later
            try:
                import base64
                import msgpack
                from algosdk.encoding import encode_address
                from decimal import Decimal
                from django.conf import settings
                from send.models import SendTransaction
                from users.models import Account

                raw = base64.b64decode(signed_user_txn)
                try:
                    d = msgpack.unpackb(raw, raw=False)
                except Exception:
                    d = None

                sender_addr = ''
                recipient_addr = ''
                token_type = 'CUSD'
                amount_dec = Decimal('0')
                parsed_type = None

                if isinstance(d, dict):
                    td = d.get('txn', {})
                    t = td.get('type')
                    parsed_type = t
                    if t == 'axfer':
                        snd = td.get('snd')
                        arcv = td.get('arcv')
                        xaid = int(td.get('xaid') or 0)
                        aamt = int(td.get('aamt') or 0)
                        sender_addr = encode_address(snd) if snd else ''
                        recipient_addr = encode_address(arcv) if arcv else ''
                        # Map asset id to token type and decimals (default 6)
                        if xaid == int(getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 0)):
                            token_type = 'CUSD'
                            decimals = 6
                        elif xaid == int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0)):
                            token_type = 'CONFIO'
                            decimals = 6
                        elif xaid == int(getattr(settings, 'ALGORAND_USDC_ASSET_ID', 0)):
                            token_type = 'USDC'
                            decimals = 6
                        else:
                            token_type = 'CUSD'
                            decimals = 6
                        amount_dec = Decimal(aamt) / (Decimal(10) ** Decimal(decimals))
                    elif t == 'pay':
                        # ALGO payment (rare in our app); store as CONFIRMED token 'ALGO' if needed
                        snd = td.get('snd')
                        rcv = td.get('rcv')
                        amt = int(td.get('amt') or 0)
                        sender_addr = encode_address(snd) if snd else ''
                        recipient_addr = encode_address(rcv) if rcv else ''
                        token_type = 'ALGO'
                        amount_dec = Decimal(amt) / Decimal(1_000_000)

                # Only persist sends for real asset transfers with non-zero amount
                if not (parsed_type == 'axfer' and amount_dec > 0):
                    logger.info(
                        f"Skipping SendTransaction persist for tx {result.get('tx_id')} (type={parsed_type}, amount={amount_dec})"
                    )
                    return cls(
                        success=True,
                        transaction_id=result['tx_id'],
                        confirmed_round=result['confirmed_round'] or 0,
                        fees_saved=result.get('fees_saved') or 0.0
                    )

                # Resolve recipient user if known by Algorand address
                recipient_user = None
                try:
                    acct = Account.objects.filter(algorand_address=recipient_addr).select_related('user').first()
                    recipient_user = acct.user if acct else None
                except Exception:
                    recipient_user = None

                # Derive friendly display names and types
                def full_name(u):
                    try:
                        nm = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
                        return nm or None
                    except Exception:
                        return None

                sender_display = full_name(user) or (getattr(user, 'username', None) if '@' not in (getattr(user, 'username', '') or '') else None)
                recipient_display = None
                if recipient_user:
                    recipient_display = full_name(recipient_user) or (getattr(recipient_user, 'username', None) if '@' not in (getattr(recipient_user, 'username', '') or '') else None)

                sender_type = 'user'
                recipient_type = 'user' if recipient_user else 'external'

                # Phone numbers (used for contact matching; optional)
                try:
                    sc = getattr(user, 'phone_country', None) or getattr(user, 'phoneCountry', None)
                    sn = getattr(user, 'phone_number', None) or getattr(user, 'phoneNumber', None)
                    sender_phone = (f"{sc}{sn}" if sn and sc else (sn or '')) or ''
                except Exception:
                    sender_phone = ''
                try:
                    rc = getattr(recipient_user, 'phone_country', None) if recipient_user else None
                    rn = getattr(recipient_user, 'phone_number', None) if recipient_user else None
                    recipient_phone = (f"{rc}{rn}" if rn and rc else (rn or '')) or ''
                except Exception:
                    recipient_phone = ''

                # Create or update by unique transaction_hash
                stx, created = SendTransaction.all_objects.update_or_create(
                    transaction_hash=result['tx_id'],
                    defaults={
                        'sender_user': user,
                        'recipient_user': recipient_user,
                        'sender_address': sender_addr or '',
                        'recipient_address': recipient_addr or '',
                        'amount': amount_dec,
                        'token_type': token_type if token_type in ['CUSD', 'CONFIO', 'USDC'] else 'CUSD',
                        'status': 'SUBMITTED',
                        'error_message': '',
                        'sender_display_name': sender_display or '',
                        'recipient_display_name': recipient_display or '',
                        'sender_type': sender_type,
                        'recipient_type': recipient_type,
                        'sender_phone': sender_phone,
                        'recipient_phone': recipient_phone,
                    }
                )
                logger.info(f"SendTransaction persisted for tx {result['tx_id']} (created={created})")
            except Exception as pe:
                logger.warning(f"Failed to persist SendTransaction for tx {result.get('tx_id')}: {pe}")

            return cls(
                success=True,
                transaction_id=result['tx_id'],
                confirmed_round=result['confirmed_round'] or 0,
                fees_saved=result.get('fees_saved') or 0.0
            )
            
        except Exception as e:
            logger.error(f'Error submitting sponsored group: {str(e)}')
            return cls(success=False, error=str(e))


class SubmitBusinessOptInGroupMutation(graphene.Mutation):
    """
    Submit a complete sponsored opt-in group for a business account.
    Expects all user opt-in transactions (signed by the business) and the pre-signed sponsor transaction.
    The order must match the group created by CheckBusinessOptInMutation: [opt-in..., sponsor-fee].
    """

    class Arguments:
        signed_transactions = graphene.JSONString(
            required=True,
            description="Array of base64-encoded signed transactions in group order (opt-ins first, sponsor last)"
        )

    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    confirmed_round = graphene.Int()

    @classmethod
    def mutate(cls, root, info, signed_transactions):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')

            logger.info('SubmitBusinessOptInGroupMutation: submitting opt-in group')

            # Parse input JSON if passed as a string
            import json
            import base64
            import msgpack
            from algosdk.v2client import algod
            
            if isinstance(signed_transactions, str):
                try:
                    signed_transactions = json.loads(signed_transactions)
                except json.JSONDecodeError as e:
                    logger.error(f'Invalid JSON for signed_transactions: {e}')
                    return cls(success=False, error='Invalid transaction format')

            if not isinstance(signed_transactions, list) or not signed_transactions:
                return cls(success=False, error='No transactions provided')

            # Decode signed transactions
            submit_bytes = []
            for i, txn_b64 in enumerate(signed_transactions):
                try:
                    if isinstance(txn_b64, dict):
                        # Accept object with 'transaction' field
                        txn_b64 = txn_b64.get('transaction')
                    if not isinstance(txn_b64, str):
                        raise ValueError('Each transaction must be a base64 string')

                    # Simple base64 decode without extra normalization
                    decoded = base64.b64decode(txn_b64)
                    submit_bytes.append(decoded)
                    logger.info(f'Transaction {i}: decoded {len(decoded)} bytes')
                except Exception as e:
                    logger.error(f'Failed to decode transaction {i}: {e}')
                    return cls(success=False, error=f'Failed to decode transaction {i}: {str(e)}')

            # Submit group
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )

            logger.info(f'Submitting business opt-in group of {len(submit_bytes)} txns')
            
            # Log what we're submitting for debugging
            for i, raw_bytes in enumerate(submit_bytes):
                logger.info(f'Transaction {i} size: {len(raw_bytes)} bytes')
                # Log first few bytes to verify it's msgpack
                logger.info(f'Transaction {i} first bytes: {raw_bytes[:10].hex()}')
            
            # Submit as base64-encoded concatenated bytes
            combined = b''.join(submit_bytes)
            combined_b64 = base64.b64encode(combined).decode('ascii')

            logger.info(f'Submitting concatenated group of {len(combined)} total bytes')
            tx_id = algod_client.send_raw_transaction(combined_b64)
            
            from algosdk.transaction import wait_for_confirmation
            confirmed = wait_for_confirmation(algod_client, tx_id, 10)
            confirmed_round = confirmed.get('confirmed-round', 0)

            logger.info(f'Business opt-in group submitted: txid={tx_id}, round={confirmed_round}')

            return cls(
                success=True,
                transaction_id=tx_id,
                confirmed_round=confirmed_round
            )

        except Exception as e:
            logger.error(f'Error submitting business opt-in group: {str(e)}')
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
    asset_id = graphene.String()
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
            
            # Determine account context using JWT context (allow business or personal)
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)

            sender_address = None
            if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                business_id = jwt_context.get('business_id')
                business_account = Account.objects.filter(
                    business_id=business_id,
                    account_type='business',
                    deleted_at__isnull=True
                ).order_by('account_index').first()
                if business_account and business_account.algorand_address:
                    sender_address = business_account.algorand_address
            else:
                # Personal account
                account_index = (jwt_context or {}).get('account_index', 0)
                personal_account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()
                if personal_account and personal_account.algorand_address:
                    sender_address = personal_account.algorand_address
            
            if not sender_address:
                return cls(success=False, error='No Algorand address found for account')

            # Validate it's an Algorand address
            if not sender_address or len(sender_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Check if account needs additional funding for MBR
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(sender_address)
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
                            sender_address,
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
                            user_address=sender_address,
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
                            user_address=sender_address,
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
                f"Asset {asset_type} (ID: {asset_id}), Address: {sender_address[:10]}..."
            )
            
            if result.get('already_opted_in'):
                return cls(
                    success=True,
                    already_opted_in=True,
                    asset_id=str(asset_id),
                    asset_name=asset_type
                )
            
            return cls(
                success=True,
                already_opted_in=False,
                requires_user_signature=result.get('requires_user_signature', True),
                user_transaction=result.get('user_transaction'),
                sponsor_transaction=result.get('sponsor_transaction'),
                group_id=result.get('group_id'),
                asset_id=str(asset_id),
                asset_name=asset_type
            )
            
        except Exception as e:
            logger.error(f'Error creating sponsored opt-in for {asset_type}: {str(e)}')
            return cls(success=False, error=str(e))


class GenerateAppOptInTransactionMutation(graphene.Mutation):
    """
    Generate a sponsored opt-in transaction for the cUSD application.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        # Use String to avoid GraphQL 32-bit int limits
        app_id = graphene.String(required=False)  # Defaults to cUSD app
    
    success = graphene.Boolean()
    error = graphene.String()
    already_opted_in = graphene.Boolean()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    # Return app_id as String to avoid 32-bit limits
    app_id = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, app_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Determine account context (personal or business)
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            account = None
            if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                business_id = jwt_context.get('business_id')
                account = Account.objects.filter(
                    business_id=business_id,
                    account_type='business',
                    deleted_at__isnull=True
                ).order_by('account_index').first()
            else:
                account_index = (jwt_context or {}).get('account_index', 0)
                account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()

            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found for account')
            
            # Default to cUSD app if not specified
            if not app_id:
                app_id_int = AlgorandAccountManager.CUSD_APP_ID
            else:
                # Coerce provided string app_id to int
                try:
                    app_id_int = int(app_id)
                except Exception:
                    return cls(success=False, error='Invalid app ID format')
                
            if not app_id_int:
                return cls(success=False, error='No app ID specified and cUSD app not configured')
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(account.algorand_address)
            apps_local_state = account_info.get('apps-local-state', [])
            
            if any(app['id'] == app_id_int for app in apps_local_state):
                logger.info(f"Account already opted into app {app_id_int}")
                return cls(
                    success=True,
                    already_opted_in=True,
                    app_id=str(app_id_int)
                )
            
            # Check user's current balance and min balance requirement
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            # After app opt-in, min balance will increase based on the app's local state schema
            # cUSD app has 2 uint64 fields (is_frozen, is_vault) in local state
            # Base opt-in: 100,000 microAlgos + (2 * 28,500) for the uint64 fields = 157,000 total
            app_mbr_increase = 100_000 + (2 * 28_500)  # 157,000 microAlgos
            min_balance_after_optin = min_balance_required + app_mbr_increase
            
            logger.info(
                f"Account {account.algorand_address}: current_balance={current_balance}, "
                f"min_balance={min_balance_required}, min_after_optin={min_balance_after_optin}"
            )
            
            # Create sponsored opt-in transaction group
            from algosdk.transaction import ApplicationOptInTxn, PaymentTxn, calculate_group_id, SuggestedParams
            from algosdk import mnemonic, account as algo_account
            import base64
            import msgpack
            
            params = algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Get sponsor credentials
            sponsor_mnemonic = settings.ALGORAND_SPONSOR_MNEMONIC
            sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
            sponsor_address = algo_account.address_from_private_key(sponsor_private_key)
            
            # Calculate funding needed for minimum balance increase
            funding_needed = 0
            if current_balance < min_balance_after_optin + min_fee:
                funding_needed = min_balance_after_optin + min_fee - current_balance
                logger.info(f"User needs {funding_needed} microAlgos for app opt-in MBR")
            else:
                logger.info(f"User has sufficient balance for app opt-in")
            
            # Transaction 0: Sponsor payment (FIRST for proper fee payment)
            sponsor_params = SuggestedParams(
                fee=2 * min_fee,  # Cover both transactions (sponsor payment + app opt-in)
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            sponsor_payment = PaymentTxn(
                sender=sponsor_address,
                receiver=account.algorand_address,
                amt=funding_needed,  # Fund the MBR increase + buffer for fees
                sp=sponsor_params,
                note=b"Sponsored app opt-in MBR funding"
            )
            
            # Transaction 1: User app opt-in (0 fee)
            opt_in_params = SuggestedParams(
                fee=0,  # Sponsored by payment transaction
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # ApplicationOptInTxn automatically sets OnComplete to OptIn
            # Beaker apps require the opt_in method selector
            opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
            
            app_opt_in = ApplicationOptInTxn(
                sender=account.algorand_address,
                sp=opt_in_params,
                index=app_id_int,
                app_args=[opt_in_selector]  # Required for Beaker router
            )
            
            # Group transactions - sponsor FIRST
            txns = [sponsor_payment, app_opt_in]
            group_id = calculate_group_id(txns)
            
            for txn in txns:
                txn.group = group_id
            
            # Sign sponsor transaction
            sponsor_signed = sponsor_payment.sign(sponsor_private_key)
            sponsor_signed_encoded = base64.b64encode(
                msgpack.packb(sponsor_signed.dictify(), use_bin_type=True)
            ).decode()
            
            # Encode user transaction for frontend
            from algosdk import encoding
            user_txn_encoded = encoding.msgpack_encode(app_opt_in)
            
            logger.info(f"Created sponsored app opt-in group for account: App {app_id} (sponsor first)")
            
            # Return sponsored transaction group
            return cls(
                success=True,
                already_opted_in=False,
                user_transaction=user_txn_encoded,
                sponsor_transaction=sponsor_signed_encoded,
                group_id=base64.b64encode(group_id).decode(),
                app_id=str(app_id_int)
            )
            
        except Exception as e:
            logger.error(f'Error generating app opt-in transaction: {str(e)}')
            return cls(success=False, error=str(e))


class AlgorandSponsoredOptInMutation(graphene.Mutation):
    """
    Create a sponsored opt-in transaction for an asset.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        # Use String to avoid 32-bit GraphQL Int limit for large ASA IDs
        asset_id = graphene.String(required=False)  # Defaults to CONFIO
    
    success = graphene.Boolean()
    error = graphene.String()
    already_opted_in = graphene.Boolean()
    requires_user_signature = graphene.Boolean()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    asset_id = graphene.String()
    asset_name = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, asset_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get user's account
            user_account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not user_account or not user_account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(user_account.algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Default to CONFIO if no asset specified
            if not asset_id:
                asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
            # Coerce string asset_id to int for on-chain ops
            try:
                asset_id_int = int(asset_id)
            except Exception:
                return cls(success=False, error='Invalid asset ID format')

            if not asset_id_int:
                return cls(success=False, error='No asset ID specified and CONFIO not configured')
            
            # Determine asset name
            asset_name = "Unknown"
            if asset_id_int == AlgorandAccountManager.CONFIO_ASSET_ID:
                asset_name = "CONFIO"
            elif asset_id_int == AlgorandAccountManager.USDC_ASSET_ID:
                asset_name = "USDC"
            elif asset_id_int == AlgorandAccountManager.CUSD_ASSET_ID:
                asset_name = "cUSD"
            
            # Execute sponsored opt-in using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    algorand_sponsor_service.execute_server_side_opt_in(
                        user_address=user_account.algorand_address,
                        asset_id=asset_id_int
                    )
                )
            finally:
                # Guard against missing loop in this path
                try:
                    loop.close()
                except NameError:
                    pass
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create opt-in transaction'))
            
            # Log the opt-in request
            logger.info(
                f"Created sponsored opt-in for user {user.id}: "
                f"Asset {asset_name} (ID: {asset_id_int}), Address: {user_account.algorand_address[:10]}..."
            )
            
            if result.get('already_opted_in'):
                return cls(
                    success=True,
                    already_opted_in=True,
                    asset_id=str(asset_id_int),
                    asset_name=asset_name
                )
            
            return cls(
                success=True,
                already_opted_in=False,
                requires_user_signature=result.get('requires_user_signature', True),
                user_transaction=result.get('user_transaction'),
                sponsor_transaction=result.get('sponsor_transaction'),
                group_id=result.get('group_id'),
                asset_id=str(asset_id_int),
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


class CheckBusinessOptInMutation(graphene.Mutation):
    """
    Check if business account needs opt-ins for CONFIO and cUSD assets
    Only for business owners, not employees
    """
    
    class Arguments:
        pass  # No arguments needed, uses JWT context
    
    needs_opt_in = graphene.Boolean()
    assets = graphene.List(graphene.String)
    # Keep existing field name style
    opt_in_transactions = graphene.JSONString()
    # Explicit camelCase alias expected by some clients
    optInTransactions = graphene.JSONString()
    # Personal-flow alias
    transactions = graphene.JSONString()
    # Convenience boolean for clients that only check presence
    hasTransactions = graphene.Boolean()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        try:
            user = info.context.user
            if not user.is_authenticated:
                logger.error('CheckBusinessOptIn: User not authenticated')
                return cls(error='User not authenticated')
            
            # Get JWT context properly
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info)
            
            # If no context, extract manually from JWT
            if not jwt_context:
                # Try to extract JWT claims directly
                request = info.context
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('JWT '):
                    from jwt import decode as jwt_decode
                    token = auth_header[4:]
                    try:
                        jwt_claims = jwt_decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                    except:
                        jwt_claims = {}
                else:
                    jwt_claims = {}
            else:
                jwt_claims = jwt_context
            
            logger.info(f'CheckBusinessOptIn: JWT claims: {jwt_claims}')
            
            # Check if this is a business account
            account_type = jwt_claims.get('account_type')
            if account_type != 'business':
                logger.info(f'CheckBusinessOptIn: Not a business account (type={account_type})')
                return cls(needs_opt_in=False, assets=[])
            
            # Check if user is owner (not just a regular employee)
            employee_role = jwt_claims.get('business_employee_role')
            if employee_role and employee_role != 'owner':
                # Only non-owner employees are blocked
                logger.warning(f'CheckBusinessOptIn: Non-owner employee (role={employee_role}) attempted opt-in for business {business_id}')
                return cls(
                    needs_opt_in=False, 
                    assets=[], 
                    error='Solo el dueño del negocio puede realizar opt-ins. Los empleados no tienen permisos para esta acción.'
                )
            
            # Get business account address
            business_id = jwt_claims.get('business_id')
            if not business_id:
                logger.error('CheckBusinessOptIn: No business ID in JWT')
                return cls(error='No business ID in JWT')
            
            from users.models import Account
            try:
                business_account = Account.objects.get(
                    business_id=business_id,
                    account_type='business'
                )
                logger.info(f'CheckBusinessOptIn: Found business account {business_id} with address {business_account.algorand_address}')
            except Account.DoesNotExist:
                logger.error(f'CheckBusinessOptIn: Business account not found for business_id={business_id}')
                return cls(error='Business account not found')
            
            if not business_account.algorand_address:
                logger.error(f'CheckBusinessOptIn: Business account {business_id} has no Algorand address')
                return cls(error='Business account has no Algorand address')
            
            # Check opt-in status against configured network
            from algosdk.v2client import algod
            algod_address = settings.ALGORAND_ALGOD_ADDRESS
            algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '') or ''
            if not algod_token and ('localhost' in algod_address or '127.0.0.1' in algod_address):
                algod_token = 'a' * 64
            algod_client = algod.AlgodClient(algod_token, algod_address)

            try:
                account_info = algod_client.account_info(business_account.algorand_address)
                assets = account_info.get('assets', [])
                logger.info(f'CheckBusinessOptIn: Account has {len(assets)} assets')

                CONFIO_ID = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', None)
                CUSD_ID = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None)

                has_confio = bool(CONFIO_ID) and any(a['asset-id'] == CONFIO_ID for a in assets)
                has_cusd = bool(CUSD_ID) and any(a['asset-id'] == CUSD_ID for a in assets)
                
                logger.info(f'CheckBusinessOptIn: has_confio={has_confio}, has_cusd={has_cusd}')
                
                needed_assets = []
                if CONFIO_ID and not has_confio:
                    needed_assets.append('CONFIO')
                if CUSD_ID and not has_cusd:
                    needed_assets.append('cUSD')
                
                logger.info(f'CheckBusinessOptIn: Needed assets: {needed_assets}')
                
                if not needed_assets:
                    logger.info('CheckBusinessOptIn: Account already opted into all assets')
                    return cls(needs_opt_in=False, assets=[])
                
                # Create a single group transaction for all opt-ins
                try:
                    from algosdk.transaction import AssetTransferTxn, PaymentTxn, assign_group_id
                    from algosdk import encoding
                    import base64
                except ImportError as e:
                    logger.error(f'CheckBusinessOptIn: Import error: {e}')
                    return cls(error=f"Import error: {str(e)}")
                
                # Get suggested params
                params = algod_client.suggested_params()
                
                # Create all transactions for the group
                transactions = []
                asset_ids = []
                
                for asset_name in needed_assets:
                    asset_id = CONFIO_ID if asset_name == 'CONFIO' else CUSD_ID
                    asset_ids.append(asset_id)
                    
                    # Create opt-in transaction (0 amount transfer to self) with 0 fee
                    opt_in_txn = AssetTransferTxn(
                        sender=business_account.algorand_address,
                        sp=params,
                        receiver=business_account.algorand_address,
                        amt=0,
                        index=asset_id
                    )
                    opt_in_txn.fee = 0  # User doesn't pay fees
                    transactions.append(opt_in_txn)
                
                # Get sponsor address from configuration
                sponsor_address = algorand_sponsor_service.sponsor_address
                # Use funding service (configured to this network)
                from .account_funding_service import AccountFundingService
                funding_service = AccountFundingService()
                
                # Calculate MBR increase for asset opt-ins
                # Each asset opt-in increases MBR by 100,000 microAlgos (0.1 ALGO)
                mbr_increase = len(needed_assets) * 100_000
                
                # Check current balance and calculate funding needed
                try:
                    account_info = algod_client.account_info(business_account.algorand_address)
                    current_balance = account_info.get('amount', 0)
                    current_min_balance = account_info.get('min-balance', 0)
                    new_min_balance = current_min_balance + mbr_increase
                    
                    # Calculate exact funding needed for MBR
                    funding_needed = 0
                    if current_balance < new_min_balance:
                        funding_needed = new_min_balance - current_balance
                        logger.info(f"Business needs {funding_needed} microAlgos for {len(needed_assets)} asset opt-ins")
                    else:
                        logger.info(f"Business has sufficient balance for asset opt-ins")
                        
                except Exception as e:
                    logger.error(f"Error checking account balance: {e}")
                    # Default funding for asset opt-ins
                    funding_needed = mbr_increase
                
                # Create sponsor fee payment transaction with MBR funding
                # Group has: sponsor payment FIRST, then N opt-ins (total N+1)
                total_transactions = len(transactions) + 1  # +1 for the sponsor payment itself
                total_fee = total_transactions * 1000  # 1000 microAlgos per transaction

                # Ensure flat fee so our explicit fee is respected
                try:
                    params.flat_fee = True
                except Exception:
                    pass

                fee_payment_txn = PaymentTxn(
                    sender=sponsor_address,
                    sp=params,
                    receiver=business_account.algorand_address,  # Fund the business account
                    amt=funding_needed  # Provide exact MBR funding needed
                )
                fee_payment_txn.fee = total_fee  # Sponsor pays all fees

                # Sponsor payment MUST be first in the group
                transactions = [fee_payment_txn] + transactions

                # Assign group ID to all transactions
                group_id = assign_group_id(transactions)
                
                # Sign the sponsor transaction (now at index 0)
                from algosdk import mnemonic, account
                try:
                    # Ensure mnemonic is a string
                    sponsor_mnemonic = algorand_sponsor_service.sponsor_mnemonic
                    if not sponsor_mnemonic:
                        raise ValueError("No sponsor mnemonic configured")
                    
                    # Convert mnemonic to private key
                    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
                    
                    # Sign the transaction
                    signed_sponsor_txn = transactions[0].sign(sponsor_private_key)
                    
                except Exception as sign_error:
                    logger.error(f'CheckBusinessOptIn: Error signing sponsor transaction: {sign_error}')
                    logger.error(f'CheckBusinessOptIn: Sponsor mnemonic type: {type(algorand_sponsor_service.sponsor_mnemonic)}')
                    return cls(error=f"Failed to sign sponsor transaction: {str(sign_error)}")
                
                # Prepare transaction data for frontend (mirror personal flow encoding)
                import msgpack
                user_transactions = []
                for txn in transactions[1:]:  # All except the sponsor fee payment at index 0
                    user_transactions.append(
                        base64.b64encode(msgpack.packb(txn.dictify())).decode('utf-8')
                    )
                
                # Sponsor transaction is already signed - encode the SignedTransaction dict
                sponsor_transaction = base64.b64encode(
                    msgpack.packb(signed_sponsor_txn.dictify())
                ).decode('utf-8')
                
                logger.info(f'CheckBusinessOptIn: Sponsor transaction base64 length: {len(sponsor_transaction)}')
                logger.info(f'CheckBusinessOptIn: Sponsor transaction first 100 chars: {sponsor_transaction[:100]}')
                logger.info(f'CheckBusinessOptIn: Full sponsor transaction: {sponsor_transaction}')
                
                # Format the transactions for the client with sponsor FIRST
                # This ensures the wallet submits the funding payment before the asset opt-ins
                transactions_data = []

                # Add the sponsor transaction (pre-signed) FIRST
                transactions_data.append({
                    'type': 'sponsor',
                    'transaction': sponsor_transaction,
                    'signed': True
                })

                # Then add each opt-in transaction
                for i, txn in enumerate(user_transactions):
                    asset_id = asset_ids[i]
                    asset_name = needed_assets[i]
                    transactions_data.append({
                        'type': 'opt-in',
                        'assetId': asset_id,
                        'assetName': asset_name,
                        'transaction': txn,
                        'signed': False
                    })
                
                # For GraphQL JSONString, pass the Python list; Graphene will JSON-encode it
                opt_in_data = transactions_data
                
                logger.info(f'CheckBusinessOptIn: Created group transaction for {len(needed_assets)} assets')
                
                import json
                has_tx = len(transactions_data) > 0
                # Keep camelCase fields as JSON strings for backward compatibility with clients
                tx_list = transactions_data
                tx_string = json.dumps(tx_list)
                
                # Debug: Check if sponsor transaction is intact in JSON
                parsed_check = json.loads(tx_string)
                sponsor_in_json = next((t for t in parsed_check if t.get('type') == 'sponsor'), None)
                if sponsor_in_json:
                    logger.info(f'CheckBusinessOptIn: Sponsor in JSON has length: {len(sponsor_in_json.get("transaction", ""))}')
                
                return cls(
                    needs_opt_in=True,
                    assets=needed_assets,
                    # snake_case legacy alias (string)
                    opt_in_transactions=tx_string,
                    # camelCase expected by mobile (string)
                    optInTransactions=tx_string,
                    # personal-flow style alias (array)
                    transactions=tx_list,
                    hasTransactions=has_tx
                )
            except Exception as e:
                logger.error(f'CheckBusinessOptIn: Error getting account info: {str(e)}')
                return cls(error=f'Error checking opt-in status: {str(e)}')
                
        except Exception as e:
            logger.error(f'Error checking business opt-in: {str(e)}')
            return cls(error=str(e))


class CompleteBusinessOptInMutation(graphene.Mutation):
    """
    Mark business opt-ins as complete after successful transactions
    """
    
    class Arguments:
        tx_ids = graphene.List(graphene.String, required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, tx_ids):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='User not authenticated')
            
            # Verify transactions on configured network
            from algosdk.v2client import algod
            algod_address = settings.ALGORAND_ALGOD_ADDRESS
            algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '') or ''
            if not algod_token and ('localhost' in algod_address or '127.0.0.1' in algod_address):
                algod_token = 'a' * 64
            algod_client = algod.AlgodClient(algod_token, algod_address)
            
            for tx_id in tx_ids:
                try:
                    algod_client.pending_transaction_info(tx_id)
                    logger.info(f'Verified opt-in transaction: {tx_id}')
                except Exception as e:
                    logger.warning(f'Could not verify transaction {tx_id}: {e}')
            
            return cls(success=True)
            
        except Exception as e:
            logger.error(f'Error completing business opt-in: {str(e)}')
            return cls(success=False, error=str(e))
