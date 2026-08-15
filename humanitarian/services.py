import logging
from decimal import Decimal

from algosdk import abi, encoding as algo_encoding, transaction
from algosdk.logic import get_application_address
from algosdk.transaction import wait_for_confirmation
from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from blockchain.algorand_client import get_algod_client, get_indexer_client
from blockchain.kms_manager import get_kms_signer_from_settings
from users.models import Account, RetiredWalletAddress

from .models import HumanitarianCampaign, HumanitarianDonation, HumanitarianRelease


logger = logging.getLogger(__name__)


def cusd_to_base_units(amount: Decimal) -> int:
    return int((Decimal(amount) * Decimal('1000000')).to_integral_value())


class HumanitarianReleaseService:
    RELEASE_SIGNATURE = 'release(address,uint64,string)void'

    def __init__(self):
        self.algod = get_algod_client()
        self.signer = get_kms_signer_from_settings(role='admin')

    def _validate_recipient_wallet(self, release: HumanitarianRelease) -> None:
        """Serialize linked-user payouts with wallet reenrollment.

        The release row remains a reenrollment blocker while it is draft,
        failed, or submitted, so after this short Account lock is released the
        destructive mutation still cannot retire the checked address.
        """
        linked_user = None
        if release.kind == 'reimbursement' and release.donation_id:
            linked_user = release.donation.donor_user
        elif release.volunteer_application_id:
            linked_user = release.volunteer_application.user

        with db_transaction.atomic():
            if linked_user is not None:
                account = Account.objects.select_for_update().filter(
                    user=linked_user,
                    account_type='personal',
                    account_index=0,
                    deleted_at__isnull=True,
                ).first()
                current_address = getattr(account, 'algorand_address', None) or ''
                if current_address != release.recipient_address:
                    raise ValueError(
                        'Release recipient wallet changed; update the release before submitting'
                    )

            if RetiredWalletAddress.is_retired(
                RetiredWalletAddress.CHAIN_ALGORAND,
                release.recipient_address,
            ):
                raise ValueError('Release recipient wallet has been retired')

    def _claim_submission(
        self,
        release: HumanitarianRelease,
        txid: str,
        signed_transaction_b64: str,
        first_valid_round: int,
        last_valid_round: int,
        admin_user=None,
    ) -> HumanitarianRelease:
        """Durably claim the one allowed broadcast for this release.

        The claim commits before the network call. If the response is lost the
        row deliberately remains submitted with the deterministic Algorand
        txid; a retry must reconcile that txid, never create a second payment.
        """
        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update(of=('self',)).select_related(
                'donation__donor_user',
                'volunteer_application__user',
            ).get(pk=release.pk)
            if locked.status not in ('draft', 'failed'):
                raise ValueError('Only draft or failed releases can be submitted')
            if (
                locked.public_id != release.public_id
                or locked.campaign_id != release.campaign_id
                or locked.kind != release.kind
                or locked.amount != Decimal(str(release.amount))
                or locked.recipient_address != release.recipient_address
            ):
                raise ValueError('Release changed while preparing; retry submission')

            # Nested atomic reuses this transaction. Reenrollment never locks
            # a release row; it only reads it while holding Account, so this
            # release-then-Account lock sequence cannot form a lock cycle.
            self._validate_recipient_wallet(locked)
            locked.status = 'submitted'
            locked.transaction_hash = txid
            locked.signed_transaction_b64 = signed_transaction_b64
            locked.submitted_first_valid_round = int(first_valid_round)
            locked.submitted_last_valid_round = int(last_valid_round)
            if admin_user is not None:
                locked.released_by = admin_user
            locked.save(update_fields=[
                'status',
                'transaction_hash',
                'signed_transaction_b64',
                'submitted_first_valid_round',
                'submitted_last_valid_round',
                'released_by',
                'updated_at',
            ])
            return locked

    def _mark_confirmed(self, release_id: int, txid: str, admin_user=None) -> HumanitarianRelease:
        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update().get(pk=release_id)
            if locked.status == 'confirmed' and locked.transaction_hash == txid:
                return locked
            if locked.status != 'submitted' or locked.transaction_hash != txid:
                raise RuntimeError('Humanitarian release submission state changed unexpectedly')
            locked.status = 'confirmed'
            if admin_user is not None:
                locked.released_by = admin_user
            locked.released_at = timezone.now()
            locked.save(update_fields=[
                'status',
                'released_by',
                'released_at',
                'updated_at',
            ])
            if locked.kind != 'reimbursement':
                # The row lock makes this campaign increment exactly once even
                # when the request and the reconciler observe confirmation
                # concurrently.
                HumanitarianCampaign.objects.filter(pk=locked.campaign_id).update(
                    total_released=F('total_released') + locked.amount,
                    release_count=F('release_count') + 1,
                    updated_at=timezone.now(),
                )
            return locked

    def reconcile_submission(self, release: HumanitarianRelease) -> str:
        """Converge one claimed release without ever signing a second txn."""
        release = HumanitarianRelease.objects.get(pk=release.pk)
        if release.status != 'submitted':
            return release.status
        txid = (release.transaction_hash or '').strip()
        signed_b64 = (release.signed_transaction_b64 or '').strip()
        last_valid = int(release.submitted_last_valid_round or 0)
        if not txid or not signed_b64 or last_valid <= 0:
            # Legacy/partial submitted rows cannot be proven safe to retry.
            logger.error('Humanitarian release %s has incomplete recovery data', release.pk)
            return 'incomplete'

        indexer = get_indexer_client()
        indexed = indexer.search_transactions(txid=txid, limit=1)
        indexed_round = int(indexed.get('current-round') or 0)
        indexed_transactions = indexed.get('transactions') or []
        if indexed_transactions and not any(
            str(item.get('id') or item.get('txid') or '') == txid
            for item in indexed_transactions
            if isinstance(item, dict)
        ):
            raise RuntimeError('Indexer returned a mismatched humanitarian release transaction')
        if indexed_transactions:
            self._mark_confirmed(release.pk, txid)
            return 'confirmed'

        pending = {}
        try:
            pending = self.algod.pending_transaction_info(txid) or {}
        except Exception:
            # An absent pending entry is expected before the first rebroadcast
            # and after expiry. Indexer catch-up below is the authoritative
            # absence proof before a new signature is ever allowed.
            pending = {}
        if int(pending.get('confirmed-round') or 0) > 0:
            self._mark_confirmed(release.pk, txid)
            return 'confirmed'

        algod_round = int((self.algod.status() or {}).get('last-round') or 0)
        if algod_round <= last_valid:
            try:
                returned_txid = self.algod.send_raw_transaction(signed_b64)
                if returned_txid and returned_txid != txid:
                    raise RuntimeError('Algorand returned an unexpected humanitarian release txid')
            except Exception as exc:
                message = str(exc).lower()
                if 'already in pool' not in message and 'already in ledger' not in message:
                    logger.warning(
                        'Humanitarian identical rebroadcast pending release=%s txid=%s: %s',
                        release.pk,
                        txid,
                        exc,
                    )
            return 'submitted'

        # Only a caught-up authoritative indexer can prove that an expired
        # deterministic txid never landed. Until then the release stays
        # submitted and remains a wallet-reenrollment blocker.
        if indexed_round <= last_valid:
            return 'submitted'
        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update().get(pk=release.pk)
            if (
                locked.status == 'submitted'
                and locked.transaction_hash == txid
                and locked.submitted_last_valid_round == last_valid
            ):
                locked.status = 'failed'
                locked.save(update_fields=['status', 'updated_at'])
                return 'failed'
            return locked.status

    def submit_release(self, release: HumanitarianRelease, admin_user=None) -> str:
        if release.status not in ('draft', 'failed'):
            raise ValueError('Only draft or failed releases can be submitted')
        if release.kind == 'reimbursement':
            if not release.donation or release.donation.status != 'confirmed':
                raise ValueError('Reimbursements require a confirmed donation')
            if release.recipient_address != release.donation.from_address:
                raise ValueError('Reimbursement recipient must match the donation source address')
        else:
            if not release.volunteer_application or release.volunteer_application.status != 'approved':
                raise ValueError('Volunteer application must be approved before release')

        app_id = int(
            release.campaign.algorand_app_id
            or getattr(settings, 'ALGORAND_HUMANITARIAN_APP_ID', 0)
            or 0
        )
        if app_id <= 0:
            raise ValueError('ALGORAND_HUMANITARIAN_APP_ID is not configured')

        amount_base = cusd_to_base_units(release.amount)
        cusd_asset_id = int(settings.ALGORAND_CUSD_ASSET_ID)
        app_address = get_application_address(app_id)
        vault_cusd_balance = 0
        for asset in self.algod.account_info(app_address).get('assets') or []:
            if int(asset.get('asset-id') or 0) == cusd_asset_id:
                vault_cusd_balance = int(asset.get('amount') or 0)
                break
        if vault_cusd_balance < amount_base:
            raise ValueError('Humanitarian account has insufficient cUSD for this release')

        params = self.algod.suggested_params()
        params.flat_fee = True
        params.fee = (getattr(params, 'min_fee', 1000) or 1000) * 2
        method = abi.Method.from_signature(self.RELEASE_SIGNATURE)
        app_args = [
            method.get_selector(),
            abi.AddressType().encode(release.recipient_address),
            abi.UintType(64).encode(amount_base),
            abi.StringType().encode(release.public_id),
        ]
        app_call = transaction.ApplicationNoOpTxn(
            sender=self.signer.address,
            sp=params,
            index=app_id,
            app_args=app_args,
            accounts=[release.recipient_address],
            foreign_assets=[cusd_asset_id],
        )
        signed = self.signer.sign_transaction(app_call)
        expected_txid = app_call.get_txid()
        # Encode before the durable claim: after commit every possible retry
        # has the exact same signed bytes and can never create a second payment.
        signed_transaction_b64 = algo_encoding.msgpack_encode(signed)
        release = self._claim_submission(
            release,
            expected_txid,
            signed_transaction_b64,
            app_call.first_valid_round,
            app_call.last_valid_round,
            admin_user=admin_user,
        )
        txid = self.algod.send_raw_transaction(signed_transaction_b64)
        if txid != expected_txid:
            raise RuntimeError('Algorand returned an unexpected humanitarian release txid')
        wait_for_confirmation(self.algod, txid, 6)

        self._mark_confirmed(release.pk, txid, admin_user=admin_user)
        return txid

    def reimburse_donation(self, donation: HumanitarianDonation, admin_user=None) -> str:
        if donation.status != 'confirmed':
            raise ValueError('Only confirmed donations can be reimbursed')
        if not donation.from_address:
            raise ValueError('Donation has no source address to reimburse')

        with db_transaction.atomic():
            release, created = HumanitarianRelease.objects.select_for_update().get_or_create(
                donation=donation,
                defaults={
                    'campaign': donation.campaign,
                    'kind': 'reimbursement',
                    'amount': donation.amount,
                    'purpose': f'Reembolso de donación: {donation.campaign.title}',
                    'recipient_address': donation.from_address,
                },
            )
        if not created and release.status not in ('draft', 'failed'):
            raise ValueError(f'Donation {donation.public_id} already reimbursed ({release.status})')
        return self.submit_release(release, admin_user=admin_user)
