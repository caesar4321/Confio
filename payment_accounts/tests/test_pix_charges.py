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
from payment_accounts.pix_payload import PixPayloadError
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

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
    def test_charges_are_read_without_the_paid_lookup(self):
        client = mock.Mock()
        static = local_money._validate(self.method, STATIC_AMOUNT, client)
        self.assertEqual((static['status'], static['holder_name'], static['holder_source']),
                         ('SUCCESSFUL', 'ANA SILVA', 'qr'))
        self.assertEqual(static['charge'], {'type': 'static', 'amount': '150.00', 'expiration': '',
                                            'txid': 'INFINIASANDBOX01'})
        with mock.patch('payment_accounts.pix_payload.resolve_dynamic', return_value={
                'amount': Decimal('250.75'), 'expires_at': timezone.now() + timedelta(hours=1), 'txid': 't' * 26,
                'key': 'k', 'receiver_name': '', 'revision': 0, 'domain': 'pix.example.com'}) as network:
            dynamic = local_money._validate(self.method, DYNAMIC, client)
        network.assert_called_once_with('pix.example.com/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783')
        self.assertEqual((dynamic['status'], dynamic['holder_name'], dynamic['holder_source'], dynamic['institution']),
                         ('SUCCESSFUL', 'INFINIA SANDBOX', 'qr', 'pix.example.com'))
        client.create_bank_account_validation.assert_not_called()
        open_code = qr(('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'), ('58', 'BR'))
        self.assertFalse(local_money.fixed_pix_charge(self.method, open_code))
        self.assertEqual(local_money._validation_request(self.method, open_code)['account']['dataType'], 'PIX_KEY')

    @override_settings(LOCAL_MONEY_PIX_CHARGES_ENABLED=False)
    def test_charges_have_their_own_switch(self):
        self.assertEqual(local_money._validate(self.method, STATIC_AMOUNT, mock.Mock())['status'], 'DISABLED')

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
        # The Pix network's answer when a journey reads the charge again.
        self.network = mock.patch('payment_accounts.pix_payload.resolve_dynamic', return_value={
            'amount': Decimal('250.75'), 'expires_at': timezone.now() + timedelta(hours=1), 'txid': 't' * 26,
            'key': 'k', 'receiver_name': 'INFINIA SANDBOX LTDA', 'revision': 0,
            'domain': 'pix.example.com'}).start()

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

    def test_a_qr_name_is_never_shown_as_a_verified_holder(self):
        validation = dict(charge_validation(), holder_source='qr')
        view = local_money.destination_view(self.charge_destination(DYNAMIC, validation))
        self.assertEqual((view['verification'], view['holder_name']), ('unverified', ''))
        # A provider (DICT) answer still shows as verified.
        view = local_money.destination_view(self.charge)
        self.assertEqual(view['verification'], 'verified')

    def test_a_journey_authorized_on_a_dict_name_is_not_refunded_for_a_qr_name(self):
        j, _ = self.funded()
        self.network.return_value = dict(self.network.return_value, receiver_name='')  # QR name 'INFINIA SANDBOX'
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')

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
        self.network.side_effect = PixPayloadError('charge is CONCLUIDA', gone=True)
        self.refunds(j, 'pix_charge_unpayable')

    def test_a_changed_charge_returns_all_the_dollars(self):
        j, _ = self.funded()
        self.network.return_value = dict(self.network.return_value, amount=Decimal('260.00'))
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
        self.network.assert_not_called()

    def test_an_unanswered_check_waits_then_gives_the_dollars_back(self):
        j, entry = self.funded()
        self.network.side_effect = PixPayloadError('fetch failed', temporary=True)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'awaiting_credit')
        self.assertIsNone(j.fx_operation_id)
        flow = j.money_flow
        flow.metadata = dict(flow.metadata, pix_charge_recheck=dict(
            flow.metadata['pix_charge_recheck'], first_unanswered_at=(timezone.now() - timedelta(minutes=31)).isoformat()))
        flow.save(update_fields=['metadata'])
        self.refunds(j, 'pix_charge_unconfirmed')

    def test_a_journey_never_uses_the_paid_lookup(self):
        j, _ = self.funded()
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.network.assert_called_once()
        self.api.create_bank_account_validation.assert_not_called()

    def test_a_failed_return_is_reviewed(self):
        j, _ = self.funded()
        self.network.side_effect = PixPayloadError('charge returned 410', gone=True)
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


class PixChargeUnwindTests(PixChargeBase):
    """A charge whose payout fails cleanly goes back to dollars, automatically."""

    def paid_out(self, credit='50'):
        j, _ = self.funded(credit=credit)
        self.target_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '250.75')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertIsNotNone(j.payout_operation_id)
        return j

    def fail_payout(self, j):
        # The provider refuses the payout; the sync flips the journey to review.
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(status='failed', failure_code='')
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='needs_review', failure_code='provider_leg_requires_review')

    def live(self, j):
        from payment_accounts.infinia_bridge import live_journeys
        return live_journeys(InfiniaJourney.objects.filter(pk=j.pk)).exists()

    def candidate(self, j):
        from payment_accounts.infinia_journeys import unwind_candidates
        return unwind_candidates(InfiniaJourney.objects.filter(pk=j.pk)).exists()

    def unwind(self, j):
        return MoneyOperation.objects.get(money_flow=j.money_flow,
                                          idempotency_key=str(uuid.uuid5(j.internal_id, 'unwind')))

    def settle_unwind(self, j, usdc='45.80'):
        op = self.unwind(j)
        op.provider_operation_id = 'unwind-id'; op.status = 'settling'; op.save()
        self.credit(self.crypto, amount=usdc, provider_data={
            'operation': {'type': 'INTERNAL_TRANSFER', 'operation_id': 'unwind-id'}})

    def test_a_failed_payout_returns_every_dollar_the_journey_holds(self):
        j = self.paid_out()
        self.fail_payout(j)
        # Visited by the worker, but not live: it reserves nothing.
        self.assertFalse(self.live(j))
        self.assertTrue(self.candidate(j))
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')
        self.assertTrue(self.live(j))
        self.assertEqual(display_stage(j), 'refunding')
        op = self.unwind(j)
        self.assertEqual((op.source_account, op.destination_account, op.source_amount),
                         (self.local, self.crypto, Decimal('250.75')))
        # A failed leg elsewhere in the flow flips it to review again: it keeps going.
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='needs_review', failure_code='provider_leg_requires_review')
        self.assertTrue(self.live(j))
        self.settle_unwind(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'refunding')
        back = self.returned(j)
        # 50 arrived, 46.10 converted, 45.80 came back from the reais.
        self.assertEqual(back.source_amount, Decimal('49.700000'))
        self.assertEqual(back.external_destination['destination_account'],
                         {'type': 'POLYGON', 'address': j.wallet_address})
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='needs_review', failure_code='provider_leg_requires_review')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'refunding')  # unparked so its submission is allowed
        back.status = 'succeeded'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('failed', 'pix_charge_payout_failed'))
        self.assertEqual(display_stage(j), 'refunded')
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'done')
        self.assertFalse(self.live(j))

    def test_an_expired_charge_after_conversion_is_unwound_too(self):
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
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('unwinding', 'pix_charge_expired'))
        self.assertEqual(self.unwind(j).source_amount, Decimal('250.75'))

    def test_a_payout_that_moved_money_is_never_unwound(self):
        j = self.paid_out()
        self.fail_payout(j)
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(provider_operation_id='payout-id')
        self.credit(self.local, amount='250.75', provider_data={})  # unrelated credit
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local, provider_entry_id='debit-1',
                                   direction='debit', asset='BRL', amount='250.75', occurred_at=timezone.now(),
                                   provider_data={'operation': {'type': 'PAYOUT', 'operation_id': 'payout-id'}})
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')
        self.assertFalse(MoneyOperation.objects.filter(idempotency_key=str(uuid.uuid5(j.internal_id, 'unwind'))).exists())
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'not_applicable')
        # Checked once, never live again: it cannot block the owner's next payment.
        self.assertFalse(self.live(j))

    def test_a_failed_unwind_parks_for_a_human_and_stops_being_live(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        MoneyOperation.objects.filter(pk=self.unwind(j).pk).update(status='failed')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_unwind_leg_problem'))
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'stopped')
        self.assertFalse(self.live(j))

    def test_the_unwind_runs_at_the_current_rate_not_the_payment_quote(self):
        from payment_accounts.providers.infinia import InfiniaProvider
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        client = mock.Mock()
        client.create_internal_transfer.return_value = {'id': 't2', 'status': 'PENDING'}
        adapter = InfiniaProvider.__new__(InfiniaProvider); adapter.client = client
        adapter.create_transfer(self.unwind(j))
        payload = client.create_internal_transfer.call_args[0][0]
        self.assertNotIn('quote_id', payload)
        self.assertEqual(payload['source_amount'], 250.75)
        self.assertNotIn('target_amount', payload)

    def test_a_payout_the_provider_still_has_is_never_unwound(self):
        j = self.paid_out()
        self.fail_payout(j)
        self.api.find_operation.return_value = [{'originId': 'x', 'status': 'IN_PROGRESS'}]
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'not_applicable')
        self.assertFalse(MoneyOperation.objects.filter(idempotency_key=str(uuid.uuid5(j.internal_id, 'unwind'))).exists())

    def test_no_answer_from_the_provider_waits_without_deciding(self):
        from payment_accounts.clients import ProviderAPIError
        j = self.paid_out()
        self.fail_payout(j)
        self.api.find_operation.side_effect = ProviderAPIError('unavailable')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertNotIn('pix_charge_unwind', j.money_flow.metadata)
        self.assertTrue(self.candidate(j))
        self.assertFalse(self.live(j))
        self.api.find_operation.side_effect = None
        self.api.find_operation.return_value = []
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')

    def test_the_flow_sync_leaves_an_active_unwind_alone(self):
        from payment_accounts.services import _sync_flow_status
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        _sync_flow_status(j.money_flow); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')

    def test_a_parked_unwind_stops_being_live(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.owner.bsc_address = '0x' + '9' * 40; self.owner.save(update_fields=['bsc_address'])
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'wallet_changed'))
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'stopped')
        self.assertFalse(self.live(j))

    def test_an_unwind_that_cannot_be_submitted_for_hours_is_parked(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        MoneyOperation.objects.filter(pk=self.unwind(j).pk).update(created_at=timezone.now() - timedelta(hours=7))
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_unwind_stuck'))
        self.assertFalse(self.live(j))
        # The never-submitted leg no longer reserves the account or the owner.
        self.assertEqual((self.unwind(j).status, self.unwind(j).failure_code), ('failed', 'never_submitted'))

    def test_a_rate_limited_payout_is_not_unwound(self):
        j = self.paid_out()
        self.fail_payout(j)
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(failure_code='429')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'not_applicable')
        self.assertFalse(self.live(j))

    def test_a_provider_that_never_answers_stops_holding_the_owner(self):
        from payment_accounts.clients import ProviderAPIError
        j = self.paid_out()
        self.fail_payout(j)
        self.api.find_operation.side_effect = ProviderAPIError('unavailable')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertTrue(self.candidate(j))
        flow = j.money_flow
        flow.metadata = dict(flow.metadata, pix_charge_unwind_wait=(timezone.now() - timedelta(hours=7)).isoformat())
        flow.save(update_fields=['metadata'])
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'not_applicable')
        self.assertFalse(self.live(j))

    def test_a_late_webhook_never_reopens_a_finished_unwind(self):
        from payment_accounts.services import _sync_flow_status
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api)
        self.settle_unwind(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        back = self.returned(j); back.status = 'succeeded'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'failed')
        _sync_flow_status(j.money_flow); j.refresh_from_db()
        self.assertEqual(j.stage, 'failed')
        self.assertEqual(display_stage(j), 'refunded')

    def test_a_refund_reversed_after_the_unwind_is_reopened_for_review(self):
        from payment_accounts.services import _sync_flow_status
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api)
        self.settle_unwind(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        back = self.returned(j); back.status = 'succeeded'; back.save()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'failed')
        back.status = 'reversed'; back.save()
        _sync_flow_status(j.money_flow); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'provider_leg_requires_review'))

    def test_two_parked_charges_unwind_one_after_the_other(self):
        first = self.paid_out()
        self.fail_payout(first)
        # A second parked charge journey of the same person on the same accounts.
        second = InfiniaJourney.objects.get(pk=first.pk)
        second.pk = None; second.internal_id = uuid.uuid4(); second.request_id = uuid.uuid4()
        flow = first.money_flow; flow.pk = None; flow.internal_id = uuid.uuid4(); flow.metadata = {}; flow.save()
        second.money_flow = flow; second.fx_operation = None; second.payout_operation = None
        second.funding_credit = None; second.bridge = None
        second.save()
        self.assertFalse(self.live(second))
        advance_journey(first.pk, client=self.api); first.refresh_from_db()
        self.assertEqual(first.stage, 'unwinding')
        # The parked one never blocked it, and it cannot block the owner either.
        self.assertFalse(self.live(second))

    def test_a_reversed_conversion_stops_the_unwind_before_more_money_moves(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')
        MoneyOperation.objects.filter(pk=j.fx_operation_id).update(status='reversed')
        self.submit.reset_mock()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_unwind_leg_problem'))
        self.submit.assert_not_called()
        self.assertFalse(self.live(j))

    def test_a_late_flip_of_the_triggering_payout_reopens_the_flow(self):
        from payment_accounts.services import _sync_flow_status
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(status='needs_review')
        _sync_flow_status(j.money_flow); j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')
        self.submit.reset_mock()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'pix_charge_unwind_leg_problem'))
        self.submit.assert_not_called()

    def test_an_auth_error_is_not_a_refusal(self):
        j = self.paid_out()
        self.fail_payout(j)
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(failure_code='401')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.money_flow.metadata['pix_charge_unwind']['state'], 'not_applicable')

    def test_an_invalid_request_is_a_refusal(self):
        j = self.paid_out()
        self.fail_payout(j)
        MoneyOperation.objects.filter(pk=j.payout_operation_id).update(failure_code='422')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')

    def test_a_parked_unwind_leaves_nothing_reserving_the_owner(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()  # unwind created, not submitted (mock)
        MoneyOperation.objects.filter(pk=j.fx_operation_id).update(status='reversed')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(self.unwind(j).status, 'failed')
        self.assertFalse(MoneyOperation.objects.filter(
            source_account__in=[self.local, self.crypto], status__in=['created', 'submitted', 'processing',
                                                                      'settling', 'unknown']).exists())

    def test_an_unwind_once_started_is_not_held_by_other_activity(self):
        j = self.paid_out()
        self.fail_payout(j)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')
        self.settle_unwind(j)
        # Another live journey of the person exists now: the started unwind still finishes.
        with mock.patch('payment_accounts.infinia_journeys.live_journeys') as live:
            live.return_value.exclude.return_value.exists.return_value = True
            advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'refunding')

    def test_a_conversion_whose_status_has_not_landed_waits(self):
        j = self.paid_out()
        self.fail_payout(j)
        MoneyOperation.objects.filter(pk=j.fx_operation_id).update(status='processing')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertNotIn('pix_charge_unwind', j.money_flow.metadata)
        MoneyOperation.objects.filter(pk=j.fx_operation_id).update(status='succeeded')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'unwinding')

class PixChargeRecheckTests(PixChargeBase):
    def test_an_unreadable_answer_waits_instead_of_refunding(self):
        j, entry = self.funded()
        self.network.side_effect = PixPayloadError('response is not a compact JWS')  # e.g. a WAF page
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'awaiting_credit')
        self.assertFalse(MoneyOperation.objects.filter(
            idempotency_key=str(uuid.uuid5(j.internal_id, 'return'))).exists())
        self.network.side_effect = None
        self.target_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')

    def test_a_late_first_check_still_gets_its_full_wait(self):
        j, entry = self.funded()
        LedgerEntry.objects.filter(pk=entry.pk).update(created_at=timezone.now() - timedelta(hours=2))
        self.network.side_effect = PixPayloadError('503', temporary=True)
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        # Not refunded on the first unanswered check, however old the credit.
        self.assertEqual(j.stage, 'awaiting_credit')
        self.assertFalse(MoneyOperation.objects.filter(
            idempotency_key=str(uuid.uuid5(j.internal_id, 'return'))).exists())
