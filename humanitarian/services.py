from decimal import Decimal

from algosdk import abi, transaction
from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from blockchain.algorand_client import get_algod_client
from blockchain.kms_manager import get_kms_signer_from_settings

from .models import HumanitarianRelease


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

        params = self.algod.suggested_params()
        amount_base = cusd_to_base_units(release.amount)
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
            foreign_assets=[int(settings.ALGORAND_CUSD_ASSET_ID)],
        )
        signed = self.signer.sign_transaction(app_call)
        txid = self.algod.send_raw_transaction(signed)

        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update().get(pk=release.pk)
            locked.status = 'submitted'
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
        return txid
