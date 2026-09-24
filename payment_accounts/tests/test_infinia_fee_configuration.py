from django.test import SimpleTestCase, override_settings
from payment_accounts.checks import infinia_fee_configuration_checks


class FeeConfigurationTests(SimpleTestCase):
    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='CO,BR,MX,AR', INFINIA_PROCESSING_FEE_TIER=0, INFINIA_ACCOUNT_FEE_TIER=0)
    def test_supported_rollout(self):
        self.assertEqual(infinia_fee_configuration_checks(None), [])

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='ZZ', INFINIA_PROCESSING_FEE_TIER=6, INFINIA_ACCOUNT_FEE_TIER=-1)
    def test_unknown_country_and_tiers_block_configuration(self):
        self.assertEqual({e.id for e in infinia_fee_configuration_checks(None)},
                         {'payment_accounts.E012','payment_accounts.E013','payment_accounts.E014'})
