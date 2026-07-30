"""
CUSD_DEPOSITS_PAUSED must flow settings → cusdPlusSummary.cusd_deposits_paused
verbatim: this flag is the remote kill-switch for the cUSD phase-out steering
(app hides the cUSD recharge rail when True), so a silent default flip here
would re-open or close deposit rails without anyone deploying the app.

Runs without a database:
    myvenv/bin/python manage.py test cusd_plus.tests.test_deposits_paused_flag
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus.schema import Query


def _info(user):
    return SimpleNamespace(context=SimpleNamespace(user=user))


AUTHED = SimpleNamespace(is_authenticated=True)


class DepositsPausedFlagTests(SimpleTestCase):
    def _summary(self):
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True), \
             mock.patch('cusd_plus.schema._active_bsc_address', return_value=None), \
             mock.patch('cusd_plus.vault.apy_split', return_value=(3.5, 3.0)):
            return Query.resolve_cusd_plus_summary(None, _info(AUTHED))

    @override_settings(CUSD_DEPOSITS_PAUSED=True)
    def test_paused_true_reaches_summary(self):
        self.assertTrue(self._summary().cusd_deposits_paused)

    @override_settings(CUSD_DEPOSITS_PAUSED=False)
    def test_paused_false_reaches_summary(self):
        self.assertFalse(self._summary().cusd_deposits_paused)

    def test_unauthenticated_returns_none(self):
        anon = SimpleNamespace(is_authenticated=False)
        self.assertIsNone(Query.resolve_cusd_plus_summary(None, _info(anon)))
