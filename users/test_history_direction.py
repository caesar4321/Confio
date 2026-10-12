"""Pure resolver regressions; no database or cloud credentials required."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


def load_direction():
    source = ast.parse(Path(__file__).with_name('graphql_views.py').read_text())
    function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'row_direction')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'graphql_views.py', 'exec'), namespace)
    return namespace['row_direction']


class HistoricalDirectionTests(unittest.TestCase):
    def setUp(self):
        self.direction = load_direction()
        self.viewer = NS(id=5, is_authenticated=True)

    def row(self, **overrides):
        fields = dict(transaction_type='send', _user_address='new-wallet',
                      _account_type='personal', _account_business_id=None,
                      sender_user_id=5, counterparty_user_id=139,
                      sender_business_id=None, counterparty_business_id=None,
                      get_direction_for_address=lambda address: 'unknown')
        fields.update(overrides)
        return NS(**fields)

    def test_historical_outgoing_after_wallet_change(self):
        self.assertEqual(self.direction(self.row(), self.viewer), 'sent')

    def test_historical_incoming_after_wallet_change(self):
        self.assertEqual(self.direction(self.row(sender_user_id=139, counterparty_user_id=5), self.viewer), 'received')

    def test_business_owner_is_not_personal_sender(self):
        self.assertEqual(self.direction(self.row(sender_business_id=8), self.viewer), 'unknown')

    def test_business_view_uses_business_identity(self):
        self.assertEqual(self.direction(self.row(_account_type='business', _account_business_id=8,
                                                 sender_business_id=8), self.viewer), 'sent')

    def test_existing_address_match_takes_precedence_for_self_transfer(self):
        self.assertEqual(self.direction(self.row(counterparty_user_id=5,
                                                 get_direction_for_address=lambda _: 'received'), self.viewer), 'received')

    def test_ambiguous_self_transfer_and_unrelated_viewer_stay_unknown(self):
        self.assertEqual(self.direction(self.row(counterparty_user_id=5), self.viewer), 'unknown')
        self.assertEqual(self.direction(self.row(sender_user_id=6), self.viewer), 'unknown')

    def test_no_authenticated_identity_stays_unknown(self):
        self.assertEqual(self.direction(self.row(), None), 'unknown')


if __name__ == '__main__':
    unittest.main()
