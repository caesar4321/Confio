"""Sign-in wallet registration changes, not fund migrations.

The client recovers its canonical secret before requesting this challenge.
The server authenticates the identity and verifies control of the new address;
it does not claim to independently verify an Apple/Drive backup.
Old addresses remain audit records. No transaction or balance is moved.
"""
import hashlib
import json
import logging
import re
import secrets

import graphene
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Account, RetiredWalletAddress, User

SALT = 'confio.signin-wallet-reconciliation.v1'
MAX_AGE = 600
logger = logging.getLogger(__name__)


def challenge(payload):
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()
    return f'Confio sign-in wallet reconciliation v{payload["version"]}\n{digest}'


def owned_accounts(user, lock=False):
    query = Account.objects.select_for_update() if lock else Account.objects
    # Owner relation only: employee business access does not own wallet keys.
    return list(query.filter(user=user, deleted_at__isnull=True).order_by('pk'))


def anchors(account):
    return [account.algorand_address or '', (account.bsc_address or '').lower()]


def context(account):
    return {'account_id': str(account.pk), 'account_type': account.account_type,
            'account_index': account.account_index,
            'business_id': str(account.business_id) if account.business_id else None}


def inventory(accounts):
    return [{**context(account), 'anchors': anchors(account),
             'is_keyless_migrated': account.is_keyless_migrated} for account in accounts]


def account_results(accounts):
    return [{**context(account), 'algorand_address': account.algorand_address,
             'bsc_address': account.bsc_address,
             'is_keyless_migrated': account.is_keyless_migrated} for account in accounts]


def valid_address(value):
    address = str(value or '').strip().lower()
    if not re.fullmatch(r'0x[0-9a-f]{40}', address) or int(address[2:], 16) == 0:
        raise ValueError('Invalid wallet address')
    return address


def wallet_challenge(base_challenge, account_id, address):
    return f'{base_challenge}\nAccount: {account_id}\nAddress: {address.lower()}'


class WalletReconciliationAccount(graphene.ObjectType):
    account_id = graphene.String(required=True)
    account_type = graphene.String(required=True)
    account_index = graphene.Int(required=True)
    business_id = graphene.String()
    algorand_address = graphene.String()
    bsc_address = graphene.String()
    is_keyless_migrated = graphene.Boolean(required=True)


class WalletReconciliationProofInput(graphene.InputObjectType):
    account_id = graphene.String(required=True)
    bsc_address = graphene.String(required=True)
    signature = graphene.String(required=True)


class PrepareWalletReconciliation(graphene.Mutation):
    class Arguments:
        firebase_id_token = graphene.String(required=True)
        bsc_address = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()
    grant = graphene.String()
    challenge = graphene.String()
    accounts = graphene.List(graphene.NonNull(WalletReconciliationAccount))

    @classmethod
    def mutate(cls, root, info, firebase_id_token, bsc_address=None):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return cls(success=False, error='Authentication required')
        try:
            address = valid_address(bsc_address) if bsc_address is not None else None
        except ValueError:
            return cls(success=False, error='Invalid wallet address')
        from firebase_admin import auth
        try:
            identity = auth.verify_id_token(firebase_id_token, check_revoked=True)
            provider = identity.get('firebase', {}).get('sign_in_provider')
            age = timezone.now().timestamp() - float(identity.get('auth_time', 0))
            if (identity.get('uid') != user.firebase_uid
                    or provider not in ('google.com', 'apple.com')
                    or not -60 <= age <= MAX_AGE):
                raise ValueError('Fresh matching social identity required')
        except Exception:
            return cls(success=False, error='Sign in again to verify your identity')
        accounts = owned_accounts(user)
        account = next((item for item in accounts if item.account_type == 'personal'
                        and item.account_index == 0), None)
        if not account:
            return cls(success=False, error='Account not found')
        if address is None:
            return cls(success=True, accounts=account_results(accounts))
        payload = {
            'version': 2, 'user': user.pk, 'account': account.pk,
            'provider': provider, 'firebase_uid': user.firebase_uid,
            'inventory': inventory(accounts), 'replacement': address,
            'nonce': secrets.token_hex(32),
        }
        return cls(success=True, grant=signing.dumps(payload, salt=SALT),
                   challenge=challenge(payload), accounts=account_results(accounts))


class CompleteWalletReconciliation(graphene.Mutation):
    class Arguments:
        grant = graphene.String(required=True)
        signature = graphene.String(required=True)
        wallets = graphene.List(graphene.NonNull(WalletReconciliationProofInput))

    success = graphene.Boolean()
    error = graphene.String()
    bsc_address = graphene.String()
    accounts = graphene.List(graphene.NonNull(WalletReconciliationAccount))

    @classmethod
    def mutate(cls, root, info, grant, signature, wallets=None):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return cls(success=False, error='Authentication required')
        from eth_account import Account as EvmAccount
        from eth_account.messages import encode_defunct
        try:
            payload = signing.loads(grant, salt=SALT, max_age=MAX_AGE)
            address = valid_address(payload['replacement'])
            if (payload['version'] != 2 or payload['user'] != user.pk
                    or payload['firebase_uid'] != user.firebase_uid
                    or payload['provider'] not in ('google.com', 'apple.com')
                    or not payload['nonce']):
                raise ValueError('Wrong identity')
            base_challenge = challenge(payload)
            signer = EvmAccount.recover_message(
                encode_defunct(text=base_challenge), signature=signature)
            if signer.lower() != address:
                raise ValueError('Wrong signer')
            expected_ids = [entry['account_id'] for entry in payload['inventory']]
            primary_id = str(payload['account'])
            if not expected_ids or len(set(expected_ids)) != len(expected_ids):
                raise ValueError('Invalid inventory')
            if wallets is None:
                # Older clients cannot silently reconcile only one sibling.
                if expected_ids != [primary_id]:
                    raise ValueError('All owned wallets require proofs')
                targets = {primary_id: address}
            else:
                targets = {}
                for proof in wallets:
                    account_id = proof['account_id']
                    target = valid_address(proof['bsc_address'])
                    if account_id in targets or account_id not in expected_ids:
                        raise ValueError('Duplicate or unowned account')
                    signer = EvmAccount.recover_message(encode_defunct(text=wallet_challenge(
                        base_challenge, account_id, target)), signature=proof['signature'])
                    if signer.lower() != target:
                        raise ValueError('Wrong account signer')
                    targets[account_id] = target
                if set(targets) != set(expected_ids) or targets.get(primary_id) != address:
                    raise ValueError('Incomplete or mismatched wallet proofs')
            if len(set(targets.values())) != len(targets):
                raise ValueError('Duplicate wallet targets')
        except Exception:
            return cls(success=False, error='Invalid or expired wallet proof')

        try:
            with transaction.atomic():
                owner = User.objects.select_for_update().get(pk=user.pk)
                if not owner.is_active or owner.firebase_uid != payload['firebase_uid']:
                    return cls(success=False, error='Authentication required')
                accounts = owned_accounts(owner, lock=True)
                current_inventory = inventory(accounts)
                if ([context(item) for item in accounts] != [
                    {key: value for key, value in item.items()
                     if key not in ('anchors', 'is_keyless_migrated')}
                    for item in payload['inventory']
                ]):
                    return cls(success=False, error='Accounts changed; sign in again')
                account = next((item for item in accounts if item.pk == payload['account']), None)
                if not account:
                    return cls(success=False, error='Account not found')
                # A retry after a lost response still verifies identity and signature.
                if all(not item.algorand_address and item.is_keyless_migrated
                       and (item.bsc_address or '').lower() == targets[str(item.pk)]
                       for item in accounts):
                    return cls(success=True, bsc_address=account.bsc_address,
                               accounts=account_results(accounts))
                if current_inventory != payload['inventory']:
                    return cls(success=False, error='Wallet changed; sign in again')
                # Include historical owners: retiring an address never frees it
                # for another account to claim (even a sibling of this owner).
                for item in accounts:
                    target = targets[str(item.pk)]
                    if Account.all_objects.filter(bsc_address__iexact=target).exclude(pk=item.pk).exists():
                        return cls(success=False, error='Wallet belongs to another account')
                    if RetiredWalletAddress.objects.filter(
                        chain='bsc', address=target,
                    ).exclude(account=item).exists():
                        return cls(success=False, error='Wallet belongs to another account')
                for item in accounts:
                    target = targets[str(item.pk)]
                    old_algo, old_bsc = anchors(item)
                    for chain, old in [('algorand', old_algo), ('bsc', old_bsc)]:
                        if not old or (chain == 'bsc' and old == target):
                            continue
                        retired, _ = RetiredWalletAddress.objects.get_or_create(
                            chain=chain,
                            address=RetiredWalletAddress.normalize_address(chain, old),
                            defaults={'account': item, 'user': owner},
                        )
                        if retired.account_id != item.pk:
                            raise IntegrityError('Historical address ownership conflict')
                    item.algorand_address = None
                    item.bsc_address = target
                    item.is_keyless_migrated = True
                    item.save(update_fields=['algorand_address', 'bsc_address',
                                             'is_keyless_migrated'])
                # Neither pending transactions nor recorded amounts are rewritten.
                # Drop the monitor's cached active-address map after commit.
                from django.core.cache import cache
                transaction.on_commit(lambda: cache.delete('cusd_plus_bsc_registered_v1'), robust=True)
            logger.info('Wallet reconciliation completed accounts=%s user=%s provider=%s',
                        len(accounts), user.pk, payload['provider'])
            return cls(success=True, bsc_address=address, accounts=account_results(accounts))
        except IntegrityError:
            return cls(success=False, error='Wallet address conflict; sign in again')
        except Exception:
            # Never log grants, signatures, Firebase tokens or key material.
            logger.error('Wallet reconciliation failed user=%s', user.pk)
            return cls(success=False, error='Could not reconcile wallet; sign in again')
