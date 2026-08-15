from django.test import TestCase

from humanitarian.models import (
    HumanitarianCampaign,
    HumanitarianRelease,
    HumanitarianVolunteerApplication,
)
from humanitarian.services import HumanitarianReleaseService
from users.models import Account, RetiredWalletAddress, User


class HumanitarianReleaseWalletSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='humanitarian-recipient',
            email='humanitarian-recipient@example.com',
            firebase_uid='humanitarian-recipient-firebase',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='A' * 58,
        )
        self.campaign = HumanitarianCampaign.objects.create(
            slug='wallet-safety',
            title='Wallet safety',
        )
        self.application = HumanitarianVolunteerApplication.objects.create(
            user=self.user,
            campaign=self.campaign,
            status='approved',
        )

    def _release(self, address):
        return HumanitarianRelease.objects.create(
            campaign=self.campaign,
            volunteer_application=self.application,
            amount='10.00',
            purpose='Test aid',
            recipient_address=address,
        )

    def test_linked_release_refuses_address_that_no_longer_matches_account(self):
        release = self._release('B' * 58)
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)

        with self.assertRaisesRegex(ValueError, 'wallet changed'):
            service._validate_recipient_wallet(release)

    def test_release_refuses_tombstoned_destination(self):
        release = self._release(self.account.algorand_address)
        RetiredWalletAddress.objects.create(
            chain=RetiredWalletAddress.CHAIN_ALGORAND,
            address=self.account.algorand_address,
            account=self.account,
            user=self.user,
        )
        service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)

        with self.assertRaisesRegex(ValueError, 'has been retired'):
            service._validate_recipient_wallet(release)
