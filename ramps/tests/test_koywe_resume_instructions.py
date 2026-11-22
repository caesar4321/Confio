"""A reopened top-up still shows how to pay it (GET /orders omits it all)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from ramps import schema
from ramps.koywe_sync import original_pay_instructions

QR = 'iVBORw0KGgoAAAANSUhEUgAAAT8'
CREATED = {'orderId': 'order', 'providedAction': QR, 'providedAddress': 'Banco X\nAlias confio',
           'providedAddressFromProviderDetails': True, 'paymentProvider': {'name': 'QR'},
           'email': 'a@example.com', 'documentNumber': '123', 'amountIn': 500}
POLLED = {'orderId': 'order', '_id': '6b01ece2aae5c71c4963ae51', 'status': 'WAITING', 'amountIn': 500,
          'dates': {'paymentDate': None}}


def order(**fields):
    return SimpleNamespace(**{'direction': 'on_ramp', 'status': 'PENDING', 'country_code': 'BO',
                              'destination': 'cusd_plus', 'metadata': {'provider_payload_created': dict(CREATED)},
                              **fields})


@override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=['CO'])
class OriginalPayInstructionsTests(SimpleTestCase):
    def test_every_rail_gets_its_instructions_back(self):
        for country, action in (('BO', QR), ('BR', '00020126pix'), ('PE', '000201qrpe'),
                                ('AR', 'https://pay.example/ar'), ('MX', 'https://pay.example/mx')):
            row = order(country_code=country,
                        metadata={'provider_payload_created': {**CREATED, 'providedAction': action}})
            found = original_pay_instructions(row, POLLED)
            self.assertEqual(found['providedAction'], action)
            self.assertEqual(found['providedAddress'], CREATED['providedAddress'])

    def test_nothing_else_of_the_create_answer_comes_back(self):
        found = original_pay_instructions(order(), POLLED)
        self.assertEqual(set(found), {'providedAction', 'providedAddress'})

    def test_a_webhook_recovered_order_pays_with_what_koywe_put_in_response(self):
        response = '{"providerName": "PIX-QR", "providerLinkUrl": "00020126pix"}'
        recovered = {'orderId': 'order', 'status': 'WAITING', 'response': response}
        row = order(country_code='BR', metadata={'provider_payload_created': recovered})
        self.assertEqual(original_pay_instructions(row, POLLED)['providedAction'], '00020126pix')
        self.assertEqual(schema._recovered_method_code(row.metadata), 'PIX-QR')
        self.assertEqual(original_pay_instructions(row, {**POLLED, 'response': 'not json'})['providedAction'],
                         '00020126pix')

    def test_a_failed_read_does_not_bring_a_paid_orders_qr_back(self):
        for status, shown in (('PROCESSING', 'PENDING'), ('COMPLETED', 'DELIVERED'), ('FAILED', 'REJECTED')):
            out = schema._not_payable_status(order(status=status), 'order')
            self.assertEqual(out.status, shown)
            self.assertIsNone(out.payment_details['providedAction'])
        self.assertIsNone(schema._not_payable_status(order(), 'order'))  # still payable: the error, as before
        self.assertIsNone(schema._not_payable_status(order(direction='off_ramp', status='FAILED'), 'order'))

    def test_a_qr_rail_without_a_code_gets_no_address_to_draw_as_one(self):
        row = order(metadata={'payment_method_code': 'PIX_QR',
                              'provider_payload_created': {**CREATED, 'providedAction': ''}})
        self.assertEqual(original_pay_instructions(row, POLLED), {})

    def test_never_for_an_order_that_should_not_be_paid(self):
        cases = {
            'withdrawal': (order(direction='off_ramp'), POLLED),
            'closed row': (order(status='FAILED'), POLLED),
            'processing row': (order(status='PROCESSING'), POLLED),
            'rejected now': (order(), {**POLLED, 'status': 'REJECTED'}),
            'received now': (order(), {**POLLED, 'status': 'PAYMENT_RECEIVED'}),
            'delivered now': (order(), {**POLLED, 'status': 'DELIVERED'}),
            'paid': (order(), {**POLLED, 'dates': {'paymentDate': '2026-11-21T19:20:00Z'}}),
            'paid, says Koywe': (order(), {**POLLED, 'status': 'PENDING'}),
            'unknown status': (order(), {**POLLED, 'status': 'EXPIRED'}),
            'no status': (order(), {**POLLED, 'status': ''}),
            'paused country': (order(country_code='CO'), POLLED),
            'another order': (order(), {**POLLED, 'orderId': 'other'}),
            'no stored answer': (order(metadata={}), POLLED),
            'no row': (None, POLLED),
        }
        for name, (row, payload) in cases.items():
            self.assertEqual(original_pay_instructions(row, payload), {}, name)

    def test_what_koywe_still_sends_wins(self):
        self.assertEqual(original_pay_instructions(order(), {**POLLED, 'providedAction': 'fresh'})['providedAction'], 'fresh')

    def status(self, row, payload):
        result = SimpleNamespace(order_id='order', status=payload.get('status'), status_details=None,
                                 next_action_url=None, raw_response=dict(payload))
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True, pk=1)))
        row.metadata['auth_email'] = 'a@example.com'
        with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='BO'), \
                mock.patch.object(schema, 'KoyweClient') as client, \
                mock.patch.object(schema.RampTransaction.objects, 'filter') as find, \
                mock.patch.object(schema, 'sync_koywe_ramp_transaction_from_order'), \
                mock.patch.object(schema, '_ramp_tx_crypto_amount', return_value=None), \
                mock.patch.object(schema, '_stored_koywe_deposit_wei', return_value=None), \
                mock.patch.object(schema, '_stored_confio_preview_wei', return_value=None), \
                mock.patch('ramps.koywe_polygon.polygon', return_value=False):
            client.return_value.get_ramp_order_status.return_value = result
            find.return_value.first.return_value = row
            return schema.Query().resolve_ramp_order_status(info, 'order', country_code='BO')

    def test_reopened_order_shows_the_bank_qr(self):
        out = self.status(order(), POLLED)
        self.assertTrue(out.success)
        self.assertEqual(out.payment_details['providedAction'], QR)
        self.assertIsNone(out.payment_details.get('confioDepositAddress'))  # never read as a funding address
        self.assertIsNone(out.next_action_url)

    def test_reopened_transfer_gets_its_link_back(self):
        link = 'https://pay.example/ar'
        row = order(country_code='AR', metadata={'provider_payload_created': {**CREATED, 'providedAction': link}})
        self.assertEqual(self.status(row, POLLED).next_action_url, link)

    def test_rejected_order_gets_no_qr(self):
        out = self.status(order(), {**POLLED, 'status': 'REJECTED'})
        self.assertIsNone(out.payment_details['providedAction'])

    def test_the_screen_that_created_the_order_lets_go_of_what_it_had(self):
        for status in ('PENDING', 'REJECTED', 'DELIVERED'):
            out = self.status(order(), {**POLLED, 'status': status})
            merged = {**CREATED, **out.payment_details}  # what RampInstructionsScreen does
            self.assertEqual([v for v in merged.values() if isinstance(v, str)], [], status)
            self.assertTrue(out.next_action_url)  # truthy, so the route's old link is not used
            self.assertFalse(out.next_action_url.startswith('http'))

    def test_with_nothing_to_pay_with_there_is_no_text_to_draw_as_a_qr(self):
        for row, status in ((order(), 'PENDING'), (order(), 'REJECTED'), (order(), 'DELIVERED'),
                            (order(country_code='CO'), 'WAITING'), (order(metadata={}), 'WAITING')):
            out = self.status(row, {**POLLED, 'status': status, 'amountOut': '38.05', 'email': 'a@example.com'})
            self.assertEqual({k: v for k, v in out.payment_details.items() if v is not None}, {'amountOut': 38.05}, status)

    def test_a_withdrawal_is_left_alone(self):
        details = {'orderId': 'order', '_id': 'abc', 'depositAddress': '0x1'}
        self.assertIs(schema._with_pay_instructions(order(direction='off_ramp'), {}, details), details)


class CreateAnswerWinsTests(TestCase):
    def test_a_webhook_that_lands_first_does_not_lose_the_instructions(self):
        from django.contrib.auth import get_user_model

        from ramps.koywe_sync import upsert_koywe_ramp_transaction
        from ramps.models import RampTransaction

        user = get_user_model().objects.create_user(
            username='resume1', email='resume1@example.com', password='x', firebase_uid='fb-resume1')
        RampTransaction.objects.create(
            provider='koywe', direction='on_ramp', status='PENDING', actor_user=user, actor_type='user',
            country_code='BO', provider_order_id='order', external_id='ext-resume-1',
            metadata={'provider_payload_created': dict(POLLED)})
        with mock.patch('ramps.signals.send_ramp_notification', create=True):
            upsert_koywe_ramp_transaction(
                actor_user=user, actor_business=None, actor_type='user', actor_display_name='Ana', actor_address='',
                direction='ON_RAMP', country_code='BO', fiat_currency='BOB', payment_method_code='QRI-BO',
                payment_method_display='QRI-BO', order_id='order', external_id='ext-resume-1', amount_in='500',
                amount_out='38.05', next_action_url=None, auth_email='resume1@example.com',
                order_payload=dict(CREATED))
        stored = RampTransaction.objects.get(provider_order_id='order').metadata['provider_payload_created']
        self.assertEqual(stored['providedAction'], QR)
