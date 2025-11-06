from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from achievements.models import (
    AchievementType,
    UserAchievement,
    ConfioRewardBalance,
    ConfioRewardTransaction,
)
from blockchain.mutations import AlgorandSponsoredSendMutation
from blockchain.algorand_account_manager import AlgorandAccountManager
from users.models import User, Account


class FakeAlgodClient:
    """Minimal stub for Algod client interactions used in tests."""

    def __init__(self, token=None, address=None):
        self.token = token
        self.address = address

    def account_info(self, address):
        # Provide sufficient CONFIO balance (in base units) so balance checks pass.
        return {
            'assets': [
                {
                    'asset-id': AlgorandAccountManager.CONFIO_ASSET_ID,
                    'amount': 2_000_000_000,  # 2000 CONFIO assuming 6 decimals
                }
            ],
            'amount': 5_000_000,
            'min-balance': 1_000_000,
        }

    def asset_info(self, asset_id):
        return {'params': {'decimals': 6}}


async def fake_create_sponsored_transfer(*args, **kwargs):
    """Async stub that mimics a successful sponsored transfer response."""
    return {
        'success': True,
        'user_transaction': 'fake-user-txn',
        'sponsor_transaction': 'fake-sponsor-txn',
        'group_id': 'fake-group',
        'total_fee': 1000,
    }


@override_settings(
    ALGORAND_CONFIO_ASSET_ID=123456,
    ALGORAND_ALGOD_ADDRESS='http://fake-node',
    ALGORAND_ALGOD_TOKEN='fake-token',
)
class ReferralWithdrawalLimitTest(TestCase):
    """Tests around referral withdrawal restrictions for sponsored sends."""

    def setUp(self):
        # Ensure AlgorandAccountManager picks up the overridden settings.
        AlgorandAccountManager.CONFIO_ASSET_ID = 123456
        AlgorandAccountManager.ALGOD_ADDRESS = 'http://fake-node'
        AlgorandAccountManager.ALGOD_TOKEN = 'fake-token'

        self.user = User.objects.create_user(
            username='referrer',
            email='referrer@example.com',
            password='password123',
            firebase_uid='uid-referrer',
        )
        # Provide minimal phone context (kept blank so phone verification check only
        # triggers once earned >= 100).
        self.user.phone_number = ''
        self.user.save()

        # Create sender Algorand account record.
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='A' * 58,
        )

        # Ensure referral achievement exists.
        achievement_type, _ = AchievementType.objects.get_or_create(
            slug='successful_referral',
            defaults={
                'name': 'Referral Conversion',
                'description': 'Referred user completed first transaction',
                'category': 'ambassador',
                'icon_emoji': '🎯',
                'color': '#2563EB',
                'confio_reward': Decimal('20'),
            },
        )

        self.referral_achievement = UserAchievement.objects.create(
            user=self.user,
            achievement_type=achievement_type,
            status='earned',
        )

        # Seed reward balance and ledger so referral portion calculation has funds.
        self.balance = ConfioRewardBalance.objects.create(
            user=self.user,
            total_earned=Decimal('20'),
            total_locked=Decimal('20'),
            total_unlocked=Decimal('20'),
            total_spent=Decimal('0'),
        )

        ConfioRewardTransaction.objects.create(
            user=self.user,
            transaction_type='earned',
            amount=Decimal('20'),
            balance_after=self.balance.total_locked,
            reference_type='achievement',
            reference_id=str(self.referral_achievement.id),
            description='Referral reward',
        )

        # Dummy GraphQL info/context objects.
        self.context = SimpleNamespace(user=self.user, META={})
        self.info = SimpleNamespace(context=self.context)

        # Silence notification side effects during tests.
        self.notification_patcher = patch('notifications.utils.create_notification', return_value=None)
        self.notification_patcher.start()

    def tearDown(self):
        self.notification_patcher.stop()

    def _grant_referral_earnings(self, amount: Decimal):
        """Utility to add referral-earned CONFIO and update ledger/balance."""
        self.balance.total_earned += amount
        self.balance.total_locked += amount
        self.balance.total_unlocked += amount
        self.balance.save(update_fields=['total_earned', 'total_locked', 'total_unlocked'])

        ConfioRewardTransaction.objects.create(
            user=self.user,
            transaction_type='earned',
            amount=amount,
            balance_after=self.balance.total_locked,
            reference_type='achievement',
            reference_id=str(self.referral_achievement.id),
            description='Referral reward (test grant)',
        )

    def test_daily_limit_blocks_unverified_identity(self):
        """Unverified users exceeding the daily referral withdrawal limit should be blocked."""

        ctx_patch, algod_patch, sponsor_patch = self._patch_context()
        with ctx_patch, algod_patch, sponsor_patch:
            result = AlgorandSponsoredSendMutation.mutate(
                root=None,
                info=self.info,
                recipient_address='B' * 58,
                amount=15,
                asset_type='CONFIO',
            )

        self.assertFalse(result.success)
        self.assertIn('solo pueden retirar 10 CONFIO', result.error)

    def _patch_context(self):
        """Helper to patch JWT context, Algod client, and sponsor service."""
        return (
            patch(
                'users.jwt_context.get_jwt_business_context_with_validation',
                return_value={
                    'user_id': self.user.id,
                    'account_type': 'personal',
                    'account_index': 0,
                    'business_id': None,
                },
            ),
            patch(
                'algosdk.v2client.algod.AlgodClient',
                side_effect=lambda token, addr: FakeAlgodClient(token, addr),
            ),
            patch(
                'blockchain.mutations.algorand_sponsor_service.create_sponsored_transfer',
                side_effect=fake_create_sponsored_transfer,
            ),
        )

    def test_high_value_requires_identity_verification(self):
        """High-value referral withdrawals require KYC when identity is not verified."""

        self.user.phone_number = '1234567890'
        self.user.save(update_fields=['phone_number'])

        # Add 780 CONFIO to reach 800 total earned.
        self._grant_referral_earnings(Decimal('780'))

        ctx_patch, algod_patch, sponsor_patch = self._patch_context()
        with ctx_patch, algod_patch, sponsor_patch, patch(
            'blockchain.mutations.REFERRAL_DAILY_LIMIT', Decimal('1000')
        ), patch(
            'blockchain.mutations.REFERRAL_WEEKLY_LIMIT', Decimal('5000')
        ):
            result = AlgorandSponsoredSendMutation.mutate(
                root=None,
                info=self.info,
                recipient_address='B' * 58,
                amount=600,
                asset_type='CONFIO',
            )

        self.assertFalse(result.success)
        self.assertIn('verificación de identidad', result.error)

    def test_earned_threshold_requires_identity(self):
        """Lifetime referral earnings over threshold require identity verification."""

        self.user.phone_number = '987654321'
        self.user.save(update_fields=['phone_number'])

        # Add 130 CONFIO to push lifetime earnings over 100 threshold.
        self._grant_referral_earnings(Decimal('130'))

        ctx_patch, algod_patch, sponsor_patch = self._patch_context()
        with ctx_patch, algod_patch, sponsor_patch:
            result = AlgorandSponsoredSendMutation.mutate(
                root=None,
                info=self.info,
                recipient_address='B' * 58,
                amount=5,
                asset_type='CONFIO',
            )

        self.assertFalse(result.success)
        self.assertIn('verificación de identidad', result.error)
