from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from django.test import SimpleTestCase, override_settings

from blockchain.solana_mutations import SponsorSolanaTransaction
from blockchain.solana_sponsor_service import SolanaSponsorPolicyError


class _Info:
    context = SimpleNamespace(user=SimpleNamespace(id=7, is_authenticated=True))


@override_settings(
    SOLANA_SPONSOR_ENABLED=True,
    SOLANA_SPONSOR_REQUIRE_SHARED_CACHE=False,
)
class SponsorSolanaTransactionMutationTests(SimpleTestCase):
    @patch("blockchain.solana_mutations._reconcile_outstanding_sponsorships")
    @patch("blockchain.solana_mutations.cache.add", return_value=True)
    @patch("blockchain.solana_mutations._rate_limited", return_value=False)
    @patch("blockchain.solana_mutations._active_solana_account")
    @patch("blockchain.solana_mutations.SolanaSponsorService")
    def test_relays_an_ordinary_transaction_generically(
        self, service_cls, active_account, rate_limited, cache_add, reconcile
    ):
        active_account.return_value = (
            SimpleNamespace(id=9, solana_address="user-address"),
            None,
        )
        service_cls.return_value.sponsor_and_send.return_value = {
            "signature": "chain-signature",
            "feeLamports": 5_000,
        }

        result = SponsorSolanaTransaction.mutate(
            None, _Info(), transaction="base64-wire"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.signature, "chain-signature")
        service_cls.return_value.sponsor_and_send.assert_called_once_with(
            "base64-wire",
            expected_user_signer="user-address",
            fee_authorizer=ANY,
            transaction_lookup=ANY,
            signature_recorder=ANY,
        )

    @patch("blockchain.solana_mutations._reconcile_outstanding_sponsorships")
    @patch("blockchain.solana_mutations.cache.add", return_value=True)
    @patch("blockchain.solana_mutations._rate_limited", return_value=False)
    @patch("blockchain.solana_mutations._active_solana_account")
    @patch("blockchain.solana_mutations.SolanaSponsorService")
    @patch("blockchain.solana_policies.sponsor_reference_policy")
    def test_sponsor_aware_transaction_uses_registry_policy(
        self, policy_factory, service_cls, active_account, rate_limited, cache_add, reconcile
    ):
        active_account.return_value = (
            SimpleNamespace(id=9, solana_address="user-address"),
            None,
        )
        policy = Mock()
        policy_factory.return_value = policy
        service_cls.return_value.sponsor_and_send.side_effect = [
            SolanaSponsorPolicyError("sponsor_account_referenced"),
            {"signature": "chain-signature", "feeLamports": 5_000},
        ]

        result = SponsorSolanaTransaction.mutate(
            None, _Info(), transaction="base64-wire"
        )

        self.assertTrue(result.success)
        service_cls.return_value.sponsor_and_send.assert_called_with(
            "base64-wire",
            expected_user_signer="user-address",
            policy_hook=policy,
            allow_sponsor_account_reference=True,
            fee_authorizer=ANY,
            transaction_lookup=ANY,
            signature_recorder=ANY,
        )
