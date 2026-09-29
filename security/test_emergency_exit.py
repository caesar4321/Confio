import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct

from security import emergency_exit as ee
from security.models import UserBan
from users.models import Account


def _sign(message, key):
    return EthAccount.sign_message(encode_defunct(text=message), private_key=key).signature.hex()


class BannedEmergencyExitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.wallet = EthAccount.create()
        self.address = self.wallet.address.lower()
        self.user = get_user_model().objects.create(
            username='exit-user', email='exit@example.com', firebase_uid='exit-user-uid')
        Account.objects.create(user=self.user, account_type='personal', account_index=0,
                               bsc_address=self.wallet.address)
        app_check = mock.patch(
            'security.integrity_service.app_check_service.verify_and_record',
            return_value={'success': True})
        self.app_check = app_check.start()
        self.addCleanup(app_check.stop)

    def _open(self, key=None, nonce=None):
        issued = ee.issue_challenge(self.address)
        return ee.open_session(
            self.address, nonce or issued['nonce'],
            _sign(issued['message'], key or self.wallet.key), 'app-check-token')

    def _ban(self):
        UserBan.objects.create(user=self.user, ban_type='permanent', reason='ring')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_banned_account_must_show_its_face(self):
        self._ban()
        session = self._open()
        self.assertEqual((session['banned'], session['face_required']), (True, True))
        self.assertTrue(session['token'])
        self.app_check.assert_called_with(
            user=self.user, token='app-check-token', action=ee.APP_CHECK_ACTION, should_enforce=True)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_a_faked_ban_does_not_route_a_healthy_account(self):
        session = self._open()
        self.assertEqual((session['banned'], session['face_required'], session['token']), (False, False, ''))

    def test_no_face_while_enforcement_is_off(self):
        self._ban()
        session = self._open()
        self.assertEqual((session['banned'], session['face_required']), (True, False))

    def test_only_the_accounts_own_key_opens_a_session(self):
        with self.assertRaises(ee.EmergencyExitError):
            self._open(key=EthAccount.create().key)

    def test_a_challenge_is_single_use(self):
        issued = ee.issue_challenge(self.address)
        signature = _sign(issued['message'], self.wallet.key)
        ee.open_session(self.address, issued['nonce'], signature, 'app-check-token')
        with self.assertRaises(ee.EmergencyExitError):
            ee.open_session(self.address, issued['nonce'], signature, 'app-check-token')

    def test_an_unattested_device_is_refused(self):
        self.app_check.return_value = {'success': False}
        with self.assertRaises(ee.EmergencyExitError) as ctx:
            self._open()
        self.assertEqual(str(ctx.exception), ee.DEVICE_MESSAGE)

    def test_challenges_are_rate_limited(self):
        for _ in range(ee.MAX_CHALLENGES_PER_HOUR):
            ee.issue_challenge(self.address)
        with self.assertRaises(ee.EmergencyExitError):
            ee.issue_challenge(self.address)

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_face_runs_for_the_session_user(self):
        self._ban()
        token = self._open()['token']
        with mock.patch.object(ee, 'start_face_check', return_value={'session_id': 's-1'}) as start, \
                mock.patch.object(ee, 'complete_face_check', return_value=True) as complete:
            self.assertEqual(ee.start_face(token, 'app-check-token'), {'session_id': 's-1'})
            self.assertTrue(ee.complete_face(token, 's-1'))
        start.assert_called_once_with(self.user, 'emergency_exit')
        complete.assert_called_once_with(self.user, 's-1')

    def test_face_needs_a_live_session(self):
        with self.assertRaises(ee.EmergencyExitError):
            ee.start_face('not-a-token', 'app-check-token')

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_endpoints_need_no_jwt(self):
        self._ban()
        issued = self.client.post('/api/emergency-exit/challenge/', json.dumps({'address': self.address}),
                                  content_type='application/json').json()
        response = self.client.post('/api/emergency-exit/session/', json.dumps({
            'address': self.address, 'nonce': issued['nonce'],
            'signature': _sign(issued['message'], self.wallet.key),
        }), content_type='application/json', HTTP_X_FIREBASE_APPCHECK='app-check-token')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['faceRequired'], True)
