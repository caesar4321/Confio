import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
import json
import logging
import secrets
from datetime import datetime
from .models import Account, WalletPepper

logger = logging.getLogger(__name__)
User = get_user_model()


class Web3AuthUserType(DjangoObjectType):
    algorand_address = graphene.String()
    is_phone_verified = graphene.Boolean()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name']
    
    def resolve_algorand_address(self, info):
        try:
            account = self.accounts.filter(account_type='personal', deleted_at__isnull=True).first()
            # Temporarily using aptos_address field to store Algorand address
            return account.aptos_address if account else None
        except Exception as e:
            logger.error(f"Error resolving algorand_address: {e}")
            return None
    
    def resolve_is_phone_verified(self, info):
        """Check if user has a phone number stored"""
        return bool(self.phone_number)


class Web3AuthLoginMutation(graphene.Mutation):
    """
    Web3Auth authentication mutation.
    Creates/updates user data AND generates JWT tokens using the existing JWT system.
    """
    class Arguments:
        provider = graphene.String(required=True)  # 'google', 'apple', etc.
        web3_auth_id = graphene.String(required=True)  # Web3Auth verifier ID
        email = graphene.String()
        first_name = graphene.String()
        last_name = graphene.String() 
        algorand_address = graphene.String()
        id_token = graphene.String()  # Firebase ID token for verification
        device_fingerprint = graphene.JSONString()  # Device fingerprint data
    
    success = graphene.Boolean()
    error = graphene.String()
    access_token = graphene.String()
    refresh_token = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    
    @classmethod
    def mutate(cls, root, info, provider, web3_auth_id, email=None, first_name=None, 
               last_name=None, algorand_address=None, id_token=None, device_fingerprint=None):
        try:
            from django.contrib.auth import get_user_model
            from graphql_jwt.utils import jwt_encode
            from users.jwt import jwt_payload_handler, refresh_token_payload_handler
            
            User = get_user_model()
            
            # Find or create user based on Firebase UID (which is the Web3Auth verifier ID)
            user, created = User.objects.get_or_create(
                firebase_uid=web3_auth_id,
                defaults={
                    'email': email or f'{web3_auth_id}@confio.placeholder',
                    'first_name': first_name or '',
                    'last_name': last_name or '',
                    'username': email or f'user_{web3_auth_id[:8]}',
                }
            )
            
            # Update user info if provided
            if not created:
                if email and user.email != email:
                    user.email = email
                if first_name and user.first_name != first_name:
                    user.first_name = first_name
                if last_name and user.last_name != last_name:
                    user.last_name = last_name
                # Update last login timestamp
                user.last_login = timezone.now()
                user.save()
            
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
            
            # Create/update Algorand account if address provided
            if algorand_address:
                account, _ = Account.objects.get_or_create(
                    user=user,
                    account_type='personal',
                    defaults={
                        'aptos_address': algorand_address,  # Temporarily using aptos_address field
                    }
                )
                if account.aptos_address != algorand_address:
                    account.aptos_address = algorand_address
                    account.save()
                
                # Update last login timestamp for the account
                account.last_login_at = timezone.now()
                account.save(update_fields=['last_login_at'])
                
                # Check balance and auto-fund if needed
                from blockchain.algorand_account_manager import AlgorandAccountManager
                from algosdk.v2client import algod
                
                try:
                    algod_client = algod.AlgodClient(
                        AlgorandAccountManager.ALGOD_TOKEN,
                        AlgorandAccountManager.ALGOD_ADDRESS
                    )
                    account_info = algod_client.account_info(algorand_address)
                    balance = account_info.get('amount', 0)
                    num_assets = len(account_info.get('assets', []))
                    
                    # Calculate minimum balance needed:
                    # 0.1 ALGO for account + 0.1 ALGO per asset
                    min_balance_needed = 100000 + (num_assets * 100000)  # in microAlgos
                    # MBR for 2 assets: CONFIO and cUSD
                    # 0.1 base + 0.1 CONFIO + 0.1 cUSD = 0.3 ALGO
                    # Sponsor pays opt-in fees separately
                    min_balance_with_buffer = 300000  # 0.3 ALGO (exactly the MBR)
                    
                    if balance < min_balance_with_buffer:
                        # Fund the account to reach 0.3 ALGO
                        funding_amount = min_balance_with_buffer - balance
                        logger.info(f"Auto-funding Web3Auth user {algorand_address} with {funding_amount} microAlgos")
                        
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
                
                # Trigger sponsored opt-in for CONFIO (async)
                from blockchain.algorand_sponsor_service import algorand_sponsor_service
                import asyncio
                
                if AlgorandAccountManager.CONFIO_ASSET_ID:
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        opt_in_result = loop.run_until_complete(
                            algorand_sponsor_service.execute_server_side_opt_in(
                                user_address=algorand_address,
                                asset_id=AlgorandAccountManager.CONFIO_ASSET_ID
                            )
                        )
                        loop.close()
                        
                        if opt_in_result.get('success'):
                            if opt_in_result.get('already_opted_in'):
                                logger.info(f"User {user.id} already opted into CONFIO")
                            else:
                                logger.info(f"Created CONFIO opt-in for user {user.id}")
                    except Exception as e:
                        logger.warning(f"Could not create auto opt-in for CONFIO: {e}")
            
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
                user=user
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
    opted_in_assets = graphene.List(graphene.Int)
    opt_in_errors = graphene.List(graphene.String)
    needs_opt_in = graphene.List(graphene.Int)  # Assets that need frontend opt-in
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
            opted_in_assets = result['opted_in_assets']
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
            needs_opt_in = []
            algo_balance = 0.0
            
            try:
                algod_client = algod.AlgodClient(
                    AlgorandAccountManager.ALGOD_TOKEN,
                    AlgorandAccountManager.ALGOD_ADDRESS
                )
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
                needs_opt_in=needs_opt_in,
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
            # Temporarily using aptos_address field to store Algorand address
            account = user.accounts.filter(account_type='personal').first()
            if account:
                account.aptos_address = algorand_address
                account.save()
            else:
                # Create account if it doesn't exist
                Account.objects.create(
                    user=user,
                    account_type='personal',
                    aptos_address=algorand_address
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
            # Temporarily using aptos_address field to store Algorand address
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # TODO: Implement actual Algorand signature verification
            # For now, we'll just return success for testing
            # In production, you would verify the signature against the message
            # using the Algorand SDK
            
            verified = True  # Placeholder
            
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
            # Temporarily using aptos_address field to store Algorand address
            if not account or not account.aptos_address:
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


class GetServerPepperMutation(graphene.Mutation):
    """
    Get or create a server pepper for wallet key derivation.
    Each user gets exactly one pepper for additional security.
    During grace period after rotation, can optionally return previous pepper.
    """
    class Arguments:
        firebase_uid = graphene.String(required=True)
        request_version = graphene.Int()  # Optional: specific version requested (for grace period)
    
    success = graphene.Boolean()
    pepper = graphene.String()
    version = graphene.Int()
    is_rotated = graphene.Boolean()  # True if pepper was recently rotated
    grace_period_until = graphene.String()  # ISO timestamp when grace period ends
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, firebase_uid, request_version=None):
        try:
            # Verify the user is authenticated and accessing their own pepper
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Check if the firebase_uid matches the authenticated user
            if user.firebase_uid != firebase_uid:
                return cls(success=False, error='Unauthorized access to pepper')
            
            # Use transaction.atomic() for thread safety
            with transaction.atomic():
                pepper_obj, created = WalletPepper.objects.get_or_create(
                    firebase_uid=firebase_uid,
                    defaults={
                        'pepper': secrets.token_hex(32),  # 32 bytes -> 64 char hex
                        'version': 1
                    }
                )
            
            if created:
                logger.info(f'Created new wallet pepper for user {firebase_uid}')
            
            # Check if client requested a specific version (during grace period)
            if request_version and request_version == pepper_obj.previous_version:
                if pepper_obj.is_in_grace_period():
                    logger.info(f'Returning previous pepper v{request_version} during grace period for {firebase_uid}')
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


class RotateServerPepperMutation(graphene.Mutation):
    """
    Rotate the server pepper for a user.
    This will increment the version and generate a new pepper.
    Client must re-wrap (re-encrypt) the seed with the new pepper.
    """
    class Arguments:
        firebase_uid = graphene.String(required=True)
    
    success = graphene.Boolean()
    pepper = graphene.String()
    version = graphene.Int()
    old_version = graphene.Int()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, firebase_uid):
        try:
            # Verify the user is authenticated and accessing their own pepper
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Check if the firebase_uid matches the authenticated user
            if user.firebase_uid != firebase_uid:
                return cls(success=False, error='Unauthorized access to pepper')
            
            # Use select_for_update to lock the row during rotation
            with transaction.atomic():
                try:
                    pepper_obj = WalletPepper.objects.select_for_update().get(
                        firebase_uid=firebase_uid
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
                    
                    logger.info(f'Rotated wallet pepper for user {firebase_uid}: v{old_version} -> v{pepper_obj.version}')
                    
                    return cls(
                        success=True,
                        pepper=pepper_obj.pepper,
                        version=pepper_obj.version,
                        old_version=old_version
                    )
                    
                except WalletPepper.DoesNotExist:
                    # No existing pepper, create one
                    pepper_obj = WalletPepper.objects.create(
                        firebase_uid=firebase_uid,
                        pepper=secrets.token_hex(32),
                        version=1
                    )
                    logger.info(f'Created initial wallet pepper during rotation for user {firebase_uid}')
                    
                    return cls(
                        success=True,
                        pepper=pepper_obj.pepper,
                        version=1,
                        old_version=0
                    )
            
        except Exception as e:
            logger.error(f'Rotate server pepper error: {str(e)}')
            return cls(success=False, error=str(e))


class Web3AuthMutation(graphene.ObjectType):
    web3_auth_login = Web3AuthLoginMutation.Field()
    add_algorand_wallet = AddAlgorandWalletMutation.Field()
    update_algorand_address = UpdateAlgorandAddressMutation.Field()
    verify_algorand_ownership = VerifyAlgorandOwnershipMutation.Field()
    create_algorand_transaction = CreateAlgorandTransactionMutation.Field()
    get_server_pepper = GetServerPepperMutation.Field()
    rotate_server_pepper = RotateServerPepperMutation.Field()


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
                # Temporarily using aptos_address field to store Algorand address
                address = account.aptos_address if account else None
            
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
            # Using aptos_address field to store Algorand address (temporary)
            if not account or not account.aptos_address:
                return []
            
            # TODO: Implement actual Algorand transaction history fetching
            # This would query the Algorand blockchain for transactions
            
            return []  # Placeholder
            
        except Exception as e:
            logger.error(f'Get Algorand transactions error: {str(e)}')
            return []