"""The assistant sees verification results, where a send went, and open futures."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

User = get_user_model()


class VerificationNoteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='vn1', email='vn1@example.com', password='x',
                                             firebase_uid='fb-vn1')
        self.viewer = SimpleNamespace(user=self.user, is_employee=False, account_type='personal')

    def doc(self, status, raw, reason='', **extra):
        from security.models import IdentityVerification
        return IdentityVerification.objects.create(
            user=self.user, status=status, verified_first_name='Ana', verified_last_name='Paz',
            verified_date_of_birth=date(1990, 1, 1), verified_nationality='COL', verified_address='-',
            verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
            document_number=f'N{IdentityVerification.all_documents.count()}', document_issuing_country='COL',
            rejected_reason=reason, risk_factors={'didit': {'raw_status': raw}}, **extra)

    def note(self):
        from .verification_note import verification_note
        return verification_note(self.viewer)

    def test_nothing_without_an_attempt(self):
        self.assertEqual(self.note(), '')

    def test_a_decline_with_the_reason_the_app_shows(self):
        self.doc('rejected', 'Declined', reason='Tu documento está vencido. Usa un documento de identidad vigente.')
        note = self.note()
        self.assertIn('fue rechazado', note)
        self.assertIn('Tu documento está vencido', note)
        self.assertIn('nunca digas que no puedes ver', note)

    def test_a_new_unfinished_attempt_still_tells_the_earlier_decline(self):
        # Declined twice, then a fresh session left at "Not Started" (2026-11-24).
        first = self.doc('rejected', 'Declined')
        type(first).all_documents.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.doc('pending', 'Not Started')
        note = self.note()
        self.assertIn('Empezó una verificación y no la terminó', note)
        self.assertIn('Su intento anterior fue rechazado, sin un motivo concreto', note)
        self.assertIn('documento de identidad nacional o pasaporte', note)

    def test_an_old_decline_is_not_brought_up(self):
        old = self.doc('rejected', 'Declined')
        type(old).all_documents.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        self.doc('pending', 'Not Started')
        self.assertNotIn('anterior', self.note())

    def test_a_step_to_redo(self):
        self.doc('pending', 'Resubmitted')
        self.assertIn('Didit le pide repetir un paso', self.note())

    def test_in_review_and_verified_say_nothing_more(self):
        self.doc('pending', 'In Review')
        self.assertEqual(self.note(), '')
        self.doc('verified', 'Approved', verified_at=timezone.now())
        self.assertEqual(self.note(), '')

    def test_not_for_a_business_or_an_employee(self):
        self.doc('rejected', 'Declined')
        for viewer in (SimpleNamespace(user=self.user, is_employee=False, account_type='business'),
                       SimpleNamespace(user=self.user, is_employee=True, account_type='business')):
            self.viewer = viewer
            self.assertEqual(self.note(), '')


class SendDeliveryTests(SimpleTestCase):
    def delivery(self, rows):
        from .engine import _send_delivery
        manager = mock.Mock()
        manager.filter.return_value.values.return_value = rows
        with mock.patch('users.models_unified.UnifiedTransactionTable.objects', manager):
            return _send_delivery([r['pk'] for r in rows])

    def row(self, pk, **values):
        base = {'pk': pk, 'status': 'CONFIRMED', 'counterparty_user_id': None, 'counterparty_business_id': None,
                'counterparty_type': 'user', 'counterparty_address': '', 'is_invitation': False,
                'invitation_claimed': False, 'invitation_reverted': False}
        return {**base, **values}

    def test_a_confirmed_send_to_an_outside_wallet_arrived_there(self):
        out = self.delivery([self.row(1, counterparty_type='external',
                                     counterparty_address='0x12ab00000000000000000000000000000000cd34')])
        self.assertIn('billetera externa 0x12ab…cd34', out[1]['destino'])
        self.assertIn('no una cuenta Confío', out[1]['destino'])
        self.assertIn('ya llegó', out[1]['estado_envio'])

    def test_to_a_confio_account_and_still_on_its_way(self):
        out = self.delivery([self.row(2, counterparty_user_id=9, status='SUBMITTED')])
        self.assertEqual(out[2]['destino'], 'una cuenta Confío')
        self.assertIn('en camino', out[2]['estado_envio'])

    def test_a_comprar_escrow_leg_is_never_an_outside_wallet(self):
        # marketplace/ledger.py: no counterparty, escrow in to_address only.
        self.assertEqual(self.delivery([self.row(4, counterparty_type='business')]), {})

    def test_an_unclaimed_invitation_waits(self):
        out = self.delivery([self.row(3, is_invitation=True, counterparty_address='0x' + 'a' * 40)])
        self.assertIn('invitación', out[3]['destino'])
        self.assertIn('esperando', out[3]['estado_envio'])

    def test_withdrawals_are_left_to_their_own_tool(self):
        from .engine import DELIVERED_KINDS
        self.assertNotIn('withdrawal', DELIVERED_KINDS)
        self.assertNotIn('donation', DELIVERED_KINDS)
        self.assertNotIn('savings_in', DELIVERED_KINDS)


class FuturesTests(SimpleTestCase):
    viewer = SimpleNamespace(user=SimpleNamespace(pk=1), account=SimpleNamespace(bsc_address='0xABC'),
                             account_type='personal', is_employee=False)

    def position(self, **values):
        base = dict(name='Bitcoin', ticker='BTC', side='short', leverage=3, state='open', put_in_usd=12.0,
                    value_usd=10.3, unrealized_pnl_usd=-1.7, entry_px=90000.0, mark_px=91500.5,
                    liquidation_px=118000.0, funding_usd=-0.04, take_profit_px=None, stop_loss_px=85000.0,
                    protection_known=True, resting_px=None)
        return SimpleNamespace(**{**base, **values})

    def test_reads_open_positions_without_moving_them(self):
        from . import futures
        with mock.patch('cusd_plus.perps_schema.position_rows',
                        return_value=[self.position(), self.position(state='done')]) as rows:
            out = futures.futures_data(self.viewer)
        rows.assert_called_once_with(self.viewer.user, '0xabc', reconcile=False)
        self.assertEqual(len(out['posiciones']), 1)
        pos = out['posiciones'][0]
        self.assertEqual(pos['lado'], 'corto (gana si el precio baja)')
        self.assertEqual(pos['apalancamiento'], '3x')
        self.assertEqual(pos['precio_liquidacion'], 118000.0)
        self.assertEqual(pos['ganancia_no_realizada_usd'], -1.7)
        self.assertEqual(pos['stop_loss'], 85000.0)

    def test_unknown_protection_is_never_a_guess(self):
        from . import futures
        with mock.patch('cusd_plus.perps_schema.position_rows',
                        return_value=[self.position(protection_known=False)]):
            pos = futures.futures_data(self.viewer)['posiciones'][0]
        self.assertEqual(pos['take_profit'], 'desconocido')

    def test_an_unreadable_venue_says_so(self):
        from . import futures
        with mock.patch('cusd_plus.perps_schema.position_rows', return_value=None):
            out = futures.futures_data(self.viewer)
        self.assertFalse(out['disponible'])

    def test_offered_only_to_someone_with_positions(self):
        from .engine import Toolbelt
        belt = Toolbelt.__new__(Toolbelt)
        belt.viewer = self.viewer
        with mock.patch('assistant.futures.offered', return_value=False):
            self.assertIn('error', belt.get_futures())
        belt2 = Toolbelt.__new__(Toolbelt)
        belt2.viewer = self.viewer
        with mock.patch('assistant.futures.offered', return_value=True), \
             mock.patch('assistant.futures.futures_data', return_value={'disponible': True}):
            self.assertEqual(belt2.get_futures(), {'disponible': True})

    @override_settings(PERPS_IOS_ENABLED=False)
    def test_never_on_ios(self):
        from . import futures
        ios = SimpleNamespace(**{**vars(self.viewer), 'request_meta': {'HTTP_X_CONFIO_PLATFORM': 'ios'}})
        with mock.patch('blockchain.models.PerpPosition.objects') as positions:
            self.assertFalse(futures.offered(ios))
        positions.filter.assert_not_called()


class FuturesSpecTests(TestCase):
    def test_the_tool_appears_only_with_a_position(self):
        from zoneinfo import ZoneInfo

        from users.models import Account

        from .engine import Toolbelt, TurnResult, Viewer
        user = User.objects.create_user(username='fs1', email='fs1@example.com', password='x', firebase_uid='fb-fs1')
        account = Account.objects.create(user=user, account_type='personal', account_index=0)
        viewer = Viewer(user=user, account=account, account_type='personal', business_id=None,
                        is_business_owner=False, tz=ZoneInfo('UTC'))
        names = {s['name'] for s in Toolbelt(viewer, TurnResult(reply=''), analyses_left=0).specs()}
        self.assertNotIn('get_futures', names)
        with mock.patch('assistant.futures.offered', return_value=True):
            names = {s['name'] for s in Toolbelt(viewer, TurnResult(reply=''), analyses_left=0).specs()}
        self.assertIn('get_futures', names)
