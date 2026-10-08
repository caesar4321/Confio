from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from sms_verification import twilio_verify
from sms_verification.schema import SMS_SEND_GENERIC, sms_send_error_message


@override_settings(TWILIO_ACCOUNT_SID='AC', TWILIO_AUTH_TOKEN='t', TWILIO_VERIFY_SERVICE_SID='VA')
class SmsSendErrorTests(SimpleTestCase):
    """A refused SMS must say why in Spanish and point to Telegram, never the
    old English "Failed to send SMS" (a Bolivian prefix blocked by Twilio's
    fraud guard, code 60410, showed exactly that on 2026-10-08)."""

    def _post(self, status, payload):
        return SimpleNamespace(status_code=status, text=str(payload), json=lambda: payload)

    def test_twilio_error_code_is_kept(self):
        blocked = {'code': 60410, 'message': '59177612 prefix is blocked for the SMS channel', 'status': 403}
        with patch('sms_verification.twilio_verify.requests.post', return_value=self._post(403, blocked)):
            with self.assertRaises(twilio_verify.TwilioVerifyError) as raised:
                twilio_verify.send_verification_sms('+59177612254')
        self.assertEqual(raised.exception.code, 60410)

    def test_unreadable_error_body_has_no_code(self):
        def broken():
            raise ValueError('not json')
        resp = SimpleNamespace(status_code=500, text='oops', json=broken)
        with patch('sms_verification.twilio_verify.requests.post', return_value=resp):
            with self.assertRaises(twilio_verify.TwilioVerifyError) as raised:
                twilio_verify.send_verification_sms('+59177612254')
        self.assertIsNone(raised.exception.code)

    def test_messages_are_spanish_and_point_to_telegram(self):
        blocked = sms_send_error_message(60410)
        self.assertIn('bloqueó temporalmente', blocked)
        self.assertIn('Telegram', blocked)
        self.assertEqual(sms_send_error_message(None), SMS_SEND_GENERIC)
        self.assertEqual(sms_send_error_message(99999), SMS_SEND_GENERIC)
        for code in (60410, 60203, 60605, 60205, 60200, None):
            self.assertNotIn('Failed', sms_send_error_message(code))
            self.assertIn('Telegram', sms_send_error_message(code))
        # 60200 ("invalid parameter") can be our own request: generic, never "your number".
        self.assertEqual(sms_send_error_message(60200), SMS_SEND_GENERIC)

    def test_string_and_odd_error_bodies(self):
        as_string = {'code': '60410', 'message': 'blocked'}
        with patch('sms_verification.twilio_verify.requests.post', return_value=self._post(403, as_string)):
            with self.assertRaises(twilio_verify.TwilioVerifyError) as raised:
                twilio_verify.send_verification_sms('+59177612254')
        self.assertEqual(raised.exception.code, 60410)
        with patch('sms_verification.twilio_verify.requests.post', return_value=self._post(500, ['not', 'a', 'dict'])):
            with self.assertRaises(twilio_verify.TwilioVerifyError) as raised:
                twilio_verify.send_verification_sms('+59177612254')
        self.assertIsNone(raised.exception.code)



class InitiateSmsMutationTests(TestCase):
    """The mutation returns the coded Spanish message end to end."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user(username='sms1', firebase_uid='uid-sms1')

    def _initiate(self, error):
        from sms_verification.schema import InitiateSMSVerification
        info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}, headers={}))
        with patch('security.integrity_service.app_check_enforcement_enabled', return_value=False), \
                patch('sms_verification.schema.lookup_phone_with_line_type',
                      return_value=(True, '+59177612254', 'BO', 'mobile')), \
                patch('sms_verification.schema.send_verification_sms', side_effect=error):
            return InitiateSMSVerification.mutate(None, info, phone_number='77612254', country_code='BO')

    def test_a_blocked_prefix_says_so_and_points_to_telegram(self):
        result = self._initiate(twilio_verify.TwilioVerifyError('403', code=60410))
        self.assertFalse(result.success)
        self.assertEqual(result.error, sms_send_error_message(60410))

    def test_an_unexpected_failure_gets_the_generic_spanish_message(self):
        result = self._initiate(RuntimeError('network'))
        self.assertFalse(result.success)
        self.assertEqual(result.error, SMS_SEND_GENERIC)
