"""
Blockchain-related GraphQL mutations
"""
import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import graphene
from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from users.models import Account
from .algorand_account_manager import AlgorandAccountManager
from .algorand_sponsor_service import algorand_sponsor_service
from .constants import (
    REFERRAL_ACHIEVEMENT_SLUGS,
    REFERRAL_DAILY_LIMIT,
    REFERRAL_WEEKLY_LIMIT,
    REFERRAL_SINGLE_REVIEW_THRESHOLD,
    REFERRAL_VERIFICATION_TRIGGER,
    REFERRAL_MAX_USERS_PER_IP,
)

logger = logging.getLogger(__name__)


def _get_referral_reward_summary(user) -> dict:
    """Aggregate referral-earned CONFIO balances for a user."""
    from achievements.models import UserAchievement, ConfioRewardTransaction, ReferralWithdrawalLog

    referral_ids = list(
        UserAchievement.objects.filter(
            user=user,
            achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS
        ).values_list('id', flat=True)
    )
    if not referral_ids:
        zero = Decimal('0')
        return {'earned': zero, 'spent': zero, 'available': zero}

    str_ids = [str(pk) for pk in referral_ids]
    earned = (
        ConfioRewardTransaction.objects.filter(
            user=user,
            transaction_type='earned',
            reference_type='achievement',
            reference_id__in=str_ids
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'] or Decimal('0')
    )
    spent = (
        ReferralWithdrawalLog.objects.filter(user=user)
        .aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'] or Decimal('0')
    )
    available = earned - spent
    if available < Decimal('0'):
        available = Decimal('0')
    return {'earned': earned, 'spent': spent, 'available': available}


def _calculate_referral_portion(user, amount: Decimal) -> Decimal:
    """Return the portion of the withdrawal that should be treated as referral-earned CONFIO."""
    if amount <= Decimal('0'):
        return Decimal('0')
    summary = _get_referral_reward_summary(user)
    available = summary['available']
    if available <= Decimal('0'):
        return Decimal('0')
    return min(amount, available)


def _sum_referral_withdrawals(user, since=None) -> Decimal:
    """Sum referral withdrawals in a given window."""
    from achievements.models import ReferralWithdrawalLog

    qs = ReferralWithdrawalLog.objects.filter(user=user)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return qs.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'] or Decimal('0')


def _record_referral_withdrawal(user, amount: Decimal, *, reference_id: str = '', requires_review: bool = False):
    """Persist referral withdrawal metadata and adjust reward balances."""
    if amount <= Decimal('0'):
        return

    from django.db import transaction as db_transaction
    from django.db.models import F
    from achievements.models import ReferralWithdrawalLog, ConfioRewardBalance, ConfioRewardTransaction

    with db_transaction.atomic():
        existing = ReferralWithdrawalLog.all_objects.filter(
            reference_type='send_transaction',
            reference_id=reference_id,
        ).select_for_update().first()

        delta = amount
        if existing:
            previous_amount = existing.amount or Decimal('0')
            if existing.deleted_at is None and previous_amount == amount and existing.requires_review == requires_review:
                return
            existing.amount = amount
            existing.requires_review = requires_review
            existing.deleted_at = None
            existing.save(update_fields=['amount', 'requires_review', 'deleted_at', 'updated_at'])
            log = existing
            delta = amount - previous_amount
        else:
            log = ReferralWithdrawalLog.objects.create(
                user=user,
                amount=amount,
                requires_review=requires_review,
                reference_type='send_transaction',
                reference_id=reference_id,
            )
            delta = amount

        if delta == 0:
            return

        balance, _ = ConfioRewardBalance.objects.get_or_create(user=user)
        ConfioRewardBalance.objects.filter(pk=balance.pk).update(
            total_spent=F('total_spent') + delta,
            total_locked=Greatest(F('total_locked') - delta, Decimal('0')),
        )
        balance.refresh_from_db()

        if delta > 0:
            ConfioRewardTransaction.objects.create(
                user=user,
                transaction_type='spent',
                amount=delta,
                balance_after=balance.total_locked,
                reference_type='referral_withdrawal',
                reference_id=reference_id,
                description='Retiro de recompensas por referidos',
            )


def _check_referral_device_ip_limits(user) -> Optional[str]:
    """Return an error message if the user's referral rewards violate device/IP limits."""
    from achievements.models import UserAchievement

    referral_qs = UserAchievement.objects.filter(
        user=user,
        achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS,
        deleted_at__isnull=True,
    )

    device_hashes = set(
        referral_qs.exclude(device_fingerprint_hash__isnull=True).values_list('device_fingerprint_hash', flat=True)
    )
    if device_hashes:
        conflict = UserAchievement.objects.filter(
            achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS,
            device_fingerprint_hash__in=device_hashes,
            deleted_at__isnull=True,
        ).exclude(user=user).exists()
        if conflict:
            return 'Detectamos varias cuentas usando el mismo dispositivo. Solo la primera cuenta puede retirar recompensas de referidos desde ese dispositivo.'

    ip_addresses = set(
        referral_qs.exclude(claim_ip_address__isnull=True).values_list('claim_ip_address', flat=True)
    )
    for ip in ip_addresses:
        if not ip:
            continue
        distinct_count = (
            UserAchievement.objects.filter(
                achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS,
                claim_ip_address=ip,
                deleted_at__isnull=True,
            )
            .values('user')
            .distinct()
            .count()
        )
        if distinct_count > REFERRAL_MAX_USERS_PER_IP:
            return 'Detectamos múltiples cuentas retirando recompensas desde la misma red. Completa la verificación de identidad para continuar.'

    return None

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
    
    class Arguments:
        account_id = graphene.ID(required=False, description="Explicit Account ID to ensure (personal or business)")

    @classmethod
    def mutate(cls, root, info, account_id=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Resolve a specific account if provided; otherwise default to personal index 0
            if account_id:
                from users.jwt_context import resolve_account_for_write
                acc = resolve_account_for_write(info, account_id=account_id)
                # Client handles atomic opt-in/funding, so disable server-side auto-funding
                result = AlgorandAccountManager.ensure_account_ready(acc, fund_and_opt_in=False)
            else:
                # Backward-compatible path
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
        # Use String to avoid GraphQL 32-bit limits; coerce to int internally
        asset_ids = graphene.List(graphene.String, required=False)  # If not provided, uses default assets
    
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
                # Only add USDC if it exists and user hasn't opted in
                if AlgorandAccountManager.USDC_ASSET_ID and AlgorandAccountManager.USDC_ASSET_ID not in current_assets:
                    asset_ids.append(AlgorandAccountManager.USDC_ASSET_ID)
            
            # Coerce incoming string IDs to ints
            coerced_ids = []
            for aid in asset_ids:
                try:
                    coerced_ids.append(int(aid))
                except Exception:
                    continue
            
            # Filter out assets already opted into
            assets_to_opt_in = [aid for aid in coerced_ids if aid not in current_assets]
            
            if not assets_to_opt_in:
                logger.info("User already opted into all requested assets")
                # Returning null keeps the GraphQL field optional and signals no action required
                return cls(success=True, transactions=None)
            
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
                note=b"Sponsored opt-in with MBR funding"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group with sponsor payment FIRST
            # This ensures user has funds before opt-in transactions are evaluated
            txn_group = [fee_payment_txn] + user_txns
            group_id = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = group_id
            
            # Sign sponsor transaction
            from algosdk import encoding as algo_encoding
            signed_fee_txn = AlgorandAccountManager.SIGNER.sign_transaction(fee_payment_txn)
            
            # Add the signed sponsor transaction FIRST (it's first in the group)
            sponsor_txn_encoded = algo_encoding.msgpack_encode(signed_fee_txn)
            
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
        # Use String to avoid GraphQL Int 32-bit limit
        asset_id = graphene.String(required=True)
    
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
            
            # Coerce asset_id to int for on-chain comparison
            try:
                asset_id_int = int(asset_id)
            except Exception:
                return cls(success=False, error='Invalid asset ID format')

            if any(asset['asset-id'] == asset_id_int for asset in assets):
                return cls(
                    success=True,
                    message=f'Already opted into asset {asset_id_int}'
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
                index=asset_id_int
            )
            
            # Encode transaction for client
            unsigned_txn = base64.b64encode(
                msgpack.packb(opt_in_txn.dictify(), use_bin_type=True)
            ).decode()
            
            # Determine asset name
            asset_name = "Unknown"
            if asset_id_int == AlgorandAccountManager.CONFIO_ASSET_ID:
                asset_name = "CONFIO"
            elif asset_id_int == AlgorandAccountManager.USDC_ASSET_ID:
                asset_name = "USDC"
            elif asset_id_int == AlgorandAccountManager.CUSD_ASSET_ID:
                asset_name = "cUSD"
            
            return cls(
                success=True,
                unsigned_transaction=unsigned_txn,
                message=f'Please sign this transaction to opt into {asset_name} (Asset ID: {asset_id_int})'
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
            
            try:
                amount_decimal = Decimal(str(amount))
            except Exception:
                return cls(success=False, error='Monto inválido')
            if amount_decimal <= Decimal('0'):
                return cls(success=False, error='El monto debe ser mayor a cero')

            asset_type_upper = str(asset_type or '').upper()

            if asset_type_upper == 'CONFIO':
                abuse_error = _check_referral_device_ip_limits(user)
                if abuse_error:
                    return cls(success=False, error=abuse_error)
                
                referral_summary = _get_referral_reward_summary(user)
                if referral_summary['earned'] >= REFERRAL_VERIFICATION_TRIGGER and not user.is_identity_verified:
                    return cls(
                        success=False,
                        error='Necesitas completar la verificación de identidad para seguir retirando recompensas de referidos.'
                    )

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
                    recipient_user = found_user
                    # Get recipient's personal account
                    recipient_user_account = recipient_user.accounts.filter(
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
                
                # Attempt to look up the user by their Algorand address
                try:
                    matching_account = Account.objects.filter(algorand_address=resolved_recipient_address).select_related('user').first()
                    if matching_account:
                        recipient_user = matching_account.user
                except Exception:
                    pass
            
            else:
                return cls(success=False, error='Recipient identification required (user_id, phone, or address)')

            
            # Determine asset ID based on type
            asset_id = None
            if asset_type_upper == 'CONFIO':
                asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
            elif asset_type_upper == 'USDC':
                asset_id = AlgorandAccountManager.USDC_ASSET_ID
            elif asset_type_upper == 'CUSD':
                asset_id = AlgorandAccountManager.CUSD_ASSET_ID
            elif asset_type_upper == 'ALGO':
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
                scale = Decimal(10) ** Decimal(decimals)
                balance_formatted = Decimal(asset_balance) / scale
                
                if balance_formatted < amount_decimal:
                    return cls(
                        success=False,
                        error=f'Insufficient {asset_type} balance. You have {balance_formatted} but trying to send {amount}'
                    )
                
                # Apply referral restrictions for CONFIO withdrawals
                if asset_type_upper == 'CONFIO':
                    referral_summary = _get_referral_reward_summary(user)
                    referral_portion = _calculate_referral_portion(user, amount_decimal)
                    if referral_portion > Decimal('0'):
                        now = timezone.now()
                        if not user.is_identity_verified:
                            daily_total = _sum_referral_withdrawals(user, now - timedelta(days=1))
                            if daily_total + referral_portion > REFERRAL_DAILY_LIMIT:
                                return cls(success=False, error='Las cuentas básicas solo pueden retirar 10 CONFIO de referidos por día. Completa tu verificación para ampliar el límite.')
                            weekly_total = _sum_referral_withdrawals(user, now - timedelta(days=7))
                            if weekly_total + referral_portion > REFERRAL_WEEKLY_LIMIT:
                                return cls(success=False, error='Las cuentas básicas solo pueden retirar 50 CONFIO de referidos por semana. Completa tu verificación para ampliar el límite.')

                        if referral_portion > REFERRAL_SINGLE_REVIEW_THRESHOLD and not user.is_identity_verified:
                            return cls(success=False, error='Necesitas completar la verificación de identidad para retiros mayores a 500 CONFIO provenientes de referidos.')
            # Native ALGO transfers do not use ASA scaling

            # Create sponsored transaction using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create the sponsored transfer (returns unsigned user txn and signed sponsor txn)
                result = loop.run_until_complete(
                    algorand_sponsor_service.create_sponsored_transfer(
                        sender=user_account.algorand_address,
                        recipient=resolved_recipient_address,  # Use the resolved address
                        amount=amount_decimal,
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
    internal_id = graphene.String()
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

                if token_type == 'CONFIO':
                    referral_portion = _calculate_referral_portion(user, amount_dec)
                    if referral_portion > Decimal('0'):
                        requires_review = referral_portion > REFERRAL_SINGLE_REVIEW_THRESHOLD
                        reference_id = str(stx.id) if stx else (result.get('tx_id') or '')
                        _record_referral_withdrawal(
                            user,
                            referral_portion,
                            reference_id=reference_id,
                            requires_review=requires_review,
                        )
                        if requires_review and stx:
                            stx.status = 'AML_REVIEW'
                            stx.save(update_fields=['status'])
            except Exception as pe:
                logger.warning(f"Failed to persist SendTransaction for tx {result.get('tx_id')}: {pe}")
                stx = None

            return cls(
                success=True,
                transaction_id=result['tx_id'],
                internal_id=str(stx.internal_id) if stx else None,
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
            current_min_balance = account_info.get('min-balance', 0)

            # Algorand MBR calculation for asset opt-in:
            # - Base MBR = 100,000 microAlgos (0.1 ALGO)
            # - Each asset adds 100,000 microAlgos
            # - Add safety buffer to handle edge cases and transaction fees
            # The actual minimum balance increases by more than just 100k due to
            # schema changes and other factors, so we use a generous buffer
            ASSET_OPT_IN_MBR = 100_000  # Base asset opt-in cost
            SAFETY_BUFFER = 100_000     # Safety margin (0.1 ALGO)

            required_balance = current_min_balance + ASSET_OPT_IN_MBR
            target_balance = required_balance + SAFETY_BUFFER

            # Calculate funding needed
            funding_needed = max(target_balance - current_balance, 0)

            # Ensure meaningful top-up if any shortfall is detected
            if funding_needed > 0 and funding_needed < 200_000:
                funding_needed = 200_000  # Minimum funding to avoid multiple small transactions

            logger.info(
                "USDC opt-in balance check for %s: balance=%s, min=%s, required=%s, target=%s, funding=%s",
                sender_address,
                current_balance,
                current_min_balance,
                required_balance,
                target_balance,
                funding_needed,
            )

            # Execute opt-in with atomic funding if needed
            logger.info(
                "Executing opt-in for %s (asset %s) with funding=%s",
                sender_address,
                asset_id,
                funding_needed
            )
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    algorand_sponsor_service.execute_server_side_opt_in(
                        user_address=sender_address,
                        asset_id=asset_id,
                        funding_amount=funding_needed
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
            from algosdk import encoding as algo_encoding
            import base64
            import msgpack
            
            params = algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Get sponsor credentials from KMS
            sponsor_address = AlgorandAccountManager.SIGNER.address
            
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
                note=b"Sponsored opt-in with MBR funding"
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
            sponsor_signed = AlgorandAccountManager.SIGNER.sign_transaction(sponsor_payment)
            sponsor_signed_encoded = algo_encoding.msgpack_encode(sponsor_signed)
            
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
            
            # Ensure the account has enough balance to cover the additional ASA min balance
            from algosdk.v2client import algod
            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS
            )
            account_info = algod_client.account_info(user_account.algorand_address)
            current_balance = account_info.get('amount', 0)
            current_min_balance = account_info.get('min-balance', 0)
            required_balance = current_min_balance + 100_000  # Each ASA adds 0.1 ALGO
            buffer = 10_000  # cover transaction fees
            target_balance = required_balance + buffer

            logger.info(
                "USDC opt-in balance check for %s: balance=%s, min=%s, required=%s, target=%s",
                user_account.algorand_address,
                current_balance,
                current_min_balance,
                required_balance,
                target_balance,
            )
            
            # Execute sponsored opt-in using async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                if funding_needed > 0:
                     logger.info(
                        "Funding account %s with %s microAlgos via atomic funding for asset %s opt-in "
                        "(current: %s, required: %s, buffer: %s)",
                        user_account.algorand_address,
                        funding_needed,
                        asset_id_int,
                        current_balance,
                        required_balance,
                        buffer,
                    )

                result = loop.run_until_complete(
                    algorand_sponsor_service.execute_server_side_opt_in(
                        user_address=user_account.algorand_address,
                        asset_id=asset_id_int,
                        funding_amount=funding_needed
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
                from algosdk import encoding as algo_encoding
                try:
                    signer = getattr(algorand_sponsor_service, 'signer', None)
                    if not signer:
                        raise ValueError("KMS signer unavailable")
                    signer.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))
                    signed_sponsor_txn = signer.sign_transaction(transactions[0])
                except Exception as sign_error:
                    logger.error(f'CheckBusinessOptIn: Error signing sponsor transaction: {sign_error}')
                    return cls(error=f"Failed to sign sponsor transaction: {str(sign_error)}")
                
                # Prepare transaction data for frontend (mirror personal flow encoding)
                import msgpack
                user_transactions = []
                for txn in transactions[1:]:  # All except the sponsor fee payment at index 0
                    user_transactions.append(
                        base64.b64encode(msgpack.packb(txn.dictify())).decode('utf-8')
                    )
                
                # Sponsor transaction is already signed - encode the SignedTransaction dict
                sponsor_transaction = algo_encoding.msgpack_encode(signed_sponsor_txn)
                
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

class PrepareAtomicMigrationMutation(graphene.Mutation):
    """
    Generate a complete atomic migration group:
    1. Sponsor -> V2 (Fund MBR for opt-ins)
    2. Sponsor -> V1 (Fund fees for closures)
    3. V2 -> Opt in to assets
    4. V1 -> Close assets to V2
    5. V1 -> Close Algo to V2
    
    Returns the group with signed sponsor txns and unsigned user txns.
    """
    
    class Arguments:
        v1_address = graphene.String(required=True)
        v2_address = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString()
    
    @classmethod
    def mutate(cls, root, info, v1_address, v2_address):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # 1. Validate Addresses
            if len(v1_address) != 58 or len(v2_address) != 58:
                return cls(success=False, error='Invalid Algorand address format')

            from algosdk.v2client import algod
            from algosdk.transaction import AssetTransferTxn, PaymentTxn, calculate_group_id
            from blockchain.algorand_client import get_algod_client
            from blockchain.algorand_account_manager import AlgorandAccountManager
            import base64
            import msgpack
            from algosdk import encoding as algo_encoding
            
            algod_client = get_algod_client()
            params = algod_client.suggested_params()
            
            # 2. Analyze V1 Account (What to sweep)
            try:
                v1_info = algod_client.account_info(v1_address)
            except Exception:
                # If V1 doesn't exist on chain, nothing to migrate
                return cls(success=False, error='V1 account not found on chain')

            v1_assets = v1_info.get('assets', [])
            v1_algo_balance = v1_info.get('amount', 0)
            
            # Determine which assets to migrate (Strict Whitelist + USDC if present)
            # CONFIO/cUSD are mandatory if system configured, USDC if user has it
            
            # Determine which assets to migrate (Strict Whitelist + USDC if present)
            # Also detect if there are leftover "junk" assets that prevent account closure
            assets_to_migrate = []
            legacy_assets_to_burn = []  # Legacy tokens to close to burn address, not V2
            has_leftover_assets = False
            
            # Legacy CONFÍO from before token migration (mainnet)
            # This is a dead token - we close it to a burn address, not V2
            LEGACY_CONFIO_ASSET_ID = 3198568509
            LEGACY_BURN_ADDRESS = 'PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY'
            
            # Helper to check if asset ID is relevant (triggers migration)
            def is_relevant_asset(aid):
                relevant_ids = [
                    AlgorandAccountManager.CONFIO_ASSET_ID,
                    AlgorandAccountManager.CUSD_ASSET_ID,
                    AlgorandAccountManager.USDC_ASSET_ID,
                    LEGACY_CONFIO_ASSET_ID,  # Old CONFÍO token (will be burned)
                ]
                # Filter out None values in case settings are missing
                return aid in [r for r in relevant_ids if r is not None]

            for asset in v1_assets:
                aid = asset['asset-id']
                amount = asset['amount']
                if is_relevant_asset(aid):
                    if aid == LEGACY_CONFIO_ASSET_ID:
                        # Legacy token goes to burn address, not V2
                        legacy_assets_to_burn.append(aid)
                    else:
                        # Regular token goes to V2
                        assets_to_migrate.append(aid)
                else:
                    # If irrelevant asset has balance, we can't easily close it
                    if amount > 0:
                        has_leftover_assets = True
                        logger.warning(f"V1 {v1_address} has leftover asset {aid} with amount {amount}. Cannot fully close account.")
                    # If amount is 0, we could technically opt-out, but for safety we'll just leave it if it's not whitelisted
                    else:
                        # Optional: Could add logic to close 0-balance spam assets here
                         has_leftover_assets = True # Treat as leftover for now to be safe
            
            # Also ensure we target CONFIO/cUSD for V2 opt-in even if V1 doesn't have them yet
            # (To ensure V2 is fully setup for the future)
            # NOTE: We do NOT include legacy CONFIO here - it's a dead token
            target_v2_opt_ins = set(assets_to_migrate)
            if AlgorandAccountManager.CONFIO_ASSET_ID:
                target_v2_opt_ins.add(AlgorandAccountManager.CONFIO_ASSET_ID)
            if AlgorandAccountManager.CUSD_ASSET_ID:
                target_v2_opt_ins.add(AlgorandAccountManager.CUSD_ASSET_ID)
            
            target_v2_opt_ins_list = sorted(list(target_v2_opt_ins))

            # 3. Check V2 State (What opt-ins are needed)
            try:
                v2_info = algod_client.account_info(v2_address)
                v2_existing_assets = set(a['asset-id'] for a in v2_info.get('assets', []))
                v2_balance = v2_info.get('amount', 0)
                v2_min_balance = v2_info.get('min-balance', 0)
            except Exception:
                # V2 might be new
                v2_existing_assets = set()
                v2_balance = 0
                v2_min_balance = 0

            # Determine actual opt-ins needed for V2
            needed_opt_ins = [aid for aid in target_v2_opt_ins_list if aid not in v2_existing_assets]
            
            # 4. Construct Transaction List
            txns = []
            
            # --- MBR Calculation ---
            # Each ASSET opt-in costs 0.1 ALGO (100,000 microAlgo) MBR increase
            # Only fund MBR for NEW opt-ins
            mbr_per_asset = 100_000
            total_mbr_increase = len(needed_opt_ins) * mbr_per_asset
            
            # Check if V2 needs funding for MBR
            # Available balance = Balance - MinBalance
            # We need Available >= 0 AFTER opt-ins
            # So: (Balance + Funding) - (MinBalance + Increase) >= 0
            # Funding >= MinBalance + Increase - Balance
            
            funding_needed_v2 = 0
            if v2_balance < (v2_min_balance + total_mbr_increase):
                funding_needed_v2 = (v2_min_balance + total_mbr_increase) - v2_balance
                # Add a small buffer just in case (e.g. 1000 microAlgo)
                funding_needed_v2 += 1000
            
            # --- Fee Calculation ---
            # Sponsor pays for EVERYTHING.
            # Operations count:
            # 1. Sponsor MBR Fund (Sponsor -> V2)
            # 2. V2 Opt-Ins (N * Axfer)
            # 3. V1 Asset Closes (M * Axfer)
            # 3b. Legacy Asset Burns (L * Axfer)
            # 3c. Clear App Local States (K * Appl)
            # 4. V1 Close Algo (1 * Pay) - OR - V1 Max Send (1 * Pay)
            
            v1_apps = v1_info.get('apps-local-state', [])
            op_count = 1 + len(needed_opt_ins) + len(assets_to_migrate) + len(legacy_assets_to_burn) + len(v1_apps) + 1
            min_fee = 1000
            total_group_fee = op_count * min_fee
            
            # Txn 1: Sponsor Funding V2 (MBR) + Paying Request Group Fee
            sponsor_txn = PaymentTxn(
                sender=AlgorandAccountManager.SPONSOR_ADDRESS,
                sp=params,
                receiver=v2_address,
                amt=funding_needed_v2, 
                note=b"Atomic Migration: V2 MBR Funding"
            )
            sponsor_txn.fee = total_group_fee 
            txns.append({'txn': sponsor_txn, 'signer': 'sponsor', 'desc': 'Sponsor MBR Fund + Fees'})
            
            # Txn Group 2: V2 Opt-Ins
            for aid in needed_opt_ins:
                opt_in = AssetTransferTxn(
                    sender=v2_address,
                    sp=params,
                    receiver=v2_address,
                    amt=0,
                    index=aid
                )
                opt_in.fee = 0
                txns.append({'txn': opt_in, 'signer': 'v2', 'desc': f'Opt-in {aid}'})
                
            # Txn Group 3: V1 Asset Closes (to V2)
            for aid in assets_to_migrate:
                # Use close_assets_to to empty and close the asset
                close_asset = AssetTransferTxn(
                    sender=v1_address,
                    sp=params,
                    receiver=v2_address,
                    close_assets_to=v2_address,
                    amt=0,
                    index=aid
                )
                close_asset.fee = 0
                txns.append({'txn': close_asset, 'signer': 'v1', 'desc': f'Migrate Asset {aid}'})
            
            # Txn Group 3b: Legacy Asset Burns (to burn address, not V2)
            for aid in legacy_assets_to_burn:
                # Close legacy tokens to burn address to remove them from V1
                burn_asset = AssetTransferTxn(
                    sender=v1_address,
                    sp=params,
                    receiver=LEGACY_BURN_ADDRESS,
                    close_assets_to=LEGACY_BURN_ADDRESS,
                    amt=0,
                    index=aid
                )
                burn_asset.fee = 0
                txns.append({'txn': burn_asset, 'signer': 'v1', 'desc': f'Burn Legacy Asset {aid}'})
            
            # Txn Group 3c: Clear App Local States
            # Check for apps that prevent account closure
            from algosdk.transaction import ApplicationClearStateTxn
            # v1_apps fetched above
            
            for app in v1_apps:
                app_id = app['id']
                # Create Clear State checking
                clear_app = ApplicationClearStateTxn(
                    sender=v1_address,
                    sp=params,
                    index=app_id
                )
                clear_app.fee = 0
                txns.append({'txn': clear_app, 'signer': 'v1', 'desc': f'Clear App {app_id}'})
                
            # Txn Group 4: V1 Algo Transfer (Close or Max Send)
            if not has_leftover_assets:
                # Clean sweep: Close account because no assets remain
                close_algo = PaymentTxn(
                    sender=v1_address,
                    sp=params,
                    receiver=AlgorandAccountManager.SPONSOR_ADDRESS,
                    close_remainder_to=AlgorandAccountManager.SPONSOR_ADDRESS,
                    amt=0
                )
                close_algo.fee = 0
                txns.append({'txn': close_algo, 'signer': 'v1', 'desc': 'Migrate ALGO (Close)'})
            else:
                # Dirty sweep: Cannot close account due to spam assets
                # Send Max ALGO (Balance - MinBalance - Fee)
                # Fee is 0 (sponsored), so Balance - MinBalance
                # We need to recalculate MinBalance based on REMAINING assets
                # V1 Min Balance = 100,000 (Base) + 100,000 * len(Assets) + 100,000 * len(Apps) + ...
                # Assets count = Total Assets - Migrated Assets
                
                remaining_assets_count = len(v1_assets) - len(assets_to_migrate) - len(legacy_assets_to_burn)
                # Ensure count is non-negative
                remaining_assets_count = max(0, remaining_assets_count)
                
                required_min_balance = 100_000 + (remaining_assets_count * 100_000)
                
                # Check for other apps (schema) - simplified assumption: no apps or extra cost
                # If they have apps, they need more min balance.
                # Safer: Trust the node's `min-balance` reported earlier, 
                # but subtract the MBR of the assets we ARE closing.
                
                current_min = v1_info.get('min-balance', 100000)
                freed_mbr = (len(assets_to_migrate) + len(legacy_assets_to_burn)) * 100_000
                new_v1_min_balance = max(100_000, current_min - freed_mbr)
                
                amount_to_send = max(0, v1_algo_balance - new_v1_min_balance)
                
                logger.info(f"V1 has leftover assets. Skipping close. Sending {amount_to_send} ALGO. Keeping {new_v1_min_balance} MBR.")
                
                if amount_to_send > 0:
                    send_algo = PaymentTxn(
                        sender=v1_address,
                        sp=params,
                        receiver=AlgorandAccountManager.SPONSOR_ADDRESS,
                        amt=amount_to_send
                    )
                    send_algo.fee = 0
                    txns.append({'txn': send_algo, 'signer': 'v1', 'desc': 'Migrate ALGO (Partial)'})
            
            # 5. Group ID Assignment
            raw_txns = [t['txn'] for t in txns]
            gid = calculate_group_id(raw_txns)
            for t in raw_txns:
                t.group = gid
                
            # 6. Process Output
            output_txns = []
            
            # Sign Sponsor Txn
            signed_sponsor_txn = AlgorandAccountManager.SIGNER.sign_transaction(sponsor_txn)
            sponsor_txn_b64 = algo_encoding.msgpack_encode(signed_sponsor_txn)
            
            # Add to output
            output_txns.append({
                'type': 'sponsor',
                'description': 'Fees & MBR Funding',
                'transaction': sponsor_txn_b64, # Already signed
                'signed': True,
                'signer': 'sponsor'
            })
            
            # Add others as unsigned
            for i, t_info in enumerate(txns):
                if i == 0: continue # Skip sponsor txn we just handled
                
                txn_obj = t_info['txn']
                unsigned_b64 = base64.b64encode(
                    msgpack.packb(txn_obj.dictify(), use_bin_type=True)
                ).decode()
                
                output_txns.append({
                    'type': t_info['signer'], # 'v1' or 'v2'
                    'description': t_info['desc'],
                    'transaction': unsigned_b64,
                    'signed': False,
                    'signer': t_info['signer']
                })
                
            logger.info(f"Generated atomic migration group {gid} with {len(output_txns)} ops")
            
            return cls(
                success=True,
                transactions=output_txns
            )
            
        except Exception as e:
            logger.error(f'Error preparing atomic migration: {str(e)}')
            return cls(success=False, error=str(e))

class BuildAutoSwapTransactionsMutation(graphene.Mutation):
    """
    Builds an unsigned transaction group for auto-swapping.
    Handles two cases:
    1. USDC -> cUSD swap (direct).
    2. ALGO -> cUSD swap (two steps via Tinyman: ALGO -> USDC -> cUSD).

    Returns a base64 encoded msgpack of the transaction group that the client must sign and submit.
    """
    class Arguments:
        input_asset_type = graphene.String(required=True) # 'USDC' or 'ALGO'
        amount = graphene.String(required=True) # Amount in base units (microAlgos or microUSDC)

    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString() # List of transactions (some maybe sponsor-signed for fees)

    @classmethod
    def mutate(cls, root, info, input_asset_type, amount):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')

            # Get user's personal account
            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()

            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')

            from algosdk.v2client import algod
            from blockchain.algorand_client import get_algod_client
            from blockchain.algorand_sponsor_service import algorand_sponsor_service
            import base64
            import msgpack
            from algosdk import encoding as algo_encoding
            from algosdk.transaction import calculate_group_id

            algod_client = get_algod_client()
            params = algod_client.suggested_params()

            if input_asset_type == 'USDC':
                from decimal import Decimal
                from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
                from conversion.models import Conversion
                
                amount_decimal = Decimal(amount) / Decimal('1000000')
                tx_builder = CUSDTransactionBuilder()
                
                # Use actual on-chain USDC balance to avoid underflow from stale cache.
                # The client amount is a hint; the real balance may differ slightly
                # (e.g., right after an ALGO→USDC swap with slippage, or USDC already consumed).
                try:
                    account_info = algod_client.account_info(account.algorand_address)
                    usdc_asset_id = getattr(settings, 'ALGORAND_USDC_ASSET_ID', None)
                    actual_usdc = Decimal('0')
                    if usdc_asset_id:
                        for a in (account_info.get('assets') or []):
                            if a.get('asset-id') == usdc_asset_id:
                                actual_usdc = Decimal(str(a.get('amount', 0))) / Decimal('1000000')
                                break
                    logger.info(
                        "[AutoSwap USDC] on-chain balance=%s requested=%s",
                        actual_usdc,
                        amount_decimal,
                    )
                except Exception as e:
                    logger.warning(f"[AutoSwap USDC] Failed to fetch on-chain USDC balance: {e}")
                    actual_usdc = None
                
                # NOTE: Decimal('0') is falsy in Python, so we MUST use 'is not None'
                if actual_usdc is not None and actual_usdc < amount_decimal:
                    logger.info(f"[AutoSwap USDC] Client sent {amount_decimal}, actual on-chain is {actual_usdc}. Using actual.")
                    amount_decimal = actual_usdc
                
                # Contract minimum is 1 USDC for mint_with_collateral.
                if amount_decimal < Decimal('1.0'):
                    logger.info(f"[AutoSwap USDC] Amount {amount_decimal} below minimum 1.0, skipping.")
                    return cls(success=False, error='amount_below_minimum')
                
                # We need to make sure the user has a transaction hash reference eventually
                # We'll create a PENDING conversion
                conversion = Conversion.objects.create(
                    actor_type='user',
                    actor_user=user,
                    actor_display_name=user.username,
                    actor_address=account.algorand_address,
                    conversion_type='usdc_to_cusd',
                    from_amount=amount_decimal,
                    to_amount=amount_decimal,
                    exchange_rate=Decimal('1.0'),
                    fee_amount=Decimal('0.0'),
                    status='PENDING_SIG'
                )

                tx_result = tx_builder.build_mint_transactions(
                    user_address=account.algorand_address,
                    usdc_amount=amount_decimal,
                    algod_client=algod_client
                )
                
                if not tx_result.get('success'):
                    logger.warning(
                        "[AutoSwap USDC] build_mint_transactions failed: %s",
                        tx_result.get('error', 'unknown_error'),
                    )
                    # Could be needs app opt-in, handle gracefully
                    if tx_result.get('requires_app_optin'):
                        return cls(success=False, error='requires_app_optin', transactions=None)
                    
                    conversion.status = 'FAILED'
                    conversion.save()
                    return cls(success=False, error=tx_result.get('error', 'Failed to build transactions'))

                # Normalize sponsor transactions array of JSON strings and user transactions
                sponsors_norm = []
                for s in tx_result.get('sponsor_transactions', []):
                    sponsors_norm.append(s) # Usually dicts, we serialize to JSON? No, frontend needs them as objects
                    
                txs_norm = []
                for t in tx_result.get('transactions_to_sign', []):
                    txs_norm.append(t.get('txn')) # Just the base64 txn string
                
                response_data = {
                    'internal_id': conversion.internal_id.hex,
                    'transactions': txs_norm,
                    'sponsor_transactions': sponsors_norm,
                    'group_id': tx_result.get('group_id')
                }

                return cls(
                    success=True, 
                    transactions=response_data  # graphene.JSONString serializes this
                )

            elif input_asset_type == 'CUSD':
                from decimal import Decimal
                from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
                from conversion.models import Conversion
                
                amount_decimal = Decimal(amount) / Decimal('1000000')
                tx_builder = CUSDTransactionBuilder()

                # Contract minimum is 1 cUSD for burn_for_collateral.
                if amount_decimal < Decimal('1.0'):
                    logger.info(f"[AutoSwap CUSD] Amount {amount_decimal} below minimum 1.0, skipping.")
                    return cls(success=False, error='amount_below_minimum')
                
                conversion = Conversion.objects.create(
                    actor_type='user',
                    actor_user=user,
                    actor_display_name=user.username,
                    actor_address=account.algorand_address,
                    conversion_type='cusd_to_usdc',
                    from_amount=amount_decimal,
                    to_amount=amount_decimal,
                    exchange_rate=Decimal('1.0'),
                    fee_amount=Decimal('0.0'),
                    status='PENDING_SIG'
                )

                tx_result = tx_builder.build_burn_transactions(
                    user_address=account.algorand_address,
                    cusd_amount=amount_decimal,
                    algod_client=algod_client
                )
                
                if not tx_result.get('success'):
                    if tx_result.get('requires_app_optin'):
                        return cls(success=False, error='requires_app_optin', transactions=None)
                    
                    conversion.status = 'FAILED'
                    conversion.save()
                    return cls(success=False, error=tx_result.get('error', 'Failed to build transactions'))

                sponsors_norm = []
                for s in tx_result.get('sponsor_transactions', []):
                    sponsors_norm.append(s)
                    
                txs_norm = []
                for t in tx_result.get('transactions_to_sign', []):
                    txs_norm.append(t.get('txn'))
                
                response_data = {
                    'internal_id': conversion.internal_id.hex,
                    'transactions': txs_norm,
                    'sponsor_transactions': sponsors_norm,
                    'group_id': tx_result.get('group_id')
                }

                return cls(
                    success=True, 
                    transactions=response_data  # graphene.JSONString serializes this
                )

            elif input_asset_type == 'ALGO':
                from decimal import Decimal
                from conversion.models import Conversion
                from tinyman.v2.client import TinymanV2MainnetClient, TinymanV2TestnetClient
                from tinyman.assets import AssetAmount
                from algosdk import transaction as algo_txn
                from algosdk.transaction import PaymentTxn, AssetTransferTxn, ApplicationCallTxn
                from algosdk.logic import get_application_address
                from algosdk.abi import Method, Returns
                from blockchain.kms_manager import get_kms_signer_from_settings
                
                # Keep these policy numbers aligned with the client auto-swap hook.
                ALGO_RESERVE_THRESHOLD = Decimal('3')
                ALGO_MIN_SWAP_AMOUNT = Decimal('1')
                logger.debug(
                    "[AutoSwap ALGO] policy reserve=%s min_swap=%s",
                    ALGO_RESERVE_THRESHOLD,
                    ALGO_MIN_SWAP_AMOUNT,
                )

                amount_micro = int(amount)
                amount_decimal = Decimal(amount) / Decimal('1000000')

                # Validate and clamp by actual on-chain ALGO excess over reserve.
                account_info = algod_client.account_info(account.algorand_address)
                current_algo_balance = Decimal(account_info.get('amount', 0)) / Decimal('1000000')
                max_swappable_algo = max(Decimal('0'), current_algo_balance - ALGO_RESERVE_THRESHOLD)
                if max_swappable_algo < ALGO_MIN_SWAP_AMOUNT:
                    return cls(success=False, error='algo_amount_below_minimum')
                if amount_decimal > max_swappable_algo:
                    amount_decimal = max_swappable_algo
                    amount_micro = int(amount_decimal * Decimal('1000000'))

                if amount_decimal < ALGO_MIN_SWAP_AMOUNT:
                    return cls(success=False, error='algo_amount_below_minimum')
                
                is_mainnet = getattr(settings, 'ALGORAND_NETWORK', 'testnet') == 'mainnet'
                if is_mainnet:
                    tm_client = TinymanV2MainnetClient(algod_client=algod_client)
                else:
                    tm_client = TinymanV2TestnetClient(algod_client=algod_client)
                
                algo_id = 0
                usdc_id = settings.ALGORAND_USDC_ASSET_ID
                
                pool = tm_client.fetch_pool(algo_id, usdc_id)
                algo_asset = tm_client.fetch_asset(algo_id)
                
                quote = pool.fetch_fixed_input_swap_quote(
                    amount_in=AssetAmount(algo_asset, amount_micro)
                )
                
                # Use conservative output for atomic minting.
                # If swap output is below this minimum the whole group fails, which is correct.
                usdc_out_micro = quote.amount_out_with_slippage.amount
                if usdc_out_micro <= 0:
                    return cls(success=False, error='invalid_swap_quote')

                usdc_out_decimal = Decimal(usdc_out_micro) / Decimal('1000000')
                exchange_rate = usdc_out_decimal / amount_decimal if amount_decimal > 0 else Decimal('0')

                # Reject dust amounts — no point minting < 10 cents.
                if usdc_out_decimal < Decimal('0.10'):
                    return cls(success=False, error='amount_below_minimum')

                # Ensure user is opted into cUSD app before composing the combined group.
                apps_local_state = account_info.get('apps-local-state', [])
                app_opted_in = any(app.get('id') == settings.ALGORAND_CUSD_APP_ID for app in apps_local_state)
                if not app_opted_in:
                    return cls(success=False, error='requires_app_optin', transactions=None)
                
                # Persist this as the final visible conversion leg (USDC -> cUSD),
                # since history/rendering layers only model usdc_to_cusd/cusd_to_usdc.
                conversion = Conversion.objects.create(
                    actor_type='user',
                    actor_user=user,
                    actor_display_name=user.username,
                    actor_address=account.algorand_address,
                    conversion_type='usdc_to_cusd',
                    from_amount=usdc_out_decimal,
                    to_amount=usdc_out_decimal,
                    exchange_rate=Decimal('1.0'),
                    fee_amount=Decimal('0.0'),
                    status='PENDING_SIG'
                )
                
                # Build Tinyman ALGO -> USDC leg
                tinyman_group = pool.prepare_swap_transactions_from_quote(
                    quote=quote,
                    user_address=account.algorand_address,
                    suggested_params=params
                )

                # Canonicalize Tinyman txns before grouping.
                # Some SDK/provider txn objects may not preserve direct field assignment
                # exactly as encoded, which can cause "incomplete group" at submission.
                tinyman_txns = []
                for t in list(tinyman_group.transactions):
                    if hasattr(t, 'dictify'):
                        tinyman_txns.append(algo_txn.Transaction.undictify(t.dictify()))
                    else:
                        tinyman_txns.append(t)

                # Build sponsored USDC -> cUSD leg appended to the same atomic group:
                # [... Tinyman txns ..., sponsor pay, USDC transfer, cUSD app call]
                min_fee = getattr(params, 'min_fee', 1000) or 1000
                app_call_fee = 3 * min_fee  # mint app call + 1 inner transfer safety budget
                sponsor_payment_fee = min_fee

                current_balance = account_info.get('amount', 0)
                min_balance_required = account_info.get('min-balance', 0)
                funding_needed = 0
                if current_balance < min_balance_required:
                    funding_needed = min_balance_required - current_balance
                if funding_needed < min_fee:
                    funding_needed = min_fee

                app_address = get_application_address(settings.ALGORAND_CUSD_APP_ID)
                sponsor_address = settings.ALGORAND_SPONSOR_ADDRESS

                sponsor_params = algo_txn.SuggestedParams(
                    fee=sponsor_payment_fee,
                    first=params.first,
                    last=params.last,
                    gh=params.gh,
                    gen=params.gen,
                    flat_fee=True
                )
                sponsor_payment = PaymentTxn(
                    sender=sponsor_address,
                    sp=sponsor_params,
                    receiver=account.algorand_address,
                    amt=funding_needed,
                    note=b"Min balance top-up for cUSD"
                )

                usdc_params = algo_txn.SuggestedParams(
                    fee=0,
                    first=params.first,
                    last=params.last,
                    gh=params.gh,
                    gen=params.gen,
                    flat_fee=True
                )
                usdc_transfer = AssetTransferTxn(
                    sender=account.algorand_address,
                    sp=usdc_params,
                    receiver=app_address,
                    amt=int(usdc_out_micro),
                    index=settings.ALGORAND_USDC_ASSET_ID
                )

                mint_selector = Method(
                    name="mint_with_collateral",
                    args=[],
                    returns=Returns("void")
                ).get_selector()

                app_params = algo_txn.SuggestedParams(
                    fee=app_call_fee,
                    first=params.first,
                    last=params.last,
                    gh=params.gh,
                    gen=params.gen,
                    flat_fee=True
                )
                app_call = ApplicationCallTxn(
                    sender=sponsor_address,
                    sp=app_params,
                    index=settings.ALGORAND_CUSD_APP_ID,
                    on_complete=algo_txn.OnComplete.NoOpOC,
                    app_args=[mint_selector],
                    foreign_assets=[settings.ALGORAND_USDC_ASSET_ID, settings.ALGORAND_CUSD_ASSET_ID],
                    accounts=[account.algorand_address]
                )

                combined_txns = tinyman_txns + [sponsor_payment, usdc_transfer, app_call]
                if len(combined_txns) > 16:
                    conversion.status = 'FAILED'
                    conversion.error_message = f'atomic_group_too_large:{len(combined_txns)}'
                    conversion.save(update_fields=['status', 'error_message', 'updated_at'])
                    return cls(success=False, error='atomic_group_too_large')

                # Tinyman txns may already include a prior group id; clear before recomputing.
                for txn in combined_txns:
                    txn.group = None

                group_id = calculate_group_id(combined_txns)
                for txn in combined_txns:
                    txn.group = group_id

                signer = get_kms_signer_from_settings()
                signer.assert_matches_address(sponsor_address)
                sponsor_payment_signed = signer.sign_transaction_msgpack(sponsor_payment)
                app_call_signed = signer.sign_transaction_msgpack(app_call)

                sponsor_idx = len(tinyman_txns)
                usdc_idx = sponsor_idx + 1
                app_idx = sponsor_idx + 2

                # User signs all non-sponsor txns in group order.
                txs_norm = [algo_encoding.msgpack_encode(txn) for txn in tinyman_txns]
                txs_norm.append(algo_encoding.msgpack_encode(usdc_transfer))
                
                response_data = {
                    'internal_id': conversion.internal_id.hex,
                    'transactions': txs_norm,
                    'sponsor_transactions': [
                        {
                            'txn': algo_encoding.msgpack_encode(sponsor_payment),
                            'signed': sponsor_payment_signed,
                            'index': sponsor_idx
                        },
                        {
                            'txn': algo_encoding.msgpack_encode(app_call),
                            'signed': app_call_signed,
                            'index': app_idx
                        }
                    ],
                    'group_id': base64.b64encode(group_id).decode('utf-8'),
                    'mint_usdc_tx_index': usdc_idx,
                }
                
                return cls(
                    success=True,
                    transactions=response_data  # graphene.JSONString serializes this
                )
        except Exception as e:
            logger.error(f'Error preparing auto swap: {str(e)}')
            return cls(success=False, error=str(e))

class SubmitAutoSwapTransactionsMutation(graphene.Mutation):
    """
    Submits an auto-swap transaction group to the Algorand network.
    Receives base64-encoded signed user transactions and sponsor transactions.
    Optionally accepts a withdrawal_id to also record the USDC send in transaction history.
    """
    class Arguments:
        internal_id = graphene.String(required=True)
        signed_transactions = graphene.List(graphene.String, required=True)
        sponsor_transactions = graphene.List(graphene.String, required=True)
        withdrawal_id = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, internal_id, signed_transactions, sponsor_transactions, withdrawal_id=None):
        try:
            from conversion.models import Conversion
            from blockchain.algorand_client import get_algod_client
            import base64
            import json as _json

            try:
                conv = Conversion.objects.get(internal_id=internal_id)
            except Conversion.DoesNotExist:
                return cls(success=False, error='conversion_not_found')

            if not isinstance(signed_transactions, list) or not signed_transactions:
                return cls(success=False, error='signed_transactions_required')

            parsed_sponsors = []
            for s in (sponsor_transactions or []):
                parsed_sponsors.append(_json.loads(s) if isinstance(s, str) else s)
                
            raw_txs_by_idx = {}

            # Process Sponsor Transactions
            for e in parsed_sponsors:
                idx = int(e.get('index', 0))
                signed_b64 = e.get('signed')
                if signed_b64:
                    raw_txs_by_idx[idx] = base64.b64decode(signed_b64)
                else:
                    txn_b64 = e.get('txn')
                    if txn_b64:
                         raw_txs_by_idx[idx] = base64.b64decode(txn_b64)

            # Process User Signed Transactions
            total_txs = len(raw_txs_by_idx) + len(signed_transactions)
            ordered_bytes = []
            user_ptr = 0
            
            for i in range(total_txs):
                if i in raw_txs_by_idx:
                    ordered_bytes.append(raw_txs_by_idx[i])
                else:
                    if user_ptr >= len(signed_transactions):
                        return cls(success=False, error='group_shape_mismatch')
                    
                    try:
                        user_blob = base64.b64decode(signed_transactions[user_ptr])
                        ordered_bytes.append(user_blob)
                        user_ptr += 1
                    except Exception:
                        return cls(success=False, error='invalid_user_txn_encoding')

            combined_group = b''.join(ordered_bytes)
            combined_b64 = base64.b64encode(combined_group).decode('utf-8')

            algod_client = get_algod_client()
            txid = algod_client.send_raw_transaction(combined_b64)
            
            conv.status = 'SUBMITTED'
            conv.to_transaction_hash = txid
            conv.save(update_fields=['status', 'to_transaction_hash', 'updated_at'])

            # If this is a burn+send, also finalize the withdrawal record
            # and create a proper SendTransaction (post_save signal in users/signals.py
            # automatically creates the linked UnifiedTransactionTable row, and
            # scan_outbound_confirmations Celery task confirms it)
            if withdrawal_id:
                try:
                    from usdc_transactions.models import USDCWithdrawal
                    from send.models import SendTransaction
                    from users.models import Account
                    from django.utils import timezone as dj_tz

                    w = USDCWithdrawal.objects.get(internal_id=withdrawal_id)
                    w.status = 'PROCESSING'
                    w.updated_at = dj_tz.now()
                    w.save(update_fields=['status', 'updated_at'])

                    # Try to resolve recipient user from their address
                    recipient_user = None
                    recipient_display = w.destination_address[:8] + '...'
                    recipient_type = 'external'
                    try:
                        recipient_acct = Account.objects.filter(
                            algorand_address=w.destination_address,
                            deleted_at__isnull=True
                        ).select_related('user').first()
                        if recipient_acct and recipient_acct.user:
                            recipient_user = recipient_acct.user
                            recipient_display = recipient_acct.user.get_full_name() or recipient_acct.user.username
                            recipient_type = 'user'
                    except Exception:
                        pass

                    # Create the SendTransaction — post_save signal creates UnifiedTransactionTable
                    SendTransaction.objects.create(
                        sender_user=w.actor_user,
                        sender_business=w.actor_business,
                        sender_type=w.actor_type,
                        sender_display_name=w.actor_display_name,
                        sender_address=w.actor_address,
                        recipient_user=recipient_user,
                        recipient_type=recipient_type,
                        recipient_display_name=recipient_display,
                        recipient_address=w.destination_address,
                        amount=w.amount,
                        token_type='USDC',
                        status='SUBMITTED',
                        transaction_hash=txid,
                    )
                except Exception as wdl_err:
                    logger.warning(f"Failed to finalize withdrawal {withdrawal_id}: {wdl_err}")

            return cls(success=True, txid=txid)
            
        except Exception as e:
            logger.error(f"Error submitting auto-swap for {internal_id}: {e}")
            # Mark the Conversion as FAILED so it doesn't stay stuck as 'Pendiente'
            try:
                from conversion.models import Conversion
                Conversion.objects.filter(
                    internal_id=internal_id,
                    status__in=['PENDING_SIG', 'SUBMITTED']
                ).update(status='FAILED', error_message=str(e)[:500])
            except Exception as cleanup_err:
                logger.warning(f"Failed to mark conversion {internal_id} as FAILED: {cleanup_err}")
            # Also mark withdrawal as failed if applicable
            if withdrawal_id:
                try:
                    from usdc_transactions.models import USDCWithdrawal
                    USDCWithdrawal.objects.filter(
                        internal_id=withdrawal_id,
                        status='PENDING'
                    ).update(status='FAILED')
                except Exception:
                    pass
            return cls(success=False, error=str(e))


class BuildBurnAndSendMutation(graphene.Mutation):
    """
    Builds an atomic 5-txn group: burn cUSD → USDC, then send USDC to recipient.
    All in one Algorand atomic group so the USDC send uses the freshly-minted USDC.
    Also creates a USDCWithdrawal record so the send appears in transaction history.
    """
    class Arguments:
        amount = graphene.String(required=True)  # cUSD amount in base units (micro)
        recipient_address = graphene.String(required=True)
        note = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString()

    @classmethod
    def mutate(cls, root, info, amount, recipient_address, note=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')

            account = Account.objects.filter(
                user=user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()

            if not account or not account.algorand_address:
                return cls(success=False, error='No Algorand address found')

            from decimal import Decimal
            from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
            from blockchain.algorand_client import get_algod_client
            from conversion.models import Conversion
            from usdc_transactions.models import USDCWithdrawal

            algod_client = get_algod_client()
            amount_decimal = Decimal(amount) / Decimal('1000000')

            # Reject dust amounts
            if amount_decimal < Decimal('0.10'):
                return cls(success=False, error='amount_below_minimum')

            # Create a PENDING conversion record (for the cUSD→USDC burn)
            conversion = Conversion.objects.create(
                actor_type='user',
                actor_user=user,
                actor_display_name=user.username,
                actor_address=account.algorand_address,
                conversion_type='cusd_to_usdc',
                from_amount=amount_decimal,
                to_amount=amount_decimal,
                exchange_rate=Decimal('1.0'),
                fee_amount=Decimal('0.0'),
                status='PENDING_SIG'
            )

            # Create a PENDING withdrawal record (for the USDC send to recipient)
            actor_business = getattr(account, 'business', None)
            actor_type = 'business' if actor_business else 'user'
            actor_display_name = actor_business.name if actor_business else (user.get_full_name() or user.username)
            withdrawal = USDCWithdrawal.objects.create(
                actor_user=user,
                actor_business=actor_business,
                actor_type=actor_type,
                actor_display_name=actor_display_name,
                actor_address=account.algorand_address,
                amount=amount_decimal,
                destination_address=recipient_address,
                status='PENDING'
            )

            tx_builder = CUSDTransactionBuilder()
            tx_result = tx_builder.build_burn_and_send_transactions(
                user_address=account.algorand_address,
                recipient_address=recipient_address,
                cusd_amount=amount_decimal,
                algod_client=algod_client,
                note=note
            )

            if not tx_result.get('success'):
                if tx_result.get('requires_app_optin'):
                    return cls(success=False, error='requires_app_optin', transactions=None)
                conversion.status = 'FAILED'
                conversion.save()
                withdrawal.status = 'FAILED'
                withdrawal.save()
                return cls(success=False, error=tx_result.get('error', 'Failed to build transactions'))

            # Normalize for the client
            sponsors_norm = []
            for s in tx_result.get('sponsor_transactions', []):
                sponsors_norm.append(s)

            txs_norm = []
            for t in tx_result.get('transactions_to_sign', []):
                txs_norm.append(t.get('txn'))

            response_data = {
                'internal_id': conversion.internal_id.hex,
                'withdrawal_id': str(withdrawal.internal_id),
                'transactions': txs_norm,
                'sponsor_transactions': sponsors_norm,
                'group_id': tx_result.get('group_id')
            }

            return cls(
                success=True,
                transactions=response_data
            )

        except Exception as e:
            logger.error(f'Error building burn+send: {str(e)}')
            return cls(success=False, error=str(e))
