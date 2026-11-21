"""Paying a merchant's Pix charge (dynamic BR Code or fixed-amount static code)
at its exact amount in reais, funded by the person's own dollars."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock
import uuid

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from payment_accounts import local_money
from payment_accounts.activity import display_stage
from payment_accounts.bridge_execution import reconcile_provider_credit
from payment_accounts.infinia_journeys import advance_journey, create_journey
from payment_accounts.models import InfiniaJourney, LedgerEntry, MoneyOperation, PayoutDestination
from payment_accounts.services import PaymentAccountError
from .test_bridge_execution import DEST_HASH
from . import test_infinia_journeys as journey_tests
from .test_local_money import qr, tlv

# Infinia's sandbox dynamic charge (Testing in Sandbox, Bank Account Validation).
DYNAMIC = ('00020101021226800014br.gov.bcb.pix2558pix.example.com/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783'
           '5204000053039865802BR5915INFINIA SANDBOX6009SAO PAULO62070503***63044C26')
STATIC_AMOUNT = ('00020126450014br.gov.bcb.pix0123anasilva@infiniaweb.com5204000053039865406150.005802BR'
                 '5909ANA SILVA6009SAO PAULO62200516INFINIASANDBOX016304BB9A')
PIX = tlv('00', 'br.gov.bcb.pix')


class PixCodeTests(SimpleTestCase):
    method = local_money.METHODS['br_qr']

    def test_sandbox_codes_parse(self):
        dynamic = local_money.pix_code(DYNAMIC)
        self.assertEqual((dynamic['dynamic'], dynamic['fixed'], dynamic['key'], dynamic['txid']), (True, True, '', ''))
        self.assertEqual(dynamic['location'], 'pix.example.com/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783')
        static = local_money.pix_code(STATIC_AMOUNT)
        self.assertEqual((static['dynamic'], static['fixed'], static['amount'], static['txid']),
                         (False, True, '150.00', 'INFINIASANDBOX01'))
        self.assertEqual(local_money.normalize_value(self.method, DYNAMIC), DYNAMIC)
        self.assertEqual(local_money.normalize_value(self.method, STATIC_AMOUNT), STATIC_AMOUNT)

    def test_fixed_codes_are_checked_on_the_pix_network_and_open_ones_by_key(self):
        for payload in (DYNAMIC, STATIC_AMOUNT):
            self.assertEqual(local_money._validation_request(self.method, payload),
                             {'country': 'BR', 'account': {'dataType': 'QR_CODE', 'qrCode': payload}})
        open_code = qr(('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'), ('58', 'BR'))
        self.assertFalse(local_money.fixed_pix_charge(self.method, open_code))
        self.assertEqual(local_money._validation_request(self.method, open_code)['account']['dataType'], 'PIX_KEY')

    def test_refuses_codes_that_are_not_one_payable_charge(self):
        location = tlv('25', 'bank.example/cob/1')
        cases = {
            'key and location': (('26', PIX + tlv('01', 'ana@example.com') + location), ('53', '986'), ('58', 'BR')),
            'neither': (('26', PIX), ('53', '986'), ('58', 'BR')),
            'pix automatico': (('26', PIX + location), ('53', '986'), ('58', 'BR'),
                               ('80', PIX + tlv('25', 'bank.example/rec/1'))),
            'bad amount': (('26', PIX + location), ('53', '986'), ('54', '0.00'), ('58', 'BR')),
            'malformed amount': (('26', PIX + location), ('53', '986'), ('54', '1.001'), ('58', 'BR')),
            'location without path': (('26', PIX + tlv('25', 'example')), ('53', '986'), ('58', 'BR')),
            'not reais': (('26', PIX + location), ('53', '840'), ('58', 'BR')),
        }
        for name, fields in cases.items():
            with self.subTest(name), self.assertRaises(PaymentAccountError):
                local_money.normalize_value(self.method, qr(*fields))
        with self.assertRaises(PaymentAccountError):
            local_money.normalize_value(self.method, DYNAMIC[:-1] + '0')

    def test_argentine_fixed_amount_codes_stay_refused(self):
        payload = qr(('01', '12'), ('53', '032'), ('54', '1500.00'), ('58', 'AR'))
        with self.assertRaisesRegex(PaymentAccountError, 'monto fijo'):
            local_money.normalize_value(local_money.METHODS['ar_qr'], payload)

    def test_summary_keeps_the_networks_answer_for_a_charge(self):
        summary = local_money.summarize_validation({'id': 'v1', 'status': 'SUCCESSFUL', 'countryData': {
            'type': 'dynamic', 'amount': 250.75, 'expiration': '2030-12-31T23:59:59Z', 'holder': 'INFINIA SANDBOX LTDA',
            'holderDocument': '12345678000195', 'bankName': 'Banco'}})
        self.assertEqual(summary['holder_name'], 'INFINIA SANDBOX LTDA')
        self.assertEqual(summary['holder_document'], '•••• 0195')
        self.assertEqual(summary['institution'], 'Banco')
        self.assertEqual(summary['charge'], {'type': 'dynamic', 'amount': '250.75',
                                             'expiration': '2030-12-31T23:59:59Z', 'txid': ''})


def charge_validation(amount='250.75', kind='dynamic', expires_in=timedelta(hours=1), checked=None, holder='INFINIA SANDBOX LTDA'):
    return {'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': holder, 'holder_document': '•••• 0195',
            'institution': 'Banco', 'checked_at': (checked or timezone.now()).isoformat(),
            'charge': {'type': kind, 'amount': amount, 'txid': '',
                       'expiration': (timezone.now() + expires_in).isoformat() if expires_in else ''}}


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    INFINIA_ACCOUNT_VALIDATION_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True, PAYMENT_BRIDGE_POLYGON_ENABLED=True,
    CUSD_PLUS_7702_ENABLED=True)
class PixChargeBase(TestCase):
    quote = journey_tests.JourneyTests.quote
    prepared = journey_tests.JourneyTests.prepared
    credit = journey_tests.JourneyTests.credit
    settle_fx = journey_tests.JourneyTests.settle_fx

    def setUp(self):
        journey_tests.JourneyTests.setUp(self)
        from payment_accounts.models import AccountActivation
        AccountActivation.objects.create(confio_account=self.owner, country='BRA', asset='BRL', status='legacy')
        self.local.country, self.local.asset = 'BRA', 'BRL'
        self.local.save(update_fields=['country', 'asset'])
        self.charge = self.charge_destination(DYNAMIC, charge_validation())
        self.api.create_bank_account_validation.return_value = {
            'id': 'v2', 'status': 'SUCCESSFUL', 'countryData': {
                'type': 'dynamic', 'amount': 250.75, 'holder': 'INFINIA SANDBOX LTDA',
                'expiration': (timezone.now() + timedelta(hours=1)).isoformat()}}

    def tearDown(self):
        mock.patch.stopall()

    def charge_destination(self, payload, validation):
        return PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='qr', country='BRA', asset='BRL',
            label='QR', holder_name=validation.get('holder_name', ''),
            details={'type': 'BR_CODE', 'brCode': payload},
            provider_data={'method_id': 'br_qr', 'validation': validation})

    def target_quote(self, source='46.10', target='250.75'):
        self.api.create_transfer_quote.return_value = dict(
            id='fx-exact', status='ACTIVE', source_account_id='crypto', target_account_id='local',
            source_amount=source, target_amount=target,
            expire_at=(timezone.now() + timedelta(minutes=1)).isoformat())

    def funded(self, destination=None, credit='50'):
        t, _ = self.prepared(); t.status = 'delivered'; t.destination_tx_hash = DEST_HASH; t.save()
        entry = self.credit(self.crypto, amount=credit, provider_data={'third_party': {
            'type': 'CRYPTO', 'crypto_network': 'POLYGON', 'transaction_hash': DEST_HASH}})
        reconcile_provider_credit(t)
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                              request_id=uuid.uuid4(), direction='to_bank', bridge=t,
                              destination=destination or self.charge, minimum_fx_output='250.75'), entry

    def returned(self, j):
        return MoneyOperation.objects.get(money_flow=j.money_flow,
                                          idempotency_key=str(uuid.uuid5(j.internal_id, 'return')))


class PixChargeJourneyTests(PixChargeBase):
    # -------------------------------------------------------------- creation

    def test_journey_pins_the_charge_and_requires_its_exact_amount(self):
        j, _ = self.funded()
        self.assertEqual(j.destination_snapshot['pix_charge']['amount'], '250.75')
        self.assertTrue(j.destination_snapshot['pix_charge']['single_use'])
        self.assertEqual(j.destination_snapshot['pix_charge']['holder'], 'INFINIA SANDBOX LTDA')

    def test_refuses_an_authorization_that_is_not_the_charge_amount(self):
        t, _ = self.prepared()
        with self.assertRaisesRegex(PaymentAccountError, 'no coincide'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                           request_id=uuid.uuid4(), direction='to_bank', bridge=t,
                           destination=self.charge, minimum_fx_output='240')
        self.assertFalse(InfiniaJourney.objects.exists())

    def test_refuses_unverified_stale_or_expiring_charges(self):
        cases = {
            'confirmar': dict(charge_validation(), status='TEMPORARY_FAILURE'),
            'de nuevo': charge_validation(checked=timezone.now() - timedelta(minutes=11)),
            'vence': charge_validation(expires_in=timedelta(minutes=5)),
        }
        for message, validation in cases.items():
            with self.subTest(message):
                destination = self.charge_destination(DYNAMIC, validation)
                with self.assertRaisesRegex(PaymentAccountError, message):
                    local_money.require_payable_charge(self.owner, destination)

    def test_a_static_codes_printed_amount_must_match_the_network(self):
        mismatch = self.charge_destination(STATIC_AMOUNT, charge_validation(amount='149.00', kind='static'))
        self.assertFalse(local_money.pix_charge(mismatch)['verified'])
        match = self.charge_destination(STATIC_AMOUNT, charge_validation(amount='150.0', kind='static'))
        self.assertTrue(local_money.pix_charge(match)['verified'])
        # A printed static code is reusable even with a txid: only a payment in flight blocks it.
        self.assertFalse(local_money.pix_charge(match)['single_use'])

    def test_a_dynamic_charge_without_a_readable_expiry_is_refused(self):
        for expiration in ('', '3600', 'soon'):
            with self.subTest(expiration=expiration):
                validation = charge_validation()
                validation['charge']['expiration'] = expiration
                self.assertFalse(local_money.pix_charge(self.charge_destination(DYNAMIC, validation))['verified'])

    def test_a_charge_is_paid_once(self):
        j, _ = self.funded()
        with self.assertRaisesRegex(PaymentAccountError, 'en curso'):
            local_money.require_payable_charge(self.owner, self.charge)
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')
        with self.assertRaisesRegex(PaymentAccountError, 'Ya pagaste'):
            local_money.require_payable_charge(self.owner, self.charge)
        # Refunded or never funded: the person may try again.
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='failed')
        self.assertTrue(local_money.require_payable_charge(self.owner, self.charge)['verified'])
        # The same request retried is not a second payment.
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')
        local_money.require_payable_charge(self.owner, self.charge, exclude_request_id=j.request_id)

    def test_a_static_code_marked_single_use_is_paid_once(self):
        once = qr(('01', '12'), ('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'),
                  ('54', '25.00'), ('58', 'BR'))
        destination = self.charge_destination(once, charge_validation(amount='25.00', kind='static'))
        self.assertTrue(local_money.pix_charge(destination)['single_use'])
        reusable = qr(('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'), ('54', '25.00'), ('58', 'BR'))
        self.assertFalse(local_money.pix_charge(self.charge_destination(
            reusable, charge_validation(amount='25.00', kind='static')))['single_use'])

    def test_a_dynamic_charge_is_paid_once_whoever_pays(self):
        j, _ = self.funded()
        other = self.charge_destination(DYNAMIC, charge_validation())
        InfiniaJourney.objects.filter(pk=j.pk).update(confio_account=self.make_other_owner())
        with self.assertRaisesRegex(PaymentAccountError, 'en curso'):
            local_money.require_payable_charge(self.owner, other)

    def make_other_owner(self):
        from users.models import Account
        return Account.objects.create(user=self.owner.user, account_type='business', account_index=7)

    def test_charges_are_not_offered_as_saved_recipients(self):
        flagged = self.charge_destination(DYNAMIC, charge_validation())
        flagged.provider_data = dict(flagged.provider_data, fixed_charge=True); flagged.save()
        open_code = qr(('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'), ('58', 'BR'))
        normal = self.charge_destination(open_code, dict(charge_validation(), charge={}))
        rows = local_money.saved_destinations(self.owner, 'br_qr')
        self.assertNotIn(self.charge, rows)
        self.assertNotIn(flagged, rows)
        # Every recipient that is not a charge is still listed.
        self.assertIn(normal, rows)

    # ----------------------------------------------------------- money paths

    def test_pays_the_exact_amount_and_returns_the_unused_dollars(self):
        j, entry = self.funded()
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.assertEqual(j.fx_operation.source_amount, Decimal('46.10'))
        self.api.create_transfer_quote.assert_called_with(mock.ANY)
        self.assertEqual(self.api.create_transfer_quote.call_args[0][0]['target_amount'], 250.75)
        self.settle_fx(j, self.local, '250.75')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.payout_operation.source_amount, Decimal('250.75'))
        self.assertEqual(j.payout_operation.external_destination['destination_account']['brCode'], DYNAMIC)
        j.payout_operation.status = 'succeeded'; j.payout_operation.target_amount = Decimal('250.75')
        j.payout_operation.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'returning_remainder')
        self.assertEqual(display_stage(j), 'completed')
        back = self.returned(j)
        self.assertEqual(back.source_amount, Decimal('3.900000'))
        self.assertEqual(back.source_account, self.crypto)
        self.assertEqual(back.external_destination['destination_account'],
                         {'type': 'POLYGON', 'address': j.wallet_address})
        # Retried passes never open a second return.
        advance_journey(j.pk, client=self.api)
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow, operation_type='payout').count(), 2)
        back.status = 'succeeded'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'completed')
        self.assertEqual(j.money_flow.metadata['pix_charge_return']['reason'], 'pix_charge_remainder')

    def test_no_return_leg_when_nothing_is_left(self):
        j, _ = self.funded(credit='46.10')
        self.target_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '250.75')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        j.payout_operation.status = 'succeeded'; j.payout_operation.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'completed')
        self.assertFalse(MoneyOperation.objects.filter(
            idempotency_key=str(uuid.uuid5(j.internal_id, 'return'))).exists())

    def refunds(self, j, reason):
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('refunding', reason))
        self.assertIsNone(j.fx_operation_id)
        back = self.returned(j)
        self.assertEqual(back.source_amount, Decimal('50.000000'))
        back.status = 'succeeded'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('failed', reason))
        self.assertEqual(display_stage(j), 'refunded')

    def test_a_charge_paid_elsewhere_returns_all_the_dollars(self):
        j, _ = self.funded()
        self.api.create_bank_account_validation.return_value = {'id': 'v3', 'status': 'ERROR', 'countryData': {}}
        self.refunds(j, 'pix_charge_unpayable')

    def test_a_changed_charge_returns_all_the_dollars(self):
        j, _ = self.funded()
        self.api.create_bank_account_validation.return_value['countryData']['amount'] = 260
        self.refunds(j, 'pix_charge_changed')

    def test_a_rate_that_no_longer_fits_returns_all_the_dollars(self):
        j, _ = self.funded()
        self.target_quote(source='50.01')
        self.refunds(j, 'pix_charge_fx_short')

    def test_a_charge_about_to_expire_is_not_converted(self):
        j, _ = self.funded()
        snapshot = dict(j.destination_snapshot)
        snapshot['pix_charge'] = dict(snapshot['pix_charge'],
                                      expires_at=(timezone.now() + timedelta(seconds=60)).isoformat())
        InfiniaJourney.objects.filter(pk=j.pk).update(destination_snapshot=snapshot)
        self.refunds(j, 'pix_charge_expiring')
        self.api.create_bank_account_validation.assert_not_called()

    def test_an_unanswered_check_waits_then_gives_the_dollars_back(self):
        j, entry = self.funded()
        self.api.create_bank_account_validation.return_value = {'id': 'v4', 'status': 'TEMPORARY_FAILURE'}
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'awaiting_credit')
        self.assertIsNone(j.fx_operation_id)
        LedgerEntry.objects.filter(pk=entry.pk).update(created_at=timezone.now() - timedelta(minutes=31))
        self.refunds(j, 'pix_charge_unconfirmed')

    def test_a_running_check_is_polled_not_asked_again(self):
        j, _ = self.funded()
        self.api.create_bank_account_validation.return_value = {'id': 'v9', 'status': 'IN_PROGRESS'}
        advance_journey(j.pk, client=self.api)
        self.api.get_bank_account_validation.return_value = {'id': 'v9', 'status': 'IN_PROGRESS'}
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(self.api.create_bank_account_validation.call_count, 1)
        self.api.get_bank_account_validation.assert_called_with('v9')
        self.assertIsNone(j.fx_operation_id)
        self.api.get_bank_account_validation.return_value = {'id': 'v9', 'status': 'SUCCESSFUL', 'countryData': {
            'type': 'dynamic', 'amount': 250.75, 'holder': 'INFINIA SANDBOX LTDA'}}
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.assertEqual(self.api.create_bank_account_validation.call_count, 1)

    def test_a_failed_return_is_reviewed(self):
        j, _ = self.funded()
        self.api.create_bank_account_validation.return_value = {'id': 'v3', 'status': 'ERROR', 'countryData': {}}
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        back = self.returned(j); back.status = 'failed'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_return_failed'))

    def test_an_expired_charge_after_conversion_is_never_paid(self):
        j, _ = self.funded()
        self.target_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '250.75')
        j.refresh_from_db()
        snapshot = dict(j.destination_snapshot)
        snapshot['pix_charge'] = dict(snapshot['pix_charge'], expires_at=(timezone.now() - timedelta(seconds=1)).isoformat())
        InfiniaJourney.objects.filter(pk=j.pk).update(destination_snapshot=snapshot)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_expired_after_conversion'))
        self.assertIsNone(j.payout_operation_id)

    def test_conversion_names_the_reais_to_land(self):
        from payment_accounts.providers.infinia import InfiniaProvider
        j, _ = self.funded()
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        client = mock.Mock()
        client.create_internal_transfer.return_value = {'id': 't1', 'status': 'PENDING'}
        adapter = InfiniaProvider.__new__(InfiniaProvider); adapter.client = client
        adapter.create_transfer(j.fx_operation)
        payload = client.create_internal_transfer.call_args[0][0]
        self.assertEqual(payload['target_amount'], 250.75)
        self.assertNotIn('source_amount', payload)
        self.assertEqual(payload['quote_id'], 'fx-exact')


@override_settings(LOCAL_MONEY_PIX_FX_BUFFER_BPS=100)
class PixChargeQuoteTests(PixChargeBase):
    """The all-in price: exactly the charge to the merchant, the rest covered by the buffer."""

    def run_quote(self, minimums):
        estimates = iter(minimums)
        self.target_quote(source='46.10')
        with mock.patch.object(local_money, '_active_pair', return_value=(self.local, self.crypto)), \
                mock.patch.object(local_money, '_bridge_estimate',
                                  side_effect=lambda owner, crypto, total, fee: (*next(estimates), self.instruction)), \
                mock.patch('payment_accounts.infinia_fee_policy.price', return_value=None):
            return local_money.pix_charge_quote(self.owner, self.charge, client=self.api)

    def test_budget_grows_until_the_bridge_minimum_covers_the_buffered_conversion(self):
        quote = self.run_quote([(Decimal('46.00'), Decimal('46.40')), (Decimal('46.60'), Decimal('47.00'))])
        # 46.10 × 1.01 = 46.5610 → 46.57 needed; the first estimate falls short.
        self.assertEqual(quote['amount'], Decimal('250.75'))
        self.assertGreater(quote['total_usd'], Decimal('46.57'))
        self.assertEqual(quote['merchant_name'], 'INFINIA SANDBOX LTDA')
        self.assertEqual(quote['estimated_return_usd'], Decimal('0.90'))
        self.assertTrue(quote['dynamic'])

    def test_gives_up_rather_than_underfund(self):
        with self.assertRaisesRegex(PaymentAccountError, 'No pudimos cotizar'):
            self.run_quote([(Decimal('1'), Decimal('1'))] * 5)
