from decimal import Decimal

from algosdk import abi, transaction
from algosdk.logic import get_application_address
from algosdk.transaction import wait_for_confirmation
from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from blockchain.algorand_client import get_algod_client
from blockchain.kms_manager import get_kms_signer_from_settings

from .models import HumanitarianCampaign, HumanitarianRelease


def cusd_to_base_units(amount: Decimal) -> int:
    return int((Decimal(amount) * Decimal('1000000')).to_integral_value())


class HumanitarianReleaseService:
    RELEASE_SIGNATURE = 'release(address,uint64,string)void'

    def __init__(self):
        self.algod = get_algod_client()
        self.signer = get_kms_signer_from_settings(role='admin')

    def submit_release(self, release: HumanitarianRelease, admin_user=None) -> str:
        if release.status not in ('draft', 'failed'):
            raise ValueError('Only draft or failed releases can be submitted')
        if release.volunteer_application.status != 'approved':
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
        txid = self.algod.send_raw_transaction(signed)
        wait_for_confirmation(self.algod, txid, 6)

        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update().get(pk=release.pk)
            locked.status = 'confirmed'
            locked.transaction_hash = txid
            locked.released_by = admin_user
            locked.released_at = timezone.now()
            locked.save(update_fields=[
                'status',
                'transaction_hash',
                'released_by',
                'released_at',
                'updated_at',
            ])
            HumanitarianCampaign.objects.filter(pk=locked.campaign_id).update(
                total_released=F('total_released') + locked.amount,
                release_count=F('release_count') + 1,
                updated_at=timezone.now(),
            )
        return txid
