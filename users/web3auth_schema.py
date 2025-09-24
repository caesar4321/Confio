import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
import json
import logging
import secrets
from datetime import datetime
from .models import Account, WalletPepper, WalletDerivationPepper

logger = logging.getLogger(__name__)
User = get_user_model()


class Web3AuthUserType(DjangoObjectType):
    algorand_address = graphene.String()
    is_phone_verified = graphene.Boolean()
    phone_key = graphene.String()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name']
    
    def resolve_algorand_address(self, info):
        try:
            account = self.accounts.filter(account_type='personal', deleted_at__isnull=True).first()
            return account.algorand_address if account else None
        except Exception as e:
            logger.error(f"Error resolving algorand_address: {e}")
            return None
    
    def resolve_is_phone_verified(self, info):
        """Check if user has a phone number stored"""
        return bool(self.phone_number)

    def resolve_phone_key(self, info):
        try:
            return getattr(self, 'phone_key', None)
        except Exception:
            return None


class Web3AuthLoginMutation(graphene.Mutation):
    """
    Web3Auth authentication mutation.
    Creates/updates user data AND generates JWT tokens using the existing JWT system.
    """
    class Arguments:
        firebase_id_token = graphene.String(required=True)  # Firebase ID token containing all user info
        algorand_address = graphene.String(required=False)  # Client-generated Algorand address (optional at login)
        device_fingerprint = graphene.JSONString()  # Device fingerprint data
    
    success = graphene.Boolean()
    error = graphene.String()
    access_token = graphene.String()
    refresh_token = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    needs_opt_in = graphene.List(graphene.String)  # Asset IDs that need opt-in (use String to avoid 32-bit Int limits)
    opt_in_transactions = graphene.JSONString()  # Unsigned transactions for opt-in
    
    @classmethod
    def mutate(cls, root, info, firebase_id_token, algorand_address=None, device_fingerprint=None):
        try:
            from django.contrib.auth import get_user_model
            from graphql_jwt.utils import jwt_encode
            from users.jwt import jwt_payload_handler, refresh_token_payload_handler
            from firebase_admin import auth
            
            User = get_user_model()
            
            # Verify Firebase ID token and extract user info
            try:
                decoded_token = auth.verify_id_token(firebase_id_token)
            except Exception as e:
                logger.error(f"Firebase token verification failed: {e}")
                return cls(success=False, error="Invalid Firebase ID token")
            
            # Extract user information from verified token
            firebase_uid = decoded_token['uid']
            email = decoded_token.get('email', '')
            name = decoded_token.get('name', '')
            
            # Parse name into first and last
            name_parts = name.split(' ', 1) if name else []
            first_name = name_parts[0] if len(name_parts) > 0 else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            # Extract provider from token
            provider_data = decoded_token.get('firebase', {})
            sign_in_provider = provider_data.get('sign_in_provider', '')
            provider = 'google' if 'google' in sign_in_provider else 'apple' if 'apple' in sign_in_provider else 'unknown'
            
            # Initialize variables that need to be available for return statement
            opt_in_transactions = []
            assets_to_opt_in = []
            
            # Find or create user based on Firebase UID
            user, created = User.objects.get_or_create(
                firebase_uid=firebase_uid,
                defaults={
                    'email': email or f'{firebase_uid}@confio.placeholder',
                    'first_name': first_name,
                    'last_name': last_name,
                    'username': email or f'user_{firebase_uid[:8]}',
                }
            )
            
            # Update user info and last_login
            if not created:
                updated = False
                if email and user.email != email:
                    user.email = email
                    updated = True
                if first_name and user.first_name != first_name:
                    user.first_name = first_name
                    updated = True
                if last_name and user.last_name != last_name:
                    user.last_name = last_name
                    updated = True
                # Update last login timestamp
                user.last_login = timezone.now()
                if updated or user.last_login:
                    user.save()
                # Touch unified activity timestamp
                try:
                    from users.utils import touch_user_activity
                    touch_user_activity(user.id)
                except Exception:
                    pass

            # Ensure account-level activity is tracked regardless of Algorand address presence
            try:
                from users.models import Account
                acct = Account.objects.filter(user=user, account_type='personal', account_index=0).first()
                if acct:
                    acct.last_login_at = timezone.now()
                    acct.save(update_fields=['last_login_at'])
            except Exception:
                pass
            
            # Track device fingerprint if provided
            if device_fingerprint:
                try:
                    from security.utils import track_user_device, calculate_device_fingerprint
                    import json
                    
                    # Parse device fingerprint if it's a string
                    fingerprint_data = json.loads(device_fingerprint) if isinstance(device_fingerprint, str) else device_fingerprint
                    
                    # Track the device
                    track_user_device(user, fingerprint_data, info.context)
                    
                    # Store fingerprint hash on user for achievement validation
                    fingerprint_hash = calculate_device_fingerprint(fingerprint_data)
                    user._device_fingerprint_hash = fingerprint_hash
                    
                    # Also store IP for fraud detection
                    if hasattr(info.context, 'META'):
                        user._registration_ip = info.context.META.get('REMOTE_ADDR')
                    
                    logger.info(f"Device fingerprint tracked for user {user.id}")
                except Exception as e:
                    logger.error(f"Error tracking device fingerprint: {e}")
                    # Don't fail authentication if device tracking fails
            
            # Trigger achievement for new users (Pionero Beta)
            if created:
                try:
                    from achievements.models import AchievementType, UserAchievement
                    from achievements.signals import send_achievement_notification
                    
                    # Check if Pionero Beta achievement exists and user count is below limit
                    pionero_achievement = AchievementType.objects.filter(
                        slug='pionero_beta',
                        is_active=True
                    ).first()
                    
                    if pionero_achievement:
                        # Check if we're still under the 10,000 user limit
                        total_users = User.objects.count()
                        
                        if total_users <= 10000:
                            # Create the achievement for the user
                            user_achievement, achievement_created = UserAchievement.objects.get_or_create(
                                user=user,
                                achievement_type=pionero_achievement,
                                defaults={
                                    'status': 'earned',
                                    'earned_at': timezone.now(),
                                    'device_fingerprint_hash': getattr(user, '_device_fingerprint_hash', None),
                                    'claim_ip_address': getattr(user, '_registration_ip', None),
                                }
                            )
                            
                            if achievement_created:
                                logger.info(f"Pionero Beta achievement awarded to user {user.id} (user #{total_users})")
                                # Send notification (signal will handle this automatically)
                        else:
                            logger.info(f"User {user.id} is user #{total_users}, beyond Pionero Beta limit")
                    
                except Exception as e:
                    logger.error(f"Error awarding Pionero Beta achievement: {e}")
                    # Don't fail authentication if achievement awarding fails
            
            # If no address provided, try to use stored personal account address
            if not algorand_address:
                try:
                    existing_account = Account.objects.filter(
                        user=user,
                        account_type='personal',
                        account_index=0
                    ).first()
                    if existing_account and existing_account.algorand_address:
                        algorand_address = existing_account.algorand_address
                        logger.info(f"Using stored Algorand address for user {user.email}: {algorand_address}")
                except Exception as e:
                    logger.warning(f"Could not determine Algorand address from account: {e}")

            # Create/update Algorand account if address provided
            if algorand_address:
                # Use AlgorandAccountManager to ensure auto opt-ins happen
                from blockchain.algorand_account_manager import AlgorandAccountManager
                
                # Check if account already exists
                existing_account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=0
                ).first()
                
                if existing_account:
                    # Update existing account
                    if existing_account.algorand_address != algorand_address:
                        existing_account.algorand_address = algorand_address
                        existing_account.save()
                    account = existing_account
                    
                    # For existing accounts, check and perform missing opt-ins
                    logger.info(f"Checking opt-ins for existing account: {algorand_address}")
                    result = AlgorandAccountManager.get_or_create_algorand_account(user, algorand_address)
                    account = result['account']
                    opted_in_assets = result.get('opted_in_assets', [])
                    opt_in_errors = result.get('errors', [])
                    
                    if opted_in_assets:
                        logger.info(f"Auto-opted user {user.email} into assets: {opted_in_assets}")
                    if opt_in_errors:
                        logger.warning(f"Opt-in errors for {user.email}: {opt_in_errors}")
                else:
                    # Create new account with auto opt-ins
                    logger.info(f"Creating new account with auto opt-ins: {algorand_address}")
                    result = AlgorandAccountManager.get_or_create_algorand_account(user, algorand_address)
                    account = result['account']
                    opted_in_assets = result.get('opted_in_assets', [])
                    opt_in_errors = result.get('errors', [])
                    
                    if opted_in_assets:
                        logger.info(f"Auto-opted new user {user.email} into assets: {opted_in_assets}")
                    if opt_in_errors:
                        logger.warning(f"Opt-in errors for new user {user.email}: {opt_in_errors}")
                
                # Update last login timestamp for the account
                account.last_login_at = timezone.now()
                account.save(update_fields=['last_login_at'])
                
                # Check balance and auto-fund if needed
                try:
                    from blockchain.algorand_client import get_algod_client
                    algod_client = get_algod_client()
                    
                    # Try to get account info - new accounts might not exist on chain yet
                    try:
                        account_info = algod_client.account_info(algorand_address)
                        balance = account_info.get('amount', 0)
                        current_assets = account_info.get('assets', [])
                    except Exception as e:
                        # Account doesn't exist on chain yet - treat as 0 balance, 0 assets
                        logger.info(f"Account {algorand_address} not on chain yet: {e}")
                        balance = 0
                        current_assets = []
                    
                    current_asset_ids = [asset['asset-id'] for asset in current_assets]
                    num_assets = len(current_assets)
                    
                    # Calculate how many NEW assets we need to opt into (keep ints internally)
                    assets_to_opt_in = []
                    if AlgorandAccountManager.CONFIO_ASSET_ID and AlgorandAccountManager.CONFIO_ASSET_ID not in current_asset_ids:
                        assets_to_opt_in.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                        logger.info(f"User needs to opt into CONFIO: {AlgorandAccountManager.CONFIO_ASSET_ID}")
                    if AlgorandAccountManager.CUSD_ASSET_ID and AlgorandAccountManager.CUSD_ASSET_ID not in current_asset_ids:
                        assets_to_opt_in.append(AlgorandAccountManager.CUSD_ASSET_ID)
                        logger.info(f"User needs to opt into cUSD: {AlgorandAccountManager.CUSD_ASSET_ID}")
                    
                    logger.info(f"Account {algorand_address}: balance={balance}, current_assets={num_assets}, need_opt_in={len(assets_to_opt_in)}")
                    
                    # Get the current minimum balance from Algorand
                    current_min_balance = account_info.get('min-balance', 0)
                    
                    # Check if user will need to opt into cUSD app later
                    apps_local_state = account_info.get('apps-local-state', [])
                    already_opted_into_apps = [app['id'] for app in apps_local_state]
                    needs_cusd_app_optin = AlgorandAccountManager.CUSD_APP_ID and AlgorandAccountManager.CUSD_APP_ID not in already_opted_into_apps
                    
                    # Simple approach: current min + new assets + app if needed
                    new_min_balance = current_min_balance + (len(assets_to_opt_in) * 100000)
                    
                    if needs_cusd_app_optin:
                        # From the error, we know 7 assets need 1,428,000 total
                        # That's 100,000 base + 700,000 for assets = 800,000
                        # So the app needs 1,428,000 - 800,000 = 628,000
                        # But account already has some app min balance in current_min_balance
                        # Testing shows the app adds exactly 158,000 to whatever the current state is
                        app_cost = 158000
                        new_min_balance += app_cost
                        logger.info(f"User will need cUSD app opt-in, adding {app_cost} microAlgos")
                    
                    logger.info(f"MBR calculation:")
                    logger.info(f"  Current assets on account: {num_assets}")
                    logger.info(f"  Current min-balance: {current_min_balance} microAlgos ({current_min_balance/1000000} ALGO)")
                    logger.info(f"  Assets to opt into: {len(assets_to_opt_in)}")
                    logger.info(f"  App opt-in needed: {needs_cusd_app_optin}")
                    logger.info(f"  New min-balance after opt-ins: {new_min_balance} microAlgos ({new_min_balance/1000000} ALGO)")
                    logger.info(f"  Current balance: {balance} microAlgos ({balance/1000000} ALGO)")
                    
                    # Note: On testnet, accounts may have old test assets from previous deployments
                    # We fund based on actual Algorand requirements, not just our current asset IDs
                    
                    # Fund EXACTLY what's needed
                    if balance < new_min_balance:
                        funding_amount = new_min_balance - balance
                        logger.info(f"Auto-funding Web3Auth user {algorand_address} with {funding_amount} microAlgos ({funding_amount/1000000} ALGO)")
                        
                        # Use AlgorandAccountManager's funding logic
                        from algosdk import mnemonic
                        from algosdk.transaction import PaymentTxn, wait_for_confirmation
                        
                        sponsor_private_key = mnemonic.to_private_key(AlgorandAccountManager.SPONSOR_MNEMONIC)
                        params = algod_client.suggested_params()
                        
                        fund_txn = PaymentTxn(
                            sender=AlgorandAccountManager.SPONSOR_ADDRESS,
                            sp=params,
                            receiver=algorand_address,
                            amt=funding_amount
                        )
                        
                        signed_txn = fund_txn.sign(sponsor_private_key)
                        tx_id = algod_client.send_transaction(signed_txn)
                        wait_for_confirmation(algod_client, tx_id, 4)
                        logger.info(f"Successfully funded {algorand_address} with {funding_amount} microAlgos. TX: {tx_id}")
                        
                except Exception as e:
                    logger.warning(f"Could not check/fund account balance: {e}")
                
                # Trigger sponsored opt-in for CONFIO and cUSD (async)
                from blockchain.algorand_sponsor_service import algorand_sponsor_service
                import asyncio
                
                # Generate atomic opt-in transactions for all needed assets
                opt_in_transactions = []
                
                if assets_to_opt_in:
                    logger.info(f"Generating atomic opt-in transactions for assets: {assets_to_opt_in}")
                    try:
                        from blockchain.mutations import GenerateOptInTransactionsMutation
                        # Create a mock info object with authenticated user
                        class MockInfo:
                            class Context:
                                def __init__(self, user):
                                    self.user = user
                            def __init__(self, user):
                                self.context = self.Context(user)
                        
                        mock_info = MockInfo(user)
                        opt_in_result = GenerateOptInTransactionsMutation.mutate(
                            None, mock_info, asset_ids=assets_to_opt_in
                        )
                        
                        if opt_in_result.success and opt_in_result.transactions:
                            opt_in_transactions = opt_in_result.transactions
                            logger.info(f"Generated atomic opt-in transactions for {len(assets_to_opt_in)} assets")
                            logger.info(f"Opt-in transactions structure: {type(opt_in_transactions)}")
                            if isinstance(opt_in_transactions, list) and len(opt_in_transactions) > 0:
                                logger.info(f"First transaction keys: {opt_in_transactions[0].keys() if isinstance(opt_in_transactions[0], dict) else 'Not a dict'}")
                        else:
                            logger.warning(f"Could not generate opt-in transactions: {opt_in_result.error}")
                    except Exception as e:
                        logger.warning(f"Could not create atomic opt-in transactions: {e}")
            
            # Generate JWT tokens using the existing system
            # Access token with default personal account context
            access_payload = jwt_payload_handler(user, context=None)
            access_token = jwt_encode(access_payload)
            
            # Refresh token with default personal account context  
            refresh_payload = refresh_token_payload_handler(
                user, 
                account_type='personal', 
                account_index=0, 
                business_id=None
            )
            refresh_token = jwt_encode(refresh_payload)
            
            logger.info(f'Web3Auth user {"created" if created else "updated"} for {email} ({provider})')
            
            return cls(
                success=True,
                access_token=access_token,
                refresh_token=refresh_token,
                user=user,
                needs_opt_in=[str(a) for a in assets_to_opt_in],
                opt_in_transactions=opt_in_transactions
            )
            
        except Exception as e:
            logger.error(f'Web3Auth login error: {str(e)}')
            return cls(success=False, error=str(e))


class AddAlgorandWalletMutation(graphene.Mutation):
    """
    Add Algorand wallet to an existing Firebase-authenticated user.
    This is called after the user has already signed in with Firebase
    and Web3Auth has generated their Algorand wallet.
    
    Automatically opts the wallet into CONFIO and future cUSD tokens.
    """
    class Arguments:
        algorand_address = graphene.String(required=True)
        web3auth_id = graphene.String()
        provider = graphene.String()
    
    success = graphene.Boolean()
    error = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    is_new_wallet = graphene.Boolean()
    # Use String for ASA IDs to avoid GraphQL Int 32-bit limits
    opted_in_assets = graphene.List(graphene.String)
    opt_in_errors = graphene.List(graphene.String)
    needs_opt_in = graphene.List(graphene.String)  # Assets that need frontend opt-in (use String to avoid 32-bit Int limits)
    algo_balance = graphene.Float()  # Current ALGO balance
    
    @classmethod
    def mutate(cls, root, info, algorand_address, web3auth_id=None, provider=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Validate Algorand address format
            if not algorand_address or len(algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address')
            
            # Use the AlgorandAccountManager for get_or_create with auto opt-ins
            from blockchain.algorand_account_manager import AlgorandAccountManager
            
            result = AlgorandAccountManager.get_or_create_algorand_account(
                user=user,
                existing_address=algorand_address
            )
            
            account = result['account']
            is_new = result['created']
            opted_in_assets = [str(a) for a in result['opted_in_assets']]
            opt_in_errors = result['errors']
            
            # TODO: Store Web3Auth metadata when needed
            # For now, just log the association
            if web3auth_id or provider:
                logger.info(f"Web3Auth metadata for user {user.firebase_uid}: id={web3auth_id}, provider={provider}")
            
            logger.info(
                f'{"Added" if is_new else "Updated"} Algorand wallet for user {user.firebase_uid}: {algorand_address}. '
                f'Opted into assets: {opted_in_assets}'
            )
            
            if opt_in_errors:
                logger.warning(f'Opt-in errors for {algorand_address}: {opt_in_errors}')
            
            # Check what assets need opt-in from frontend
            from algosdk.v2client import algod
            from blockchain.algorand_client import get_algod_client
            needs_opt_in = []
            algo_balance = 0.0
            
            try:
                algod_client = get_algod_client()
                account_info = algod_client.account_info(algorand_address)
                algo_balance = account_info.get('amount', 0) / 1_000_000  # Convert to ALGO
                
                # Check which assets need opt-in
                current_assets = [asset['asset-id'] for asset in account_info.get('assets', [])]
                
                # CONFIO should be opted in
                if AlgorandAccountManager.CONFIO_ASSET_ID and AlgorandAccountManager.CONFIO_ASSET_ID not in current_assets:
                    needs_opt_in.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                
                # Future: cUSD when available
                # if AlgorandAccountManager.CUSD_ASSET_ID and AlgorandAccountManager.CUSD_ASSET_ID not in current_assets:
                #     needs_opt_in.append(AlgorandAccountManager.CUSD_ASSET_ID)
                
            except Exception as e:
                logger.error(f"Error checking opt-in status: {e}")
            
            return cls(
                success=True, 
                user=user,
                is_new_wallet=is_new,
                opted_in_assets=opted_in_assets,
                opt_in_errors=opt_in_errors,
                needs_opt_in=[str(a) for a in needs_opt_in],
                algo_balance=algo_balance
            )
            
        except Exception as e:
            logger.error(f'Add Algorand wallet error: {str(e)}')
            return cls(success=False, error=str(e))


class UpdateAlgorandAddressMutation(graphene.Mutation):
    class Arguments:
        algorand_address = graphene.String(required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    
    @classmethod
    def mutate(cls, root, info, algorand_address):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Validate Algorand address format
            if not algorand_address or len(algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address')
            
            # Update the user's personal account
            account = user.accounts.filter(account_type='personal').first()
            if account:
                account.algorand_address = algorand_address
                account.save()
            else:
                # Create account if it doesn't exist
                Account.objects.create(
                    user=user,
                    account_type='personal',
                    algorand_address=algorand_address
                )
            
            return cls(success=True, user=user)
            
        except Exception as e:
            logger.error(f'Update Algorand address error: {str(e)}')
            return cls(success=False, error=str(e))


class VerifyAlgorandOwnershipMutation(graphene.Mutation):
    class Arguments:
        message = graphene.String(required=True)
        signature = graphene.String(required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    verified = graphene.Boolean()
    
    @classmethod
    def mutate(cls, root, info, message, signature):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            account = user.accounts.filter(account_type='personal').first()
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # Verify the signature using Algorand SDK
            from algosdk import util
            from algosdk.encoding import decode_address
            import base64
            
            try:
                # Get the public key from the address
                public_key = decode_address(account.algorand_address)
                
                # Decode the base64 signature
                signature_bytes = base64.b64decode(signature)
                
                # Verify the signature
                verified = util.verify_bytes(message.encode('utf-8'), signature_bytes, public_key)
            except Exception as verify_error:
                logger.error(f"Signature verification failed: {verify_error}")
                verified = False
            
            if verified:
                # TODO: Implement account verification when needed
                # For now, just log the verification
                logger.info(f"Algorand address verified for user {user.id}")
            
            return cls(success=True, verified=verified)
            
        except Exception as e:
            logger.error(f'Verify Algorand ownership error: {str(e)}')
            return cls(success=False, error=str(e))


class CreateAlgorandTransactionMutation(graphene.Mutation):
    class Arguments:
        to = graphene.String(required=True)
        amount = graphene.Float(required=True)
        note = graphene.String()
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    status = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, to, amount, note=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            account = user.accounts.filter(account_type='personal').first()
            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')
            
            # TODO: Implement actual Algorand transaction creation
            # This would typically:
            # 1. Create the transaction on Algorand
            # 2. Store transaction details in database
            # 3. Return transaction ID
            
            # Placeholder for testing
            transaction_id = f'algo_tx_{datetime.now().timestamp()}'
            
            return cls(
                success=True,
                transaction_id=transaction_id,
                status='pending'
            )
            
        except Exception as e:
            logger.error(f'Create Algorand transaction error: {str(e)}')
            return cls(success=False, error=str(e))


class GetKekPepperMutation(graphene.Mutation):
    """
    Get or create a KEK pepper for seed encryption and re-wrapping (rotating).
    Pepper is per-account (derived from JWT context: user_id + account_type + account_index + business_id).
    During grace period after rotation, can optionally return previous pepper.
    """
    class Arguments:
        request_version = graphene.Int()  # Optional: specific version requested (for grace period)
    
    success = graphene.Boolean()
    pepper = graphene.String()
    version = graphene.Int()
    is_rotated = graphene.Boolean()  # True if pepper was recently rotated
    grace_period_until = graphene.String()  # ISO timestamp when grace period ends
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, request_version=None):
        try:
            # Determine user and account context (JWT-only)
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            from .jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                jwt_context = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')

            # Normalize business account index to an existing one for the business
            if account_type == 'business' and business_id:
                try:
                    from .models import Account
                    idx = Account.objects.filter(
                        business_id=business_id,
                        account_type='business',
                        deleted_at__isnull=True
                    ).order_by('account_index').values_list('account_index', flat=True).first()
                    if idx is not None:
                        if idx != account_index:
                            logger.info(
                                f"GetKekPepper - Normalizing business account_index from {account_index} to {idx} for business {business_id}"
                            )
                        account_index = idx
                except Exception:
                    pass
            
            # Create a unique pepper key based on account context
            # This ensures each account (personal/business) has its own pepper
            if account_type == 'business' and business_id:
                pepper_key = f"user_{user.id}_business_{business_id}_{account_index}"
            else:
                pepper_key = f"user_{user.id}_{account_type}_{account_index}"
            
            # Use transaction.atomic() for thread safety
            with transaction.atomic():
                pepper_obj, created = WalletPepper.objects.get_or_create(
                    account_key=pepper_key,
                    defaults={
                        'pepper': secrets.token_hex(32),  # 32 bytes -> 64 char hex
                        'version': 1
                    }
                )
            
            if created:
                logger.info(
                    f'GetKekPepper: created new pepper (v1) for account_key={pepper_key} '
                    f'user_id={user.id} account_type={account_type} account_index={account_index} business_id={business_id}'
                )
            else:
                logger.info(
                    f'GetKekPepper: fetched pepper v{pepper_obj.version} for account_key={pepper_key} '
                    f'user_id={user.id} account_type={account_type} account_index={account_index} business_id={business_id}'
                )
            
            # Check if client requested a specific version (during grace period)
            if request_version and request_version == pepper_obj.previous_version:
                if pepper_obj.is_in_grace_period():
                    logger.info(f'Returning previous pepper v{request_version} during grace period for {pepper_key}')
                    return cls(
                        success=True,
                        pepper=pepper_obj.previous_pepper,
                        version=pepper_obj.previous_version,
                        is_rotated=True,
                        grace_period_until=pepper_obj.grace_period_until.isoformat() if pepper_obj.grace_period_until else None
                    )
            
            # Return current pepper
            return cls(
                success=True,
                pepper=pepper_obj.pepper,
                version=pepper_obj.version,
                is_rotated=bool(pepper_obj.rotated_at),
                grace_period_until=pepper_obj.grace_period_until.isoformat() if pepper_obj.grace_period_until else None
            )
            
        except Exception as e:
            logger.error(f'Get server pepper error: {str(e)}')
            return cls(success=False, error=str(e))


class RotateKekPepperMutation(graphene.Mutation):
    """
    Rotate the KEK pepper for an account.
    This will increment the version and generate a new pepper.
    Client must re-wrap (re-encrypt) the seed with the new pepper.
    Pepper is per-account based on JWT context.
    """
    class Arguments:
        pass  # No arguments needed, uses JWT context
    
    success = graphene.Boolean()
    pepper = graphene.String()
    version = graphene.Int()
    old_version = graphene.Int()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        try:
            # Get user and account context from JWT
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get account context from JWT
            from .jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                # Fallback to personal account if no JWT context
                jwt_context = {
                    'account_type': 'personal',
                    'account_index': 0,
                    'business_id': None
                }
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')

            # Normalize business account index to an existing one for the business
            if account_type == 'business' and business_id:
                try:
                    from .models import Account
                    idx = Account.objects.filter(
                        business_id=business_id,
                        account_type='business',
                        deleted_at__isnull=True
                    ).order_by('account_index').values_list('account_index', flat=True).first()
                    if idx is not None:
                        if idx != account_index:
                            logger.info(
                                f"GetDerivationPepper - Normalizing business account_index from {account_index} to {idx} for business {business_id}"
                            )
                        account_index = idx
                except Exception:
                    pass
            
            # Create a unique pepper key based on account context
            if account_type == 'business' and business_id:
                pepper_key = f"user_{user.id}_business_{business_id}_{account_index}"
            else:
                pepper_key = f"user_{user.id}_{account_type}_{account_index}"
            
            # Use select_for_update to lock the row during rotation
            with transaction.atomic():
                try:
                    pepper_obj = WalletPepper.objects.select_for_update().get(
                        account_key=pepper_key
                    )
                    old_version = pepper_obj.version
                    old_pepper = pepper_obj.pepper
                    
                    # Rotate: save previous pepper for grace period (7 days)
                    pepper_obj.previous_pepper = old_pepper
                    pepper_obj.previous_version = old_version
                    from datetime import timedelta
                    pepper_obj.grace_period_until = timezone.now() + timedelta(days=7)
                    
                    # Set new pepper and increment version
                    pepper_obj.version += 1
                    pepper_obj.pepper = secrets.token_hex(32)  # New 32-byte pepper
                    pepper_obj.rotated_at = timezone.now()
                    pepper_obj.save()
                    
                    logger.info(f'Rotated KEK pepper for account {pepper_key}: v{old_version} -> v{pepper_obj.version}')
                    
                    return cls(
                        success=True,
                        pepper=pepper_obj.pepper,
                        version=pepper_obj.version,
                        old_version=old_version
                    )
                    
                except WalletPepper.DoesNotExist:
                    # No existing pepper, create one
                    pepper_obj = WalletPepper.objects.create(
                        account_key=pepper_key,
                        pepper=secrets.token_hex(32),
                        version=1
                    )
                    logger.info(f'Created initial KEK pepper during rotation for account {pepper_key}')
                    return cls(
                        success=True,
                        pepper=pepper_obj.pepper,
                        version=1,
                        old_version=0
                    )
        except Exception as e:
            logger.error(f'Rotate server pepper error: {str(e)}')
            return cls(success=False, error=str(e))


class GetDerivationPepperMutation(graphene.Mutation):
    """
    Get or create the non-rotating derivation pepper for wallet key derivation.
    Pepper is per-account (derived from JWT context: user_id + account_type + account_index + business_id).
    This value must never rotate, otherwise addresses change.
    """
    class Arguments:
        pass

    success = graphene.Boolean()
    pepper = graphene.String()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            from .jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                jwt_context = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')

            if account_type == 'business' and business_id:
                pepper_key = f"user_{user.id}_business_{business_id}_{account_index}"
            else:
                pepper_key = f"user_{user.id}_{account_type}_{account_index}"

            with transaction.atomic():
                deriv, created = WalletDerivationPepper.objects.get_or_create(
                    account_key=pepper_key,
                    defaults={
                        'pepper': secrets.token_hex(32)
                    }
                )
            if created:
                logger.info(
                    f'GetDerivationPepper: created derivation pepper for account_key={pepper_key} '
                    f'user_id={user.id} account_type={account_type} account_index={account_index} business_id={business_id}'
                )
            else:
                logger.info(
                    f'GetDerivationPepper: fetched derivation pepper for account_key={pepper_key} '
                    f'user_id={user.id} account_type={account_type} account_index={account_index} business_id={business_id}'
                )

            return cls(success=True, pepper=deriv.pepper)
        except Exception as e:
            logger.error(f'Get derivation pepper error: {str(e)}')
            return cls(success=False, error=str(e))


class OptInToUSDCMutation(graphene.Mutation):
    """
    Opt-in the user's Algorand account to USDC asset for trading.
    This is called when a trader navigates to the Deposit USDC screen.
    """
    
    success = graphene.Boolean()
    already_opted_in = graphene.Boolean()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Use the AlgorandAccountManager to opt-in to USDC
            from blockchain.algorand_account_manager import AlgorandAccountManager
            
            result = AlgorandAccountManager.opt_in_to_usdc(user)
            
            return cls(
                success=result['success'],
                already_opted_in=result.get('already_opted_in', False),
                error=result.get('error')
            )
            
        except Exception as e:
            logger.error(f'USDC opt-in error for user {info.context.user.email}: {str(e)}')
            return cls(success=False, error=str(e))


class Web3AuthMutation(graphene.ObjectType):
    web3_auth_login = Web3AuthLoginMutation.Field()
    add_algorand_wallet = AddAlgorandWalletMutation.Field()
    update_algorand_address = UpdateAlgorandAddressMutation.Field()
    verify_algorand_ownership = VerifyAlgorandOwnershipMutation.Field()
    create_algorand_transaction = CreateAlgorandTransactionMutation.Field()
    get_kek_pepper = GetKekPepperMutation.Field()
    rotate_kek_pepper = RotateKekPepperMutation.Field()
    get_derivation_pepper = GetDerivationPepperMutation.Field()
    opt_in_to_usdc = OptInToUSDCMutation.Field()


class Web3AuthQuery(graphene.ObjectType):
    algorand_balance = graphene.Float(address=graphene.String())
    algorand_transactions = graphene.List(graphene.JSONString, limit=graphene.Int())
    
    def resolve_algorand_balance(self, info, address=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return 0.0
            
            if not address:
                account = user.accounts.filter(account_type='personal').first()
                address = account.algorand_address if account else None
            
            if not address:
                return 0.0
            
            # TODO: Implement actual Algorand balance fetching
            # This would query the Algorand blockchain for the balance
            
            return 0.0  # Placeholder
            
        except Exception as e:
            logger.error(f'Get Algorand balance error: {str(e)}')
            return 0.0
    
    def resolve_algorand_transactions(self, info, limit=10):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return []
            
            account = user.accounts.filter(account_type='personal').first()
            if not account or not account.algorand_address:
                return []
            
            # TODO: Implement actual Algorand transaction history fetching
            # This would query the Algorand blockchain for transactions
            
            return []  # Placeholder
            
        except Exception as e:
            logger.error(f'Get Algorand transactions error: {str(e)}')
            return []
