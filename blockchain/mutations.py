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
            
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # Default assets if not specified
            if not asset_ids:
                asset_ids = []
                if AlgorandAccountManager.CONFIO_ASSET_ID:
                    asset_ids.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                # if AlgorandAccountManager.CUSD_ASSET_ID:
                #     asset_ids.append(AlgorandAccountManager.CUSD_ASSET_ID)
            
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
            account_info = algod_client.account_info(account.aptos_address)
            current_assets = [asset['asset-id'] for asset in account_info.get('assets', [])]
            
            transactions = []
            params = algod_client.suggested_params()
            
            for asset_id in asset_ids:
                if asset_id in current_assets:
                    continue  # Already opted in
                
                # Create opt-in transaction
                opt_in_txn = AssetTransferTxn(
                    sender=account.aptos_address,
                    sp=params,
                    receiver=account.aptos_address,
                    amt=0,
                    index=asset_id
                )
                
                # Encode for frontend
                unsigned_txn = base64.b64encode(
                    msgpack.packb(opt_in_txn.dictify())
                ).decode()
                
                # Determine asset name
                asset_name = "Unknown"
                if asset_id == AlgorandAccountManager.CONFIO_ASSET_ID:
                    asset_name = "CONFIO"
                elif asset_id == AlgorandAccountManager.USDC_ASSET_ID:
                    asset_name = "USDC"
                
                transactions.append({
                    'assetId': asset_id,
                    'assetName': asset_name,
                    'transaction': unsigned_txn,
                    'type': 'opt-in'
                })
            
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
            
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.aptos_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
            # Check if already opted in
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            
            account_info = algod_client.account_info(account.aptos_address)
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
                sender=account.aptos_address,
                sp=params,
                receiver=account.aptos_address,
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
            # elif asset_id == AlgorandAccountManager.CUSD_ASSET_ID:
            #     asset_name = "cUSD"
            
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
        
        return account.aptos_address if account else None
    
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
        
        return details


class AlgorandSponsoredSendMutation(graphene.Mutation):
    """
    Create a sponsored send transaction where the server pays for fees.
    Returns unsigned user transaction and signed sponsor transaction for atomic group.
    """
    
    class Arguments:
        recipient = graphene.String(required=True)
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
    def mutate(cls, root, info, recipient, amount, asset_type='CUSD', note=None):
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
            
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.aptos_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')
            
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
                
                account_info = algod_client.account_info(account.aptos_address)
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
                result = loop.run_until_complete(
                    algorand_sponsor_service.create_and_submit_sponsored_transfer(
                        sender=account.aptos_address,
                        recipient=recipient,
                        amount=Decimal(str(amount)),
                        asset_id=asset_id,
                        note=note
                    )
                )
            finally:
                loop.close()
            
            if not result['success']:
                return cls(success=False, error=result.get('error', 'Failed to create sponsored transaction'))
            
            # Log the transaction
            logger.info(
                f"Created sponsored {asset_type} transfer for user {user.id}: "
                f"{amount} from {account.aptos_address[:10]}... to {recipient[:10]}..."
            )
            
            return cls(
                success=True,
                user_transaction=result['user_transaction']['txn'],
                sponsor_transaction=result['sponsor_transaction']['signed'],
                group_id=result['group_id'],
                total_fee=result['total_fee'],
                fee_in_algo=result['fee_in_algo']
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
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Submit the sponsored group using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    algorand_sponsor_service.submit_sponsored_group(
                        signed_user_txn=signed_user_txn,
                        signed_sponsor_txn=signed_sponsor_txn
                    )
                )
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
            
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # Validate it's an Algorand address
            if len(account.aptos_address) != 58:
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
            
            # Execute sponsored opt-in using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    algorand_sponsor_service.execute_server_side_opt_in(
                        user_address=account.aptos_address,
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
                f"Asset {asset_name} (ID: {asset_id}), Address: {account.aptos_address[:10]}..."
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