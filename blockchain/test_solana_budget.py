from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from blockchain.models import SolanaSponsoredTransaction
from blockchain.solana_mutations import (
    _reconcile_outstanding_sponsorships,
    _reserve_sponsorship_budget,
)
from users.models import Account


@override_settings(
    SOLANA_SPONSOR_ACCOUNT_DAILY_BUDGET_LAMPORTS=1_000,
    SOLANA_SPONSOR_GLOBAL_DAILY_BUDGET_LAMPORTS=10_000,
    SOLANA_SPONSOR_MIN_BALANCE_LAMPORTS=50,
)
class SolanaSponsorBudgetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="solana-budget-user",
            email="solana-budget@example.com",
            password="testpass123",
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type="personal",
            account_index=0,
        )

    @staticmethod
    def validated(marker: bytes, blockhash: str = "blockhash-1"):
        return SimpleNamespace(
            message_bytes=marker,
            transaction=SimpleNamespace(
                message=SimpleNamespace(recent_blockhash=blockhash)
            ),
        )

    def reserve(self, marker: bytes, observed_balance: int = 100, fee: int = 10):
        return _reserve_sponsorship_budget(
            account=self.account,
            user=self.user,
            fee_lamports=fee,
            observed_balance_lamports=observed_balance,
            observed_balance_slot=100,
            validated=self.validated(marker),
        )

    def test_unresolved_liability_survives_balance_observation_changes(self):
        first = self.reserve(b"first")
        first.status = "unknown"
        first.signature = "signature-1"
        first.save(update_fields=["status", "signature"])

        second = self.reserve(b"second", observed_balance=70)
        second.status = "failed"
        second.save(update_fields=["status"])

        # A later higher observation does not erase the first row's liability.
        third = self.reserve(b"third", observed_balance=100)
        self.assertEqual(third.status, "reserved")
        self.assertEqual(
            SolanaSponsoredTransaction.objects.filter(
                status__in=("reserved", "signed", "sent", "unknown")
            ).count(),
            2,
        )

    def test_reconciler_releases_only_expired_or_confirmed_liabilities(self):
        expired = self.reserve(b"expired")
        expired.status = "unknown"
        expired.signature = "signature-expired"
        expired.save(update_fields=["status", "signature"])

        confirmed = self.reserve(b"confirmed")
        confirmed.status = "sent"
        confirmed.signature = "signature-confirmed"
        confirmed.save(update_fields=["status", "signature"])

        class Rpc:
            def _rpc(self, method, params):
                if method == "getSignatureStatuses":
                    return {
                        "value": [
                            None,
                            {
                                "slot": 90,
                                "confirmationStatus": "confirmed",
                                "err": None,
                            },
                        ]
                    }
                if method == "isBlockhashValid":
                    return {"value": False}
                raise AssertionError(method)

        _reconcile_outstanding_sponsorships(Rpc())
        expired.refresh_from_db()
        confirmed.refresh_from_db()
        self.assertEqual(expired.status, "expired")
        self.assertEqual(confirmed.status, "confirmed_pending")
        self.assertEqual(confirmed.confirmation_slot, 90)

        self.reserve(b"post-confirmation-balance")
        confirmed.refresh_from_db()
        self.assertEqual(confirmed.status, "confirmed")

    def test_unsigned_crash_reservation_releases_after_blockhash_expiry(self):
        row = self.reserve(b"unsigned")

        class Rpc:
            def _rpc(self, method, params):
                if method == "isBlockhashValid":
                    return {"value": False}
                raise AssertionError(method)

        _reconcile_outstanding_sponsorships(Rpc())
        row.refresh_from_db()
        self.assertEqual(row.status, "expired")

    def test_retry_reactivates_a_released_row_before_it_can_be_signed(self):
        row = self.reserve(b"retry")
        row.status = "failed"
        row.save(update_fields=["status"])

        retried = self.reserve(b"retry")
        retried.refresh_from_db()
        self.assertEqual(retried.pk, row.pk)
        self.assertEqual(retried.status, "reserved")
