from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from conversion.models import Conversion
from cusd_plus.prepare_leg_ab import _create_conversion_for_current_addresses
from users.models import Account


User = get_user_model()


class LegABPersistenceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='leg-ab-owner',
            firebase_uid='leg-ab-owner-uid',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='A' * 58,
            bsc_address='0x' + '1' * 40,
        )

    def _create(self):
        return _create_conversion_for_current_addresses(
            account_id=self.account.id,
            expected_algorand_address='A' * 58,
            expected_bsc_address='0x' + '1' * 40,
            amount=Decimal('12.5'),
            receive_usd=Decimal('12.3456789'),
        )

    def test_creates_conversion_for_locked_current_snapshot(self):
        conversion = self._create()

        self.assertIsNotNone(conversion)
        self.assertEqual(conversion.actor_user, self.user)
        self.assertEqual(conversion.actor_address, 'A' * 58)
        self.assertEqual(conversion.user_bsc_address, '0x' + '1' * 40)
        self.assertEqual(conversion.to_amount, Decimal('12.345679'))

    def test_rejects_pack_when_address_changed_before_persistence(self):
        self.account.bsc_address = '0x' + '2' * 40
        self.account.save(update_fields=['bsc_address'])

        self.assertIsNone(self._create())
        self.assertFalse(Conversion.objects.exists())
