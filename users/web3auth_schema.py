import graphene
from graphene_django import DjangoObjectType
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
import json
import logging
import re
import secrets
from datetime import datetime, timedelta
from .models import Account, RetiredWalletAddress, WalletPepper, WalletDerivationPepper
from .migration_safety import (
    inspect_address_migration_risk,
    inspect_sponsored_empty_wallet_reenrollment,
    revalidate_sponsored_empty_wallet_reenrollment,
    redact_address,
)
from .utils_username import generate_compliant_username
from .validators import validate_username

logger = logging.getLogger(__name__)
User = get_user_model()

WALLET_REENROLLMENT_GRANT_SALT = 'confio.wallet-reenrollment.v1'
WALLET_REENROLLMENT_PREPARATION_SALT = 'confio.wallet-reenrollment-preparation.v1'
WALLET_REENROLLMENT_GRANT_MAX_AGE_SECONDS = 10 * 60
WALLET_REENROLLMENT_ASSESSMENT_VERSION = 1
WALLET_REENROLLMENT_PERMANENT_REFUSALS = {
    'asset_balance',
    'onchain_state',
    'algo_balance',
    'rekey',
    'non_sponsor_payment',
    'asset_activity',
    'unsupported_transaction',
    'history_too_large',
}


def _is_recent_google_auth(auth_time, now=None):
    try:
        reference = now if now is not None else timezone.now().timestamp()
        age_seconds = float(reference) - float(auth_time)
    except (TypeError, ValueError):
        return False
    return -60 <= age_seconds <= WALLET_REENROLLMENT_GRANT_MAX_AGE_SECONDS


def _should_run_algorand_onboarding(created, client_supplied_address, effective_address):
    """Chain onboarding is signup-only, never an ordinary-login side effect."""
    return bool(created and client_supplied_address and effective_address)


def _wallet_reenrollment_assessment(account):
    value = getattr(account, 'wallet_reenrollment_assessment', None) or {}
    if (
        value.get('version') != WALLET_REENROLLMENT_ASSESSMENT_VERSION
        or value.get('old_algorand_address') != account.algorand_address
        or (value.get('old_bsc_address') or '').lower()
        != (getattr(account, 'bsc_address', None) or '').lower()
        or value.get('status') not in ('eligible', 'ineligible')
    ):
        return None
    if value.get('status') == 'eligible' and (
        int(value.get('snapshot_round') or 0) <= 0
        or int(value.get('sponsor_funding') or 0) <= 0
    ):
        return None
    return value


def _store_wallet_reenrollment_assessment(account, inspection):
    eligible = bool(inspection.get('eligible'))
    reason = str(inspection.get('reason') or 'inspection_failed')
    permanent_refusal = not eligible and reason in WALLET_REENROLLMENT_PERMANENT_REFUSALS
    value = {
        'version': WALLET_REENROLLMENT_ASSESSMENT_VERSION,
        'status': 'eligible' if eligible else ('ineligible' if permanent_refusal else 'retry'),
        'eligible': eligible,
        'reason': reason,
        'old_algorand_address': account.algorand_address,
        'old_bsc_address': getattr(account, 'bsc_address', None) or '',
    }
    if eligible:
        value.update({
            'snapshot_round': int(inspection.get('snapshot_round') or 0),
            'sponsor_funding': int(inspection.get('sponsor_funding') or 0),
        })
    account.wallet_reenrollment_assessment = value
    account.wallet_reenrollment_assessed_at = timezone.now()
    # Publishing an assessment consumes any in-flight lease. This matters not
    # only for the scan owner: completion can publish a newer refusal while an
    # older background scan is still running. Clearing the lease under the
    # Account row lock makes that older worker fail its ownership check instead
    # of overwriting the newer result.
    account.wallet_reenrollment_assessment_lease = ''
    account.wallet_reenrollment_assessment_started_at = None
    account.save(update_fields=[
        'wallet_reenrollment_assessment',
        'wallet_reenrollment_assessed_at',
        'wallet_reenrollment_assessment_lease',
        'wallet_reenrollment_assessment_started_at',
    ])
    return value


def _acquire_wallet_reenrollment_assessment_lease(account_id):
    """Acquire a database-backed, ownership-safe 15 minute scan lease."""
    from django.db.models import Q

    lease = secrets.token_urlsafe(24)
    now = timezone.now()
    expired_before = now - timedelta(minutes=15)
    acquired = Account.objects.filter(pk=account_id).filter(
        Q(wallet_reenrollment_assessment_lease='')
        | Q(wallet_reenrollment_assessment_started_at__isnull=True)
        | Q(wallet_reenrollment_assessment_started_at__lt=expired_before)
    ).update(
        wallet_reenrollment_assessment_lease=lease,
        wallet_reenrollment_assessment_started_at=now,
    )
    return lease if acquired == 1 else None


def _release_wallet_reenrollment_assessment_lease(account_id, lease):
    if not lease:
        return False
    released = Account.objects.filter(
        pk=account_id,
        wallet_reenrollment_assessment_lease=lease,
    ).update(
        wallet_reenrollment_assessment_lease='',
        wallet_reenrollment_assessment_started_at=None,
    )
    return released == 1


def _wallet_reenrollment_challenge(payload):
    return (
        "Confio wallet reenrollment v1\n"
        f"user_id:{payload['user_id']}\n"
        f"account_id:{payload['account_id']}\n"
        f"old_algorand_address:{payload['old_algorand_address']}\n"
        f"old_bsc_address:{payload.get('old_bsc_address') or ''}\n"
        f"inspection_round:{payload['inspection_round']}\n"
        f"nonce:{payload['nonce']}"
    )


def _wallet_reenrollment_identity_payload(user, account, google_subject, google_auth_time):
    return {
        'user_id': user.id,
        'account_id': account.id,
        'old_algorand_address': account.algorand_address,
        'old_bsc_address': getattr(account, 'bsc_address', None) or '',
        'google_subject': google_subject,
        'google_auth_time': google_auth_time,
    }


def _issue_wallet_reenrollment_preparation(user, account, google_subject, google_auth_time):
    payload = {
        'version': 1,
        **_wallet_reenrollment_identity_payload(
            user, account, google_subject, google_auth_time
        ),
        'nonce': secrets.token_urlsafe(32),
    }
    return signing.dumps(payload, salt=WALLET_REENROLLMENT_PREPARATION_SALT)


def _verify_wallet_reenrollment_preparation(token, user, account):
    try:
        payload = signing.loads(
            token,
            salt=WALLET_REENROLLMENT_PREPARATION_SALT,
            max_age=WALLET_REENROLLMENT_GRANT_MAX_AGE_SECONDS,
        )
        if (
            payload.get('version') != 1
            or payload.get('user_id') != user.id
            or payload.get('account_id') != account.id
            or payload.get('old_algorand_address') != account.algorand_address
            or (payload.get('old_bsc_address') or '').lower()
            != (getattr(account, 'bsc_address', None) or '').lower()
            or not payload.get('google_subject')
            or not _is_recent_google_auth(payload.get('google_auth_time'))
            or not payload.get('nonce')
        ):
            return None
        return payload
    except Exception:
        return None


def _issue_wallet_reenrollment_grant(
    user,
    account,
    google_subject,
    google_auth_time,
    inspection,
):
    payload = {
        'version': 2,
        **_wallet_reenrollment_identity_payload(
            user, account, google_subject, google_auth_time
        ),
        'inspection_round': int(inspection.get('snapshot_round') or 0),
        'sponsor_funding': int(inspection.get('sponsor_funding') or 0),
        'nonce': secrets.token_urlsafe(32),
    }
    if payload['inspection_round'] <= 0 or payload['sponsor_funding'] <= 0:
        raise ValueError('A complete wallet inspection is required')
    return (
        _wallet_reenrollment_challenge(payload),
        signing.dumps(payload, salt=WALLET_REENROLLMENT_GRANT_SALT),
    )


def _verify_wallet_reenrollment_grant(grant, user, account, address, signature):
    from eth_account import Account as EvmAccount
    from eth_account.messages import encode_defunct

    try:
        payload = signing.loads(
            grant,
            salt=WALLET_REENROLLMENT_GRANT_SALT,
            max_age=WALLET_REENROLLMENT_GRANT_MAX_AGE_SECONDS,
        )
        if (
            payload.get('version') != 2
            or payload.get('user_id') != user.id
            or payload.get('account_id') != account.id
            or payload.get('old_algorand_address') != account.algorand_address
            or (payload.get('old_bsc_address') or '').lower()
            != (getattr(account, 'bsc_address', None) or '').lower()
            or not payload.get('google_subject')
            or not _is_recent_google_auth(payload.get('google_auth_time'))
            or int(payload.get('inspection_round') or 0) <= 0
            or int(payload.get('sponsor_funding') or 0) <= 0
            or not payload.get('nonce')
        ):
            return None
        recovered = EvmAccount.recover_message(
            encode_defunct(text=_wallet_reenrollment_challenge(payload)),
            signature=signature,
        )
        return payload if recovered.lower() == address.lower() else None
    except Exception:
        return None


def _wallet_reenrollment_server_blocker(account):
    from django.db.models import Q
    from humanitarian.models import HumanitarianRelease
    from send.models import SendTransaction

    # A sponsor-signed Algorand group prepared for this internal recipient can
    # remain valid after the prepare request returns. New prepares persist an
    # address-bound reservation under this same Account row lock. Keep recent
    # unsubmitted reservations (longer than Algorand's maximum transaction
    # lifetime) and every submitted transfer as hard blockers.
    reservation_cutoff = timezone.now() - timedelta(hours=24)
    if SendTransaction.objects.filter(
        recipient_address=account.algorand_address,
        bsc_calls_json='',
        deleted_at__isnull=True,
    ).filter(
        Q(status='PENDING', created_at__gte=reservation_cutoff)
        | Q(status__in=('SPONSORING', 'SIGNED', 'SUBMITTED', 'AML_REVIEW'))
    ).exists():
        return 'pending_inbound_algorand_send'

    # Draft and retryable humanitarian releases are contract-held cUSD
    # entitlements. They have not reached the chain yet, so Indexer history
    # alone cannot prove this address safe to retire.
    if HumanitarianRelease.objects.filter(
        recipient_address=account.algorand_address,
        status__in=('draft', 'failed', 'submitted'),
    ).exists():
        return 'pending_humanitarian_release'

    return None


def _inspect_wallet_reenrollment(account):
    from blockchain.algorand_client import get_algod_client, get_indexer_client

    blocker = _wallet_reenrollment_server_blocker(account)
    if blocker:
        return {'eligible': False, 'reason': blocker}

    return inspect_sponsored_empty_wallet_reenrollment(
        get_algod_client(),
        get_indexer_client(),
        account.algorand_address,
        getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None),
    )


def _revalidate_wallet_reenrollment(account, grant_payload):
    from blockchain.algorand_client import get_algod_client, get_indexer_client

    blocker = _wallet_reenrollment_server_blocker(account)
    if blocker:
        return {'eligible': False, 'reason': blocker}
    return revalidate_sponsored_empty_wallet_reenrollment(
        get_algod_client(),
        get_indexer_client(),
        account.algorand_address,
        getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None),
        grant_payload.get('inspection_round'),
        grant_payload.get('sponsor_funding'),
    )


def _stale_bsc_server_blocker(account):
    """Return a DB-side blocker for replacing the current BSC anchor."""
    address = (account.bsc_address or '').strip()
    if not address:
        return None

    from blockchain.models import SponsoredBatch
    from conversion.models import Conversion
    from payroll.models import PayrollItem
    from presale.models import PresaleMigrationCredit
    from ramps.models import RampTransaction
    from send.models import PhoneInvite, SendTransaction
    from django.db.models import Q

    if SendTransaction.objects.filter(
        recipient_address__iexact=address,
        status__in=(
            'PENDING',
            'SPONSORING',
            'SIGNED',
            'SUBMITTED',
            'AML_REVIEW',
        ),
        deleted_at__isnull=True,
    ).exclude(bsc_calls_json='').exists():
        return 'pending_inbound_send'
    if PayrollItem.objects.filter(
        Q(blockchain_data__bsc_payout__recipient__iexact=address)
        | Q(recipient_address__iexact=address),
        status__in=('PREPARED', 'SUBMITTED'),
        deleted_at__isnull=True,
    ).exists():
        return 'pending_inbound_payroll'
    if PhoneInvite.objects.filter(
        claimed_by=account.user,
        rail='bsc',
        status='claiming',
        deleted_at__isnull=True,
    ).exists():
        return 'pending_inbound_invite_claim'

    if SponsoredBatch.objects.filter(
        user=account.user,
        user_bsc_address__iexact=address,
    ).exists():
        return 'sponsored_batch_history'
    if Conversion.objects.filter(
        user_bsc_address__iexact=address,
        is_deleted=False,
    ).exists():
        return 'conversion_history'
    if RampTransaction.objects.filter(
        actor_address__iexact=address,
        destination='cusd_plus',
    ).exists():
        return 'ramp_history'
    if PresaleMigrationCredit.objects.filter(
        user=account.user,
        bsc_address__iexact=address,
    ).exists():
        return 'presale_credit'
    return None


def _inspect_stale_bsc_reenrollment(account):
    """Fail closed unless replacing this BSC anchor cannot strand Confio value."""
    address = (account.bsc_address or '').strip()
    if not address:
        return {'eligible': True, 'reason': 'no_bsc_anchor'}

    try:
        from cusd_plus import gm_holdings, vault

        blocker = _stale_bsc_server_blocker(account)
        if blocker:
            return {'eligible': False, 'reason': blocker}

        block_tag = vault._rpc('eth_blockNumber', [])
        native_balance = int(vault._rpc('eth_getBalance', [address, block_tag]), 16)
        nonce = int(vault._rpc('eth_getTransactionCount', [address, block_tag]), 16)
        if native_balance:
            return {'eligible': False, 'reason': 'native_balance'}
        if nonce:
            return {'eligible': False, 'reason': 'transaction_history'}

        token_addresses = {
            vault.usdt_address(),
            vault.vault_address(),
            getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', None),
        }
        for token_address in filter(None, token_addresses):
            balance_of = vault.SEL_BALANCE_OF + address.lower().removeprefix('0x').rjust(64, '0')
            raw_balance = vault._rpc(
                'eth_call',
                [{'to': token_address, 'data': balance_of}, block_tag],
            )
            token_balance = int(raw_balance, 16) if raw_balance and raw_balance != '0x' else 0
            if token_balance:
                return {'eligible': False, 'reason': 'token_balance'}

        vesting_address = (
            getattr(settings, 'BSC_VESTING_VAULT_ADDRESS', '') or ''
        ).strip()
        if vesting_address:
            if not re.fullmatch(r'0x[0-9a-fA-F]{40}', vesting_address):
                raise RuntimeError('invalid vesting vault address')
            from eth_utils import keccak

            grant_data = (
                '0x'
                + keccak(text='grants(address)')[:4].hex()
                + address.lower().removeprefix('0x').rjust(64, '0')
            )
            raw_grant = vault._rpc(
                'eth_call',
                [{'to': vesting_address, 'data': grant_data}, block_tag],
            )
            grant_bytes = bytes.fromhex((raw_grant or '').removeprefix('0x'))
            if len(grant_bytes) != 128:
                raise RuntimeError('invalid vesting grant response')
            allocated = int.from_bytes(grant_bytes[0:32], 'big')
            claimed = int.from_bytes(grant_bytes[32:64], 'big')
            if claimed > allocated:
                raise RuntimeError('invalid vesting grant state')
            if allocated > claimed:
                return {'eligible': False, 'reason': 'vesting_grant'}

        registry = gm_holdings.audit_registry()
        if gm_holdings._scan(
            address,
            registry,
            block_tag=block_tag,
            require_complete=True,
        ):
            return {'eligible': False, 'reason': 'stock_balance'}
        return {'eligible': True, 'reason': 'unused_bsc_anchor'}
    except Exception:
        logger.exception(
            "Stale BSC reenrollment inspection failed for account=%s old=%s",
            account.id,
            redact_address(address),
        )
        return {'eligible': False, 'reason': 'inspection_failed'}


class Web3AuthUserType(DjangoObjectType):
    algorand_address = graphene.String()
    bsc_address = graphene.String()
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

    def resolve_bsc_address(self, info):
        # Wallet anchor for BSC-only users: the client must NOT silently mint
        # a replacement master secret when the server already knows a wallet.
        try:
            account = self.accounts.filter(account_type='personal', deleted_at__isnull=True).first()
            return getattr(account, 'bsc_address', None) if account else None
        except Exception as e:
            logger.error(f"Error resolving bsc_address: {e}")
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
        platform_os = graphene.String(required=False)  # 'ios' or 'android' explicitly from client

    success = graphene.Boolean()
    error = graphene.String()
    access_token = graphene.String()
    refresh_token = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    needs_opt_in = graphene.List(graphene.String)  # Asset IDs that need opt-in (use String to avoid 32-bit Int limits)
    opt_in_transactions = graphene.JSONString()  # Unsigned transactions for opt-in
    is_keyless_migrated = graphene.Boolean()  # True if user is V2 Native (Random Secret)
    is_new_user = graphene.Boolean()  # True only when this Web3Auth login created a new User row
    requires_backup_completion = graphene.Boolean()
    wallet_reenrollment_required = graphene.Boolean()
    wallet_reenrollment_preparation_token = graphene.String()
    # Login never performs chain I/O. The background assessment can authorize
    # reenrollment directly; preparation fields remain additive compatibility
    # for clients deployed during the transition.
    wallet_reenrollment_allowed = graphene.Boolean()
    wallet_reenrollment_challenge = graphene.String()
    wallet_reenrollment_grant = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, firebase_id_token, algorand_address=None, device_fingerprint=None, platform_os=None):
        try:

            # Preserve request intent before an existing stored address is
            # loaded below. Legacy accounts must never redo chain onboarding
            # on ordinary login.
            client_supplied_algorand_address = algorand_address


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
            google_identities = (provider_data.get('identities') or {}).get('google.com') or []
            google_subject = str(google_identities[0]) if google_identities else None
            google_auth_time = decoded_token.get('auth_time')
            
            # Initialize variables that need to be available for return statement
            opt_in_transactions = []
            assets_to_opt_in = []
            wallet_reenrollment_allowed = False
            wallet_reenrollment_challenge = None
            wallet_reenrollment_grant = None
            wallet_reenrollment_required = False
            wallet_reenrollment_preparation_token = None

            # Check for soft-deleted accounts before attempting login or recreation
            existing_any_state = User.all_objects.filter(firebase_uid=firebase_uid).first()
            if existing_any_state and existing_any_state.deleted_at:
                logger.warning("Login blocked for soft-deleted user %s", firebase_uid)
                return cls(
                    success=False,
                    error="Tu cuenta fue desactivada por nuestro equipo. Contáctanos si crees que es un error.",
                    access_token=None,
                    refresh_token=None,
                    user=None,
                    needs_opt_in=[],
                    opt_in_transactions=[]
                )
            
            # Find or create user based on Firebase UID
            user, created = User.objects.get_or_create(
                firebase_uid=firebase_uid,
                defaults={
                    'email': email or f'{firebase_uid}@confio.placeholder',
                    'first_name': first_name,
                    'last_name': last_name,
                    'username': generate_compliant_username(email or firebase_uid),
                    'platform_os': platform_os  # Save OS for new users
                }
            )
            if not created:
                is_valid, _ = validate_username(user.username or "")
                if not is_valid:
                    user.username = generate_compliant_username(email or firebase_uid, exclude_user_id=user.id)
                    user.username = generate_compliant_username(email or firebase_uid, exclude_user_id=user.id)
                    user.save(update_fields=['username'])
            
            # Firebase App Check (Warning Mode) - Post-User Resolution
            try:
                from security.integrity_service import app_check_service
                
                # Safely get token and debug error from headers or META
                token_header = ''
                debug_error = ''
                if hasattr(info.context, 'headers') and info.context.headers:
                    token_header = info.context.headers.get('X-Firebase-AppCheck', '')
                    debug_error = info.context.headers.get('X-AppCheck-Debug-Error', '')
                elif hasattr(info.context, 'META') and info.context.META:
                    token_header = info.context.META.get('HTTP_X_FIREBASE_APPCHECK', '')
                    debug_error = info.context.META.get('HTTP_X_APPCHECK_DEBUG_ERROR', '')
                
                # Debug logging to investigate failure
                token_status = "present" if token_header else "missing"
                token_preview = token_header[:10] + "..." if token_header else "None"
                logger.info(f"Web3Auth App Check Debug: Token {token_status} ({token_preview}), User {user.id}" + (f", Client Error: {debug_error}" if debug_error else ""))

                # Ensure fingerprint_str doesn't exceed 255 chars (DB limit)
                fingerprint_str = ''
                if device_fingerprint:
                    from security.utils import calculate_device_fingerprint
                    fingerprint_data = json.loads(device_fingerprint) if isinstance(device_fingerprint, str) else device_fingerprint
                    fingerprint_str = calculate_device_fingerprint(fingerprint_data)
                
                # Determine correct action based on flow
                verdict_action = 'signup' if created else 'login'

                ac_result = app_check_service.verify_and_record(
                    user=user,
                    token=token_header,
                    action=verdict_action,
                    device_fingerprint=fingerprint_str,
                    should_enforce=True
                )
                if not ac_result.get('success', True):
                    app_check_error = ac_result.get('error') or ''
                    if app_check_error == 'Missing App Check Token':
                        return cls(success=False, error="No se pudo verificar el dispositivo en este intento. Revisa Google Play Services, conexión y vuelve a intentar.")
                    return cls(success=False, error="Dispositivo no verificado (App Check failed). Por favor, usa la app oficial.")
            except Exception as e:
                logger.error(f"App Check verification failed: {e}")
                return cls(success=False, error="Error de seguridad. Intenta nuevamente o actualiza la app.")
            
            # Update user info and last_login
            if not created:
                updated = False
                if email and user.email != email:
                    user.email = email
                    updated = True
                # Once identity is verified, legal names are owned by the
                # IdentityVerification record. Do not let Firebase/Google/Apple
                # display names overwrite them on subsequent logins.
                if not user.is_identity_verified:
                    if first_name and user.first_name != first_name:
                        user.first_name = first_name
                        updated = True
                    if last_name and user.last_name != last_name:
                        user.last_name = last_name
                        updated = True
                # WRITE-ONCE: Only set OS if it's currently null/empty
                # Once a user's primary OS is set, we don't overwrite it
                if platform_os and not user.platform_os:
                    user.platform_os = platform_os
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

            # Create/update Algorand account
            # NOTE: usage of client-provided 'algorand_address' is restricted to NEW accounts only
            # to prevent existing users from accidentally overwriting their address or hijacking.

            # Ensure the personal account row ALWAYS exists — BSC-only users
            # (Algorand deprecated) never enter the algorand_address branch
            # below, but BSC address registration and JWT account context
            # still require the row.
            existing_account = None
            try:
                existing_account, _ = Account.objects.get_or_create(
                    user=user,
                    account_type='personal',
                    account_index=0,
                    defaults={'is_keyless_migrated': True}
                )
                if existing_account.algorand_address:
                    # EXISTING USER: Enforce stored address (ignore client input)
                    algorand_address = existing_account.algorand_address
            except Exception:
                pass

            # NATIVE V2: If user was JUST created, we want them to use V2 (random secret).
            # The frontend needs to know this to generate the secret.
            # We determine this status *before* creating the account to set flags correctly.
            is_keyless_migrated_status = False

            if created:
                 # New User -> V2 Native
                 is_keyless_migrated_status = True
            elif existing_account:
                 # Existing User logging in via Web3Auth
                 # DO NOT auto-migrate here. They must complete the frontend migration flow first.
                 is_keyless_migrated_status = existing_account.is_keyless_migrated

            # Keep authentication DB-only. Celery precomputes the finite legacy
            # cohort before the mobile release. Login only reads that durable
            # assessment: eligible accounts get a fresh-auth-bound grant;
            # permanent refusals continue normal V1 recovery; unassessed or
            # transient failures also continue normally until a later scan.
            if (
                provider == 'google'
                and google_subject
                and _is_recent_google_auth(google_auth_time)
                and existing_account
                and existing_account.algorand_address
                and not existing_account.is_keyless_migrated
            ):
                assessment = _wallet_reenrollment_assessment(existing_account)
                if assessment and assessment.get('status') == 'eligible':
                    wallet_reenrollment_allowed = True
                    (
                        wallet_reenrollment_challenge,
                        wallet_reenrollment_grant,
                    ) = _issue_wallet_reenrollment_grant(
                        user,
                        existing_account,
                        google_subject,
                        google_auth_time,
                        assessment,
                    )
                    logger.info(
                        "Wallet reenrollment offered from background assessment "
                        "for account=%s user=%s round=%s",
                        existing_account.id,
                        user.id,
                        assessment.get('snapshot_round'),
                    )
            
            if _should_run_algorand_onboarding(
                created,
                client_supplied_algorand_address,
                algorand_address,
            ):
                # Use AlgorandAccountManager to ensure auto opt-ins happen
                from blockchain.algorand_account_manager import AlgorandAccountManager
                
                # If this is a NEW account creation with a client-supplied address (Native V2)
                if created and not existing_account:
                    logger.info(f"Creating Native V2 account for {user.email} with address {algorand_address}")
                    # We pass the address to get_or_create, which will create the Account object
                
                # Check and perform/create account
                result = AlgorandAccountManager.get_or_create_algorand_account(user, algorand_address)
                account = result['account']
                
                # If this was a fresh creation with a specific address, mark as migrated (Native V2)
                # OR if it's a new user who is defaulting to V2
                if created:
                   account.is_keyless_migrated = True
                   account.save(update_fields=['is_keyless_migrated'])
                   logger.info(f"Marked new user {user.id} as optimized V2 (Native Keyless)")
                   is_keyless_migrated_status = True

                opted_in_assets = result.get('opted_in_assets', [])
                opted_in_assets = result.get('opted_in_assets', [])
                opt_in_errors = result.get('errors', [])
                
                if opted_in_assets:
                    logger.info(f"Auto-opted user {user.email} into assets: {opted_in_assets}")
                if opt_in_errors:
                    logger.warning(f"Opt-in errors for {user.email}: {opt_in_errors}")
                
                # Update last login timestamp for the account
                account.last_login_at = timezone.now()
                account.save(update_fields=['last_login_at'])
                
                # Algorand deprecation: onboarding (MBR funding + opt-ins) only
                # runs when the legacy flag is on. Otherwise the address is
                # stored above and the wallet is left unfunded — new users are
                # BSC-only, existing funded wallets are unaffected.
                from blockchain.algorand_account_manager import algorand_onboarding_enabled
                opt_in_transactions = []
                if not algorand_onboarding_enabled():
                    assets_to_opt_in = []
                    logger.info(f"Algorand onboarding disabled: skipping funding/opt-ins for {algorand_address}")
                else:
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
                            account_info = {}

                        current_asset_ids = [asset['asset-id'] for asset in current_assets]
                        num_assets = len(current_assets)

                        # Calculate how many NEW assets we need to opt into (keep ints internally)
                        # IMPORTANT: keep this list in sync with the default branch of
                        # GenerateOptInTransactionsMutation (blockchain/mutations.py) — both
                        # must opt new users into CONFIO + cUSD + USDC atomically in a single
                        # sponsored group so we never rely on a second client-side roundtrip.
                        assets_to_opt_in = []
                        if AlgorandAccountManager.CONFIO_ASSET_ID and AlgorandAccountManager.CONFIO_ASSET_ID not in current_asset_ids:
                            assets_to_opt_in.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                            logger.info(f"User needs to opt into CONFIO: {AlgorandAccountManager.CONFIO_ASSET_ID}")
                        if AlgorandAccountManager.CUSD_ASSET_ID and AlgorandAccountManager.CUSD_ASSET_ID not in current_asset_ids:
                            assets_to_opt_in.append(AlgorandAccountManager.CUSD_ASSET_ID)
                            logger.info(f"User needs to opt into cUSD: {AlgorandAccountManager.CUSD_ASSET_ID}")
                        if AlgorandAccountManager.USDC_ASSET_ID and AlgorandAccountManager.USDC_ASSET_ID not in current_asset_ids:
                            assets_to_opt_in.append(AlgorandAccountManager.USDC_ASSET_ID)
                            logger.info(f"User needs to opt into USDC: {AlgorandAccountManager.USDC_ASSET_ID}")

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

                    # Generate atomic opt-in transactions for all needed assets
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

            # Track login activity for DAU/MAU
            from users.activity_tracking import touch_last_activity
            touch_last_activity(user)

            logger.info(f'Web3Auth user {"created" if created else "updated"} for {email} ({provider})')

            return cls(
                success=True,
                access_token=access_token,
                refresh_token=refresh_token,
                user=user,
                needs_opt_in=[str(a) for a in assets_to_opt_in],
                opt_in_transactions=opt_in_transactions,
                is_keyless_migrated=is_keyless_migrated_status,
                is_new_user=created,
                requires_backup_completion=user.requires_backup_completion,
                wallet_reenrollment_required=wallet_reenrollment_required,
                wallet_reenrollment_preparation_token=wallet_reenrollment_preparation_token,
                wallet_reenrollment_allowed=wallet_reenrollment_allowed,
                wallet_reenrollment_challenge=wallet_reenrollment_challenge,
                wallet_reenrollment_grant=wallet_reenrollment_grant,
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
            from blockchain.algorand_account_manager import algorand_onboarding_enabled
            needs_opt_in = []
            algo_balance = 0.0

            if not algorand_onboarding_enabled():
                # Algorand deprecation: never steer clients into new opt-ins.
                return cls(
                    success=True,
                    user=user,
                    is_new_wallet=is_new,
                    opted_in_assets=opted_in_assets,
                    opt_in_errors=opt_in_errors,
                    needs_opt_in=[],
                    algo_balance=algo_balance
                )

            try:
                algod_client = get_algod_client()
                account_info = algod_client.account_info(algorand_address)
                algo_balance = account_info.get('amount', 0) / 1_000_000  # Convert to ALGO
                
                # Check which assets need opt-in
                current_assets = [asset['asset-id'] for asset in account_info.get('assets', [])]
                
                # CONFIO, cUSD, and USDC should all be opted in. Keep this list in
                # sync with Web3AuthLoginMutation above and the default branch of
                # GenerateOptInTransactionsMutation (blockchain/mutations.py).
                if AlgorandAccountManager.CONFIO_ASSET_ID and AlgorandAccountManager.CONFIO_ASSET_ID not in current_assets:
                    needs_opt_in.append(AlgorandAccountManager.CONFIO_ASSET_ID)
                if AlgorandAccountManager.CUSD_ASSET_ID and AlgorandAccountManager.CUSD_ASSET_ID not in current_assets:
                    needs_opt_in.append(AlgorandAccountManager.CUSD_ASSET_ID)
                if AlgorandAccountManager.USDC_ASSET_ID and AlgorandAccountManager.USDC_ASSET_ID not in current_assets:
                    needs_opt_in.append(AlgorandAccountManager.USDC_ASSET_ID)
                
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
                # The stored address is the wallet-recovery anchor: once set, a
                # DIFFERENT address is refused (same posture as
                # UpdateAccountAlgorandAddress, which additionally runs the
                # reassignment blocker — legit address changes go through it).
                if account.algorand_address and account.algorand_address != algorand_address:
                    return cls(
                        success=False,
                        error='Esta cuenta ya tiene una billetera registrada. Usa la app actualizada para cambiarla.'
                    )
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
                        'encrypted_pepper': secrets.token_hex(32), # Dual write for safety
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
                pepper=pepper_obj.encrypted_pepper or pepper_obj.pepper,
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
                    old_pepper = pepper_obj.encrypted_pepper or pepper_obj.pepper
                    
                    # Rotate: save previous pepper for grace period (7 days)
                    pepper_obj.previous_pepper = old_pepper
                    pepper_obj.previous_version = old_version
                    from datetime import timedelta
                    pepper_obj.grace_period_until = timezone.now() + timedelta(days=7)
                    
                    # Set new pepper and increment version
                    pepper_obj.version += 1
                    new_val = secrets.token_hex(32)
                    pepper_obj.pepper = new_val
                    pepper_obj.encrypted_pepper = new_val
                    pepper_obj.rotated_at = timezone.now()
                    pepper_obj.save()
                    
                    logger.info(f'Rotated KEK pepper for account {pepper_key}: v{old_version} -> v{pepper_obj.version}')
                    
                    return cls(
                        success=True,
                        pepper=pepper_obj.encrypted_pepper or pepper_obj.pepper,
                        version=pepper_obj.version,
                        old_version=old_version
                    )
                    
                except WalletPepper.DoesNotExist:
                    # No existing pepper, create one
                    val = secrets.token_hex(32)
                    pepper_obj = WalletPepper.objects.create(
                        account_key=pepper_key,
                        pepper=val,
                        encrypted_pepper=val,
                        version=1
                    )
                    logger.info(f'Created initial KEK pepper during rotation for account {pepper_key}')
                    return cls(
                        success=True,
                        pepper=pepper_obj.encrypted_pepper or pepper_obj.pepper,
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
                        'pepper': secrets.token_hex(32),
                        'encrypted_pepper': secrets.token_hex(32)
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

            return cls(success=True, pepper=deriv.encrypted_pepper or deriv.pepper)
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



class PrepareWalletReenrollmentMutation(graphene.Mutation):
    """Run the one-time chain proof outside the authentication hot path."""

    class Arguments:
        preparation_token = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    wallet_reenrollment_allowed = graphene.Boolean()
    wallet_reenrollment_challenge = graphene.String()
    wallet_reenrollment_grant = graphene.String()

    @classmethod
    def mutate(cls, root, info, preparation_token):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return cls(success=False, error='Authentication required')

        account = (
            Account.objects.filter(
                user=user,
                account_type='personal',
                account_index=0,
                deleted_at__isnull=True,
            )
            .first()
        )
        if not account or account.is_keyless_migrated or not account.algorand_address:
            return cls(success=False, error='Account is not eligible for wallet reenrollment')

        preparation = _verify_wallet_reenrollment_preparation(
            preparation_token,
            user,
            account,
        )
        if not preparation:
            return cls(success=False, error='Invalid or expired wallet reenrollment preparation')

        stored = _wallet_reenrollment_assessment(account)
        if stored:
            inspection = stored
        else:
            lease = _acquire_wallet_reenrollment_assessment_lease(account.id)
            if not lease:
                return cls(success=False, error='Wallet reenrollment preparation is already running')
            try:
                inspection = _inspect_wallet_reenrollment(account)
                with transaction.atomic():
                    locked = Account.objects.select_for_update().filter(pk=account.id).first()
                    if (
                        not locked
                        or locked.wallet_reenrollment_assessment_lease != lease
                        or locked.is_keyless_migrated
                        or locked.algorand_address != account.algorand_address
                        or (locked.bsc_address or '').lower()
                        != (account.bsc_address or '').lower()
                    ):
                        return cls(
                            success=False,
                            error='Wallet reenrollment preparation changed; try again',
                        )
                    inspection = _store_wallet_reenrollment_assessment(locked, inspection)
                    account = locked
            finally:
                _release_wallet_reenrollment_assessment_lease(account.id, lease)
        if not (
            inspection.get('eligible')
            or inspection.get('status') == 'eligible'
        ):
            logger.info(
                "Wallet reenrollment preflight refused for account=%s user=%s reason=%s",
                account.id,
                user.id,
                inspection.get('reason'),
            )
            # This is not an authentication failure. The account may be a
            # perfectly valid V1 wallet with real activity; the client must
            # continue through its normal anchored recovery path.
            return cls(
                success=True,
                error=None,
                wallet_reenrollment_allowed=False,
            )

        challenge, grant = _issue_wallet_reenrollment_grant(
            user,
            account,
            preparation.get('google_subject'),
            preparation.get('google_auth_time'),
            inspection,
        )
        logger.info(
            "Wallet reenrollment prepared for account=%s user=%s old=%s round=%s",
            account.id,
            user.id,
            redact_address(account.algorand_address),
            inspection.get('snapshot_round'),
        )
        return cls(
            success=True,
            error=None,
            wallet_reenrollment_allowed=True,
            wallet_reenrollment_challenge=challenge,
            wallet_reenrollment_grant=grant,
        )


class CompleteWalletReenrollmentMutation(graphene.Mutation):
    """Atomically retire a proven-empty legacy wallet and bind its V2 BSC replacement."""

    class Arguments:
        bsc_address = graphene.String(required=True)
        reenrollment_grant = graphene.String(required=True)
        bsc_signature = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, bsc_address, reenrollment_grant, bsc_signature):
        import re

        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return cls(success=False, error='Authentication required')

        address = (bsc_address or '').strip()
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
            return cls(success=False, error='Invalid BSC address')

        try:
            # Chain/indexer verification can take seconds. Run it before the
            # write transaction so an affected user's network latency does not
            # hold an Account row lock or a database connection hostage. The
            # short transaction below re-verifies the signed anchors and every
            # DB-side reservation under the lock before committing.
            inspected_account = (
                Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=0,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if not inspected_account:
                return cls(success=False, error='Account not found')
            if (
                inspected_account.is_keyless_migrated
                and not inspected_account.algorand_address
                and inspected_account.bsc_address
                and inspected_account.bsc_address.lower() == address.lower()
            ):
                return cls(success=True, error=None)
            if inspected_account.is_keyless_migrated or not inspected_account.algorand_address:
                return cls(success=False, error='Account is not eligible for wallet reenrollment')

            inspected_grant = _verify_wallet_reenrollment_grant(
                reenrollment_grant,
                user,
                inspected_account,
                address,
                bsc_signature,
            )
            if not inspected_grant:
                return cls(success=False, error='Invalid or expired wallet reenrollment proof')
            inspected_reenrollment = _revalidate_wallet_reenrollment(
                inspected_account,
                inspected_grant,
            )
            inspected_bsc = {'eligible': True, 'reason': 'same_bsc_anchor'}
            if (
                inspected_account.bsc_address
                and inspected_account.bsc_address.lower() != address.lower()
            ):
                inspected_bsc = _inspect_stale_bsc_reenrollment(inspected_account)

            with transaction.atomic():
                account = (
                    Account.objects.select_for_update()
                    .filter(
                        user=user,
                        account_type='personal',
                        account_index=0,
                        deleted_at__isnull=True,
                    )
                    .first()
                )
                if not account:
                    return cls(success=False, error='Account not found')

                # Safe retry after a response was lost.
                if (
                    account.is_keyless_migrated
                    and not account.algorand_address
                    and account.bsc_address
                    and account.bsc_address.lower() == address.lower()
                ):
                    return cls(success=True, error=None)

                if account.is_keyless_migrated or not account.algorand_address:
                    return cls(success=False, error='Account is not eligible for wallet reenrollment')

                grant_payload = _verify_wallet_reenrollment_grant(
                    reenrollment_grant,
                    user,
                    account,
                    address,
                    bsc_signature,
                )
                if not grant_payload:
                    return cls(success=False, error='Invalid or expired wallet reenrollment proof')

                # Account preparation/claim paths serialize on this same row.
                # Recheck their database reservations after acquiring the lock;
                # only the slow chain evidence is reused from above.
                server_blocker = _wallet_reenrollment_server_blocker(account)
                reenrollment = (
                    {'eligible': False, 'reason': server_blocker}
                    if server_blocker
                    else inspected_reenrollment
                )
                if not reenrollment.get('eligible'):
                    _store_wallet_reenrollment_assessment(account, reenrollment)
                    logger.warning(
                        "Wallet reenrollment refused for account=%s user=%s reason=%s",
                        account.id,
                        user.id,
                        reenrollment.get('reason'),
                    )
                    return cls(success=False, error='The previous wallet is not safe to retire')

                if (
                    account.bsc_address
                    and account.bsc_address.lower() != address.lower()
                ):
                    bsc_blocker = _stale_bsc_server_blocker(account)
                    bsc_reenrollment = (
                        {'eligible': False, 'reason': bsc_blocker}
                        if bsc_blocker
                        else inspected_bsc
                    )
                    if not bsc_reenrollment.get('eligible'):
                        bsc_reason = bsc_reenrollment.get('reason') or 'unsafe'
                        account.wallet_reenrollment_assessment = {
                            'version': WALLET_REENROLLMENT_ASSESSMENT_VERSION,
                            'status': 'retry' if bsc_reason == 'inspection_failed' else 'ineligible',
                            'eligible': False,
                            'reason': f'bsc_{bsc_reason}',
                            'old_algorand_address': account.algorand_address,
                            'old_bsc_address': account.bsc_address or '',
                        }
                        account.wallet_reenrollment_assessed_at = timezone.now()
                        account.wallet_reenrollment_assessment_lease = ''
                        account.wallet_reenrollment_assessment_started_at = None
                        account.save(update_fields=[
                            'wallet_reenrollment_assessment',
                            'wallet_reenrollment_assessed_at',
                            'wallet_reenrollment_assessment_lease',
                            'wallet_reenrollment_assessment_started_at',
                        ])
                        logger.warning(
                            "Wallet reenrollment refused for account=%s user=%s old_bsc=%s reason=%s",
                            account.id,
                            user.id,
                            redact_address(account.bsc_address),
                            bsc_reenrollment.get('reason'),
                        )
                        return cls(success=False, error='The previous BSC wallet is not safe to replace')

                duplicate = (
                    Account.objects.filter(
                        bsc_address__iexact=address,
                        deleted_at__isnull=True,
                    )
                    .exclude(pk=account.pk)
                    .exists()
                )
                if duplicate:
                    return cls(success=False, error='BSC address is already registered')

                old_address = account.algorand_address
                old_bsc_address = account.bsc_address

                retired_destinations = [
                    (
                        RetiredWalletAddress.CHAIN_ALGORAND,
                        RetiredWalletAddress.normalize_address(
                            RetiredWalletAddress.CHAIN_ALGORAND,
                            old_address,
                        ),
                    ),
                ]
                if old_bsc_address and old_bsc_address.lower() != address.lower():
                    retired_destinations.append((
                        RetiredWalletAddress.CHAIN_BSC,
                        RetiredWalletAddress.normalize_address(
                            RetiredWalletAddress.CHAIN_BSC,
                            old_bsc_address,
                        ),
                    ))

                # A destination may only ever retire from the account that
                # owned it. Check every row before writing any so an unexpected
                # historical collision cannot leave a partial audit record.
                for chain, retired_address in retired_destinations:
                    if RetiredWalletAddress.objects.filter(
                        chain=chain,
                        address=retired_address,
                    ).exclude(account=account).exists():
                        return cls(success=False, error='Previous wallet address is already retired')
                for chain, retired_address in retired_destinations:
                    RetiredWalletAddress.objects.get_or_create(
                        chain=chain,
                        address=retired_address,
                        defaults={'account': account, 'user': user},
                    )

                account.algorand_address = None
                account.bsc_address = address
                account.is_keyless_migrated = True
                try:
                    account.save(update_fields=[
                        'algorand_address',
                        'bsc_address',
                        'is_keyless_migrated',
                    ])
                except IntegrityError:
                    return cls(success=False, error='BSC address is already registered')

                logger.warning(
                    "Wallet reenrollment completed account=%s user=%s retired=%s old_bsc=%s new_bsc=%s",
                    account.id,
                    user.id,
                    redact_address(old_address),
                    redact_address(old_bsc_address),
                    redact_address(address),
                )
                return cls(success=True, error=None)
        except Exception as exc:
            logger.exception("Wallet reenrollment failed for user=%s: %s", user.id, exc)
            return cls(success=False, error='Could not complete wallet reenrollment')


class MarkWalletMigratedMutation(graphene.Mutation):
    """
    Mark the user's account as successfully migrated to V2 (Native Keyless).
    This stops the app from checking for V1->V2 migration on every launch.
    """
    class Arguments:
        new_address = graphene.String(required=False)  # The new V2 address
        migrated_from_address = graphene.String(required=False)
        
    success = graphene.Boolean()
    error = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, new_address=None, migrated_from_address=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Get JWT context
            from .jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            
            # Default to personal account index 0 if no context (common during migration flows)
            account_type = 'personal'
            account_index = 0
            business_id = None
            
            if jwt_context:
                account_type = jwt_context.get('account_type', 'personal')
                account_index = jwt_context.get('account_index', 0)
                business_id = jwt_context.get('business_id')
            
            # Find the account
            from .models import Account
            account = None
            
            if account_type == 'business' and business_id:
                account = Account.objects.filter(
                    account_type='business',
                    business_id=business_id,
                    deleted_at__isnull=True
                ).order_by('account_index').first() # Use first business account if index unclear
            else:
                account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=account_index,
                    deleted_at__isnull=True
                ).first()
                
            if not account:
                return cls(success=False, error='Account not found')

            address_to_verify = migrated_from_address or account.algorand_address
            if address_to_verify:
                from blockchain.algorand_client import get_algod_client

                risk = inspect_address_migration_risk(get_algod_client(), address_to_verify)
                if risk['has_material_risk']:
                    logger.warning(
                        "Refusing to mark account %s as migrated while %s still holds value: assets=%s spendable_algo=%s",
                        account.id,
                        address_to_verify,
                        risk['relevant_assets'],
                        risk['spendable_algo'],
                    )
                    return cls(
                        success=False,
                        error=(
                            'Migration not complete: the previous wallet still holds funds or pending assets'
                        ),
                    )
            
            update_fields = ['is_keyless_migrated']
            account.is_keyless_migrated = True

            if new_address:
                # Validate format
                if len(new_address) == 58:
                    old_address = account.algorand_address
                    account.algorand_address = new_address
                    update_fields.append('algorand_address')
                    logger.info(f"Updating address for migration: {old_address} -> {new_address}")
                else:
                    logger.warning(f"Invalid new address format provided for migration: {new_address}")

            account.save(update_fields=update_fields)
            
            logger.info(f"Marked account {account.id} (User {user.id}) as migrated to V2")
            
            return cls(success=True)
            
        except Exception as e:
            logger.error(f"Error marking wallet migrated: {e}")
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
    mark_wallet_migrated = MarkWalletMigratedMutation.Field()
    prepare_wallet_reenrollment = PrepareWalletReenrollmentMutation.Field()
    complete_wallet_reenrollment = CompleteWalletReenrollmentMutation.Field()


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




class Mutation(graphene.ObjectType):
    web3auth_login = Web3AuthLoginMutation.Field()
    add_algorand_wallet = AddAlgorandWalletMutation.Field()
    update_algorand_address = UpdateAlgorandAddressMutation.Field()
    verify_algorand_ownership = VerifyAlgorandOwnershipMutation.Field()
    create_algorand_transaction = CreateAlgorandTransactionMutation.Field()
    get_kek_pepper = GetKekPepperMutation.Field()
    rotate_kek_pepper = RotateKekPepperMutation.Field()
    get_derivation_pepper = GetDerivationPepperMutation.Field()
    mark_wallet_migrated = MarkWalletMigratedMutation.Field()
    prepare_wallet_reenrollment = PrepareWalletReenrollmentMutation.Field()
    complete_wallet_reenrollment = CompleteWalletReenrollmentMutation.Field()
