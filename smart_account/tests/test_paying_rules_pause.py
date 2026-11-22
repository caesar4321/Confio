"""Send and payout rules are not made or changed from the chat (assistant_ops.PAYING_RULES_PAUSED)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from smart_account import assistant_ops as ops


class PayingRulesPauseTests(SimpleTestCase):
    def propose(self, existing=None, **args):
        with mock.patch.object(ops, 'operable_account', return_value=object()), \
                mock.patch.object(ops.chain, 'enabled', return_value=True), \
                mock.patch.object(ops, '_find_rule', return_value=existing), \
                mock.patch.object(ops, '_viewer', side_effect=AssertionError('went past the pause')):
            return ops.propose_rule(object(), **args)

    def test_creating_one_is_refused(self):
        for kind in ('send', 'payout'):
            with self.assertRaises(ops.OpsRefused) as refused:
                self.propose(said='envíale 500 en bolívares cada mes a @ana', action='create', kind=kind,
                             amount_usd=500, frequency='monthly', payee='@ana')
            self.assertEqual(refused.exception.code, 'paused')

    def test_changing_one_is_refused_whatever_kind_the_model_says(self):
        for kind in ('send', 'payout'):
            with self.assertRaises(ops.OpsRefused) as refused:
                self.propose(existing=SimpleNamespace(kind=kind, frequency='monthly'), said='cámbiala a 20',
                             action='update', kind='buy', rule_id='r', amount_usd=20)
            self.assertEqual(refused.exception.code, 'paused')

    def test_a_buy_rule_reads_dollars_only(self):
        with self.assertRaises(ops.OpsRefused) as refused:
            self.propose(said='compra 500 de bitcoin cada mes · en pesos', action='create', kind='buy',
                         amount_usd=500, frequency='monthly', asset='bitcoin')
        self.assertEqual(refused.exception.code, 'not_said')
