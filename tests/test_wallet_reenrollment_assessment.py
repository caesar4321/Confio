"""Offline regressions: python -m unittest tests.test_wallet_reenrollment_assessment."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase

from users.wallet_reenrollment_assessment import wallet_reenrollment_assessment


class WalletAssessmentCompatibilityTests(TestCase):
    def setUp(self):
        self.account = SimpleNamespace(
            algorand_address='registered-algo', bsc_address=None,
            wallet_reenrollment_assessment={
                'version': 1, 'status': 'eligible', 'eligible': True,
                'reason': 'sponsor_only_empty_wallet',
                'old_algorand_address': 'registered-algo', 'old_bsc_address': '',
                'snapshot_round': 12345, 'sponsor_funding': 300000,
            },
        )

    def test_old_sponsor_only_proof_survives_deployment_without_mutation(self):
        before = deepcopy(self.account.wallet_reenrollment_assessment)
        self.assertIs(wallet_reenrollment_assessment(self.account),
                      self.account.wallet_reenrollment_assessment)
        self.assertEqual(self.account.wallet_reenrollment_assessment, before)

    def test_old_refusals_and_retries_require_reassessment(self):
        for status in ('ineligible', 'retry', 'unknown', None):
            with self.subTest(status=status):
                self.account.wallet_reenrollment_assessment['status'] = status
                self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_old_proof_requires_explicit_eligible_and_known_reason(self):
        for field, value in [('eligible', False), ('eligible', None),
                             ('reason', 'never_funded_wallet'), ('reason', 'unknown')]:
            with self.subTest(field=field, value=value):
                self.setUp()
                self.account.wallet_reenrollment_assessment[field] = value
                self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_unknown_versions_fail_closed(self):
        for version in (None, 0, 3, '1', '2'):
            with self.subTest(version=version):
                self.account.wallet_reenrollment_assessment['version'] = version
                self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_old_and_current_proofs_remain_anchor_bound(self):
        for version in (1, 2):
            for field, value in [('algorand_address', 'different'),
                                 ('algorand_address', None), ('bsc_address', 'new-bsc')]:
                with self.subTest(version=version, field=field):
                    self.setUp()
                    self.account.wallet_reenrollment_assessment['version'] = version
                    setattr(self.account, field, value)
                    self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_bsc_anchor_comparison_is_case_insensitive(self):
        self.account.bsc_address = '0xABC'
        self.account.wallet_reenrollment_assessment['old_bsc_address'] = '0xabc'
        self.assertIsNotNone(wallet_reenrollment_assessment(self.account))

    def test_positive_proofs_require_valid_round_and_funding(self):
        for version in (1, 2):
            for field in ('snapshot_round', 'sponsor_funding'):
                for value in (None, 0, -1, 'bad', [], float('inf')):
                    with self.subTest(version=version, field=field, value=value):
                        self.setUp()
                        self.account.wallet_reenrollment_assessment.update({
                            'version': version, field: value,
                        })
                        self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_current_sponsor_and_never_funded_proofs_are_supported(self):
        self.account.wallet_reenrollment_assessment['version'] = 2
        self.assertIsNotNone(wallet_reenrollment_assessment(self.account))
        self.account.wallet_reenrollment_assessment.update(
            reason='never_funded_wallet', sponsor_funding=0,
        )
        self.assertIsNotNone(wallet_reenrollment_assessment(self.account))

    def test_current_terminal_refusal_still_prevents_repeated_scans(self):
        self.account.wallet_reenrollment_assessment.update(
            version=2, status='ineligible', eligible=False, reason='asset_balance',
        )
        self.assertIsNotNone(wallet_reenrollment_assessment(self.account))

    def test_malformed_assessments_fail_closed(self):
        for value in (None, [], 'bad', 1, {}):
            with self.subTest(value=value):
                self.account.wallet_reenrollment_assessment = value
                self.assertIsNone(wallet_reenrollment_assessment(self.account))

    def test_malformed_bsc_anchor_fails_closed(self):
        self.account.wallet_reenrollment_assessment['old_bsc_address'] = 123
        self.assertIsNone(wallet_reenrollment_assessment(self.account))
