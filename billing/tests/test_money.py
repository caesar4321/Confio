from django.test import SimpleTestCase

from billing.money import fee_units, minimal_gross_for_receiver_net, receiver_net_units


class MoneyEquationTests(SimpleTestCase):
    def test_contract_fee_vectors(self):
        self.assertEqual(fee_units(0), 0)
        self.assertEqual(fee_units(1), 1)
        self.assertEqual(fee_units(10_000), 90)
        self.assertEqual(fee_units(10_001), 91)
        self.assertEqual(receiver_net_units(10_000), 9_910)

    def test_receiver_net_gross_up_is_minimal(self):
        for target in range(1, 25_000):
            gross = minimal_gross_for_receiver_net(target)
            self.assertGreaterEqual(receiver_net_units(gross), target)
            self.assertLess(receiver_net_units(gross - 1), target)

    def test_negative_units_are_rejected(self):
        with self.assertRaises(ValueError):
            fee_units(-1)
        with self.assertRaises(ValueError):
            minimal_gross_for_receiver_net(-1)
