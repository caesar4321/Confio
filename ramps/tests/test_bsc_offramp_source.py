from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from ramps.schema import CreateRampOrder


class BscOfframpSourceTests(SimpleTestCase):
    def _create_onramp(self, *, meta):
        user = SimpleNamespace(is_authenticated=True, id=8, phone_country='BR')
        account = SimpleNamespace(
            bsc_address='0x' + ('2' * 40),
            account_type='personal',
        )
        info = SimpleNamespace(context=SimpleNamespace(user=user, META=meta))
        client = mock.Mock(is_configured=True)
        with mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
             mock.patch('ramps.schema._resolve_ramp_country_code', return_value='BR'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=account), \
             mock.patch('ramps.schema.KoyweClient', return_value=client):
            result = CreateRampOrder().mutate(
                info,
                direction='ON_RAMP',
                amount='100',
                payment_method_code='PIX',
                country_code='BR',
                fiat_currency='BRL',
                destination='cusd_plus',
            )
        return result, client

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_legacy_ineligible_bsc_onramp_requires_update(self):
        result, client = self._create_onramp(meta={'HTTP_CF_IPCOUNTRY': 'BR'})

        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.error)
        self.assertIn('cUSD en BNB Smart Chain', result.error)
        client.create_ramp_order.assert_not_called()

    def _create_order(
        self,
        *,
        meta,
        redeem_blocked_reason=None,
        raw_usdt_wei=182 * 10**18,
        cusd_usdt_wei=0,
        withdrawable_usdt_wei=182 * 10**18,
        operational_error=None,
    ):
        user = SimpleNamespace(is_authenticated=True, id=7, phone_country='BR')
        account = SimpleNamespace(
            bsc_address='0x' + ('1' * 40),
            account_type='personal',
        )
        info = SimpleNamespace(context=SimpleNamespace(user=user, META=meta))
        preview = SimpleNamespace(net=180, gross_wei=182 * 10**18)
        client = mock.Mock(is_configured=True)

        with mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
             mock.patch('ramps.schema._resolve_ramp_country_code', return_value='BR'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=account), \
             mock.patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None), \
             mock.patch('ramps.schema._get_saved_bank_info', return_value=object()), \
             mock.patch('ramps.schema.KoyweClient', return_value=client), \
             mock.patch(
                 'cusd_plus.cusd_vault.require_operational',
                 side_effect=operational_error,
             ), \
             mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', return_value=preview), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=raw_usdt_wei), \
             mock.patch('cusd_plus.vault.cusd_withdrawable_usdt_wei', return_value=cusd_usdt_wei), \
             mock.patch('cusd_plus.vault.withdrawable_usdt_wei', return_value=withdrawable_usdt_wei), \
             mock.patch(
                 'cusd_plus.vault.redeem_blocked_reason',
                 return_value=redeem_blocked_reason,
             ):
            result = CreateRampOrder().mutate(
                info,
                direction='OFF_RAMP',
                amount='182',
                payment_method_code='PIX',
                bank_info_id='1',
                destination='cusd_plus',
            )

        return result, client

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_legacy_raw_usdt_holder_is_told_to_update_for_cusd_bsc(self):
        result, client = self._create_order(meta={})

        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.error)
        self.assertIn('cUSD en BNB Smart Chain', result.error)
        client.create_ramp_order.assert_not_called()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_legacy_brazil_update_gate_runs_before_contract_preflight(self):
        result, client = self._create_order(
            meta={'HTTP_CF_IPCOUNTRY': 'BR'},
            operational_error=RuntimeError('RPC unavailable'),
        )

        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.error)
        self.assertNotIn('conversiones de dólares están pausadas', result.error)
        client.create_ramp_order.assert_not_called()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_fee_capable_client_cannot_fund_bsc_withdrawal_from_raw_usdt(self):
        result, client = self._create_order(
            meta={'HTTP_X_CONFIO_FEE_CAPABLE': '1'},
        )

        self.assertFalse(result.success)
        self.assertIn('Disponible: 0.000000', result.error)
        self.assertNotIn('Actualiza la app', result.error)
        client.create_ramp_order.assert_not_called()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_raw_usdt_update_message_wins_over_unrelated_redeem_outage(self):
        result, client = self._create_order(
            meta={},
            redeem_blocked_reason='redeem_state_unreadable',
        )

        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.error)
        self.assertNotIn('retiros desde tu ahorro están pausados', result.error)
        client.create_ramp_order.assert_not_called()

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_legacy_brazil_client_must_update_even_after_cusd_bsc_conversion(self):
        result, client = self._create_order(
            meta={'HTTP_CF_IPCOUNTRY': 'BR'},
            raw_usdt_wei=0,
            cusd_usdt_wei=182 * 10**18,
            withdrawable_usdt_wei=182 * 10**18,
        )

        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.error)
        self.assertIn('cUSD en BNB Smart Chain', result.error)
        client.create_ramp_order.assert_not_called()
