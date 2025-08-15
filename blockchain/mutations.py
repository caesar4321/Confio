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
            user_account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            if not user_account or not user_account.algorand_address:
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
            account_info = algod_client.account_info(user_account.algorand_address)
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
                    sender=user_account.algorand_address,
                    sp=params,
                    receiver=user_account.algorand_address,
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
                receiver=user_account.algorand_address,
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
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(user_account.algorand_address)
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
                sender=user_account.algorand_address,
                sp=params,
                receiver=user_account.algorand_address,
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
        
        return user_account.algorand_address if account else None
    
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
            
            # Create notifications immediately (like CreateSendTransaction does)
            # We'll create them now even though the transaction hasn't been submitted yet
            try:
                from notifications.utils import create_notification
                from notifications.models import NotificationType
                from django.utils import timezone
                
                # Determine recipient display name
                recipient_display_name = None
                
                # Use the recipient_user we already looked up earlier
                if recipient_user:
                    # Build display name from user fields
                    recipient_display_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip()
                    if not recipient_display_name:
                        recipient_display_name = recipient_user.username or f"User {recipient_user.id}"
                    logger.info(f"Recipient user for notification: {recipient_user.id} - {recipient_display_name}")
                elif recipient_phone:
                    recipient_display_name = recipient_phone
                elif resolved_recipient_address:
                    recipient_display_name = f"{resolved_recipient_address[:6]}...{resolved_recipient_address[-4:]}"
                
                if not recipient_display_name:
                    recipient_display_name = "alguien"
                
                # Build sender display name from user fields
                sender_display_name = f"{user.first_name} {user.last_name}".strip()
                if not sender_display_name:
                    sender_display_name = user.username or f"User {user.id}"
                
                # Create notification for sender
                logger.info(f"Creating send notification for sender {user.id}")
                create_notification(
                    user=user,
                    notification_type=NotificationType.SEND_SENT,
                    title="Envío completado",
                    message=f"Enviaste {amount} {asset_type} a {recipient_display_name}",
                    data={
                        'transaction_type': 'send',
                        'amount': f'-{amount}',
                        'token_type': asset_type,
                        'currency': asset_type,
                        'recipient_name': recipient_display_name,
                        'recipient_address': resolved_recipient_address,
                        'sender_name': sender_display_name,
                        'sender_address': user_account.algorand_address,
                        'status': 'pending',
                        'created_at': timezone.now().isoformat(),
                        'note': note or '',
                        'type': 'send',
                        'to': recipient_display_name,
                        'toAddress': resolved_recipient_address,
                        'from': sender_display_name,
                        'fromAddress': user_account.algorand_address,
                        'date': timezone.now().strftime('%Y-%m-%d'),
                        'time': timezone.now().strftime('%H:%M'),
                        'avatar': recipient_display_name[0] if recipient_display_name else 'U',
                    },
                    related_object_type='AlgorandTransaction',
                    related_object_id=result['group_id'],
                    action_url=f"confio://transaction/pending"
                )
                logger.info(f"Created sender notification for {user.id}")
                
                # Create notification for recipient if they're a Confío user
                logger.info(f"Checking if recipient_user exists: {recipient_user}")
                if recipient_user:
                    logger.info(f"YES - Creating send notification for recipient {recipient_user.id} ({recipient_user.username})")
                    logger.info(f"Recipient user details: ID={recipient_user.id}, username={recipient_user.username}, email={recipient_user.email}")
                    try:
                        logger.info(f"Calling create_notification for recipient...")
                        recipient_notification = create_notification(
                            user=recipient_user,
                            notification_type=NotificationType.SEND_RECEIVED,
                            title="Envío recibido",
                            message=f"Recibiste {amount} {asset_type} de {sender_display_name}",
                            data={
                            'transaction_type': 'send',
                            'amount': f'+{amount}',
                            'token_type': asset_type,
                            'currency': asset_type,
                            'sender_name': sender_display_name,
                            'sender_address': user_account.algorand_address,
                            'recipient_name': recipient_display_name,
                            'recipient_address': resolved_recipient_address,
                            'status': 'pending',
                            'created_at': timezone.now().isoformat(),
                            'note': note or '',
                            'type': 'send',
                            'from': sender_display_name,
                            'fromAddress': user_account.algorand_address,
                            'to': recipient_display_name,
                            'toAddress': resolved_recipient_address,
                            'date': timezone.now().strftime('%Y-%m-%d'),
                            'time': timezone.now().strftime('%H:%M'),
                            'avatar': sender_display_name[0] if sender_display_name else 'U',
                            },
                            related_object_type='AlgorandTransaction',
                            related_object_id=result['group_id'],
                            action_url=f"confio://transaction/pending"
                        )
                        logger.info(f"Created recipient notification ID {recipient_notification.id} for user {recipient_user.id}")
                    except Exception as e:
                        logger.error(f"Failed to create recipient notification for user {recipient_user.id}: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    logger.info(f"No recipient user found, recipient_user_id was: {recipient_user_id}")
                    
            except Exception as e:
                logger.error(f"Failed to create notifications: {e}")
                import traceback
                traceback.print_exc()
            
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
            
            # Notifications are now created immediately in AlgorandSponsoredSend mutation
            # No need to create them here after submission
            
            return cls(
                success=True,
                transaction_id=result['tx_id'],
                confirmed_round=result['confirmed_round'],
                fees_saved=result['fees_saved']
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

            # Decode signed transactions (keep exact bytes and best-effort parsed dict for inspection)
            signed_pairs: list = []  # [(bytes, Optional[dict])]
            for i, txn_b64 in enumerate(signed_transactions):
                try:
                    if isinstance(txn_b64, dict):
                        # Defensive: accept object with 'transaction' field
                        txn_b64 = txn_b64.get('transaction')
                    if not isinstance(txn_b64, str):
                        raise ValueError('Each transaction must be a base64 string')

                    # Normalize base64: strip whitespace, handle URL-safe, and pad
                    s = txn_b64.strip().replace('\n', '').replace('\r', '').replace(' ', '')
                    s = s.replace('-', '+').replace('_', '/')
                    
                    # Add padding if needed
                    padding_needed = (4 - len(s) % 4) % 4
                    if padding_needed:
                        s += '=' * padding_needed
                        logger.info(f'Transaction {i}: Added {padding_needed} padding chars to base64')
                    
                    logger.info(f'Transaction {i}: base64 length after padding: {len(s)}, first 50 chars: {s[:50]}')

                    decoded = base64.b64decode(s)
                    try:
                        signed_txn = msgpack.unpackb(decoded, raw=False)
                        logger.info(f'  Opt-in group txn {i}: msgpack parsed')
                    except Exception as pe:
                        signed_txn = None
                        logger.warning(f'  Opt-in group txn {i}: msgpack parse skipped: {pe}')
                    signed_pairs.append((decoded, signed_txn))
                    logger.info(f'  Opt-in group txn {i}: decoded base64 length={len(decoded)}')
                except msgpack.exceptions.ExtraData as e:
                    logger.warning(f'Transaction {i} has extra data after valid msgpack: {e}')
                    # Keep raw bytes if available
                    try:
                        signed_pairs.append((decoded, None))  # type: ignore[name-defined]
                    except Exception:
                        pass
                except msgpack.exceptions.UnpackException as e:
                    logger.warning(f'Transaction {i} is not valid msgpack: {e}. Proceeding with raw bytes.')
                    try:
                        signed_pairs.append((decoded, None))  # type: ignore[name-defined]
                    except Exception:
                        return cls(success=False, error=f'Transaction {i} could not be decoded')
                except Exception as e:
                    logger.error(f'Failed to decode signed transaction {i}: {e}')
                    logger.error(f'Transaction {i} type: {type(txn_b64)}')
                    logger.error(f'Transaction {i} preview: {str(txn_b64)[:64] if txn_b64 else "None"}')
                    return cls(success=False, error=f'Failed to decode transaction {i}: {str(e)}')

            # Reorder if needed: sponsor Payment must be first so MBR lands before opt-ins
            # Reorder sponsor first if we can identify it from parsed dict
            sponsor_index = None
            for i, (_, parsed) in enumerate(signed_pairs):
                if isinstance(parsed, dict) and isinstance(parsed.get('txn'), dict) and parsed['txn'].get('type') == 'pay':
                    sponsor_index = i
                    break
            if sponsor_index is not None and sponsor_index != 0:
                sponsor = signed_pairs.pop(sponsor_index)
                signed_pairs = [sponsor] + signed_pairs
                logger.info('SubmitBusinessOptInGroupMutation: reordered group to put sponsor first')
            elif sponsor_index is None:
                logger.warning('SubmitBusinessOptInGroupMutation: could not parse sponsor; submitting in provided order')

            # Submit group
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )

            submit_bytes = [b for (b, _) in signed_pairs]
            logger.info(f'Submitting business opt-in group of {len(submit_bytes)} txns')
            
            # Log what we're submitting for debugging
            for i, raw_bytes in enumerate(submit_bytes):
                logger.info(f'Transaction {i} size: {len(raw_bytes)} bytes')
                # Log first few bytes to verify it's msgpack
                logger.info(f'Transaction {i} first bytes: {raw_bytes[:10].hex()}')
            
            # Submit as base64-encoded concatenated bytes
            # The Algorand SDK's send_raw_transaction expects base64-encoded data
            import base64
            combined = b''.join(submit_bytes)
            logger.info(f'Submitting concatenated group of {len(combined)} total bytes')
            tx_id = algod_client.send_raw_transaction(base64.b64encode(combined).decode('ascii'))
            
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
            
            # Check if account needs additional funding for MBR
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(user_account.algorand_address)
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
                            user_account.algorand_address,
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
                            user_address=user_account.algorand_address,
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
                            user_address=user_account.algorand_address,
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
                f"Asset {asset_type} (ID: {asset_id}), Address: {user_account.algorand_address[:10]}..."
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


class GenerateAppOptInTransactionMutation(graphene.Mutation):
    """
    Generate a sponsored opt-in transaction for the cUSD application.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        app_id = graphene.Int(required=False)  # Defaults to cUSD app
    
    success = graphene.Boolean()
    error = graphene.String()
    already_opted_in = graphene.Boolean()
    user_transaction = graphene.String()  # Base64 encoded unsigned user transaction
    sponsor_transaction = graphene.String()  # Base64 encoded signed sponsor transaction
    group_id = graphene.String()
    app_id = graphene.Int()
    
    @classmethod
    def mutate(cls, root, info, app_id=None):
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
            
            # Default to cUSD app if not specified
            if not app_id:
                app_id = AlgorandAccountManager.CUSD_APP_ID
                
            if not app_id:
                return cls(success=False, error='No app ID specified and cUSD app not configured')
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(user_account.algorand_address)
            apps_local_state = account_info.get('apps-local-state', [])
            
            if any(app['id'] == app_id for app in apps_local_state):
                logger.info(f"User {user.id} already opted into app {app_id}")
                return cls(
                    success=True,
                    already_opted_in=True,
                    app_id=app_id
                )
            
            # Check user's current balance and min balance requirement
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            # After app opt-in, min balance will increase based on the app's local state schema
            # cUSD app has 2 uint64 fields (is_frozen, is_vault) in local state
            # Base opt-in: 100,000 microAlgos + (2 * 28,500) for the uint64 fields = 157,000 total
            app_mbr_increase = 100_000 + (2 * 28_500)  # 157,000 microAlgos
            min_balance_after_optin = min_balance_required + app_mbr_increase
            
            logger.info(f"User {user_account.algorand_address}: current_balance={current_balance}, "
                       f"min_balance={min_balance_required}, min_after_optin={min_balance_after_optin}")
            
            # Create sponsored opt-in transaction group
            from algosdk.transaction import ApplicationOptInTxn, PaymentTxn, calculate_group_id, SuggestedParams
            from algosdk import mnemonic, account
            import base64
            import msgpack
            
            params = algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Get sponsor credentials
            sponsor_mnemonic = settings.ALGORAND_SPONSOR_MNEMONIC
            sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
            sponsor_address = account.address_from_private_key(sponsor_private_key)
            
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
                receiver=user_account.algorand_address,
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
                sender=user_account.algorand_address,
                sp=opt_in_params,
                index=app_id,
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
            
            logger.info(f"Created sponsored app opt-in transaction group for user {user.id}: App {app_id} (sponsor first)")
            
            # Return sponsored transaction group
            return cls(
                success=True,
                already_opted_in=False,
                user_transaction=user_txn_encoded,
                sponsor_transaction=sponsor_signed_encoded,
                group_id=base64.b64encode(group_id).decode(),
                app_id=app_id
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
                        user_address=user_account.algorand_address,
                        asset_id=asset_id
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
                f"Asset {asset_name} (ID: {asset_id}), Address: {user_account.algorand_address[:10]}..."
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
            
            # Check if user is owner (not employee)
            if jwt_claims.get('business_employee_role'):
                logger.info('CheckBusinessOptIn: User is employee, not owner')
                return cls(needs_opt_in=False, assets=[], error='Only business owners can opt-in')
            
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
