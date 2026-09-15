import base64
import hashlib
import json
import time
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch
from django.core import signing
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from payment_accounts import breb_location as gate


@override_settings(BREB_LOCATION_ENABLED=True, BREB_PLAY_CERTIFICATE_DIGESTS=['release'],
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BrebLocationTests(SimpleTestCase):
    def setUp(self):
        configuration = patch.object(gate, 'configured', return_value=True)
        configuration.start()
        self.addCleanup(configuration.stop)
        # The compliance record is a DB write; its own tests are below.
        recorder = patch.object(gate, '_record')
        self.record = recorder.start()
        self.addCleanup(recorder.stop)
        cache.clear()
        self.owner = SimpleNamespace(pk=34)
        self.challenge = signing.dumps({'owner': 34, 'random': 'test'}, salt='breb-application')
        self.location = json.dumps(dict(latitude=4.711, longitude=-74.072, accuracy=10,
                                       timestamp=time.time()*1000, mocked=False))

    def verdict(self, location=None):
        nonce = base64.urlsafe_b64encode(hashlib.sha256((self.challenge+'.'+(location or self.location)).encode()).digest()).decode().rstrip('=')
        return {'requestDetails': {'requestHash': nonce, 'requestPackageName': 'com.Confio.Confio', 'timestampMillis': time.time()*1000},
                'appIntegrity': {'appRecognitionVerdict': 'PLAY_RECOGNIZED', 'packageName': 'com.Confio.Confio', 'certificateSha256Digest': ['release']},
                'deviceIntegrity': {'deviceRecognitionVerdict': ['MEETS_DEVICE_INTEGRITY']}}

    def verify(self, location=None):
        return gate.verify(self.owner, {}, self.challenge, location or self.location, 'token')

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_valid_and_replay(self, decode, country):
        decode.return_value = self.verdict()
        gate.require_permit(self.verify(), self.owner)
        with self.assertRaises(gate.LocationError): self.verify()
        decode.assert_called_once()  # known replay never spends another decode

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_every_verification_is_recorded(self, decode, country):
        decode.return_value = self.verdict()
        self.verify()
        _, _, evidence, passed = self.record.call_args.args[:4]
        self.assertTrue(passed)
        self.assertTrue(self.record.call_args.kwargs.get('strict'))
        self.assertEqual((evidence['latitude'], evidence['longitude'], evidence['accuracy']), (4.711, -74.072, 10))
        cache.clear()
        data = json.loads(self.location); data['mocked'] = True
        with self.assertRaises(gate.LocationError): self.verify(json.dumps(data))
        self.assertFalse(self.record.call_args.args[3])
        self.assertEqual(self.record.call_args.args[2]['latitude'], 4.711)

    @patch.object(gate, 'country_for_request', return_value='VE')
    def test_ip_refusal_keeps_the_submitted_reading(self, country):
        with self.assertRaises(gate.LocationError): self.verify()
        _, _, evidence, passed, reason = self.record.call_args.args[:5]
        self.assertFalse(passed)
        self.assertEqual(reason, 'ip_not_allowed')
        self.assertEqual((evidence['latitude'], evidence['longitude'], evidence['accuracy']), (4.711, -74.072, 10))

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_no_pass_without_its_record(self, decode, country):
        decode.return_value = self.verdict()
        def record(*args, strict=False, **kwargs):
            if strict:
                raise RuntimeError('storage down')
        self.record.side_effect = record
        with self.assertRaises(gate.LocationError): self.verify()

    @patch.object(gate, 'country_for_request', return_value='VE')
    @patch.object(gate, 'decode_token')
    def test_venezuela_denied_before_google(self, decode, country):
        with self.assertRaises(gate.LocationError): self.verify()
        decode.assert_not_called()

    @patch.object(gate, 'country_for_request', return_value=None)
    def test_unknown_ip_does_not_pass(self, country):
        self.assertFalse(gate.ip_allowed({}))

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_bad_location(self, decode, country):
        for changes in [{'mocked': True}, {'mocked': 'false'}, {'accuracy': 1000},
                        {'latitude': 10.48, 'longitude': -66.9}, {'latitude': float('nan')},
                        {'timestamp': (time.time()-200)*1000}]:
            data = json.loads(self.location); data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(gate.LocationError):
                self.verify(json.dumps(data))
        decode.assert_not_called()

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_integrity_binding_and_release_certificate(self, decode, country):
        for section, key, value in [('requestDetails', 'requestHash', 'wrong'),
                                    ('appIntegrity', 'certificateSha256Digest', ['debug']),
                                    ('deviceIntegrity', 'deviceRecognitionVerdict', ['MEETS_BASIC_INTEGRITY'])]:
            cache.clear()  # each failed decode now consumes its challenge
            verdict = self.verdict(); verdict[section][key] = value; decode.return_value = verdict
            with self.subTest(key=key), self.assertRaises(gate.LocationError): self.verify()

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_classic_nonce_cannot_replace_standard_request_hash(self, decode, country):
        verdict = self.verdict()
        verdict['requestDetails']['nonce'] = verdict['requestDetails'].pop('requestHash')
        decode.return_value = verdict
        with self.assertRaises(gate.LocationError): self.verify()

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    @patch('payment_accounts.apple_attest.verify')
    def test_ios_uses_signed_platform_and_exact_payload(self, apple_verify, decode, country):
        self.challenge = signing.dumps({'owner': 34, 'platform': 'ios'}, salt='breb-application')
        gate.require_permit(self.verify(), self.owner)
        apple_verify.assert_called_once_with(self.owner, 'token', hashlib.sha256((self.challenge+'.'+self.location).encode()).digest())
        decode.assert_not_called()
        with self.assertRaises(gate.LocationError): self.verify()
        apple_verify.assert_called_once()

    def test_bre_b_works_anywhere_but_venezuela(self):
        # Bogotá, Cúcuta, Villa del Rosario, Cartagena, Quito and Madrid are
        # fine; Caracas, San Antonio del Táchira and Ureña are in Venezuela.
        for lat, lon, allowed in [(4.711, -74.072, True), (7.8939, -72.5078, True), (7.8336, -72.4742, True),
                                  (10.4236, -75.5510, True), (-0.1807, -78.4678, True), (40.4168, -3.7038, True),
                                  (10.48, -66.9, False), (7.8145, -72.4431, False), (7.9167, -72.4417, False)]:
            with self.subTest(lat=lat, lon=lon):
                self.assertEqual(gate.outside_venezuela(lat, lon, 60), allowed)
        # A reading whose uncertainty reaches into Venezuela asks again.
        self.assertFalse(gate.outside_venezuela(7.8145, -72.4480, 100))

    def test_location_pass_lifecycle(self):
        from payment_accounts.services import PaymentAccountError
        with self.assertRaises(PaymentAccountError): gate.require_location_pass(self.owner)
        self.assertGreater(gate.grant_pass(self.owner), time.time())
        gate.require_location_pass(self.owner)
        with self.assertRaises(PaymentAccountError): gate.require_location_pass(SimpleNamespace(pk=35))
        cache.set(f'breb-location-pass:{self.owner.pk}', time.time() - 1)
        with self.assertRaises(PaymentAccountError): gate.require_location_pass(self.owner)
        gate.grant_pass(self.owner)
        with patch.object(gate, 'configured', return_value=False), self.assertRaises(PaymentAccountError):
            gate.require_location_pass(self.owner)  # an unconfigured gate never passes

    def test_pass_cannot_override_current_venezuela_ip(self):
        from payment_accounts.services import PaymentAccountError
        gate.grant_pass(self.owner)
        for country in ('VE', None):
            with patch.object(gate, 'country_for_request', return_value=country), self.assertRaises(PaymentAccountError):
                gate.require_for_country(self.owner, 'COL', {})
        with patch.object(gate, 'country_for_request', return_value='CO'):
            gate.require_for_country(self.owner, 'COL', {})

    def test_only_colombia_needs_the_pass(self):
        from payment_accounts.services import PaymentAccountError
        for country in ('MEX', 'BR', 'ARG', ''):
            gate.require_for_country(self.owner, country)
        for country in ('COL', 'co'):
            with self.subTest(country=country), self.assertRaises(PaymentAccountError):
                gate.require_for_country(self.owner, country)

    def test_screen_verification_grants_the_pass(self):
        from payment_accounts import breb_location_schema as schema
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        with patch('payment_accounts.schema._active_account', return_value=self.owner), \
                patch.object(gate, 'verify', return_value=gate.ApplicationPermit(34, time.time() + 120)):
            result = schema.VerifyBrebLocation.mutate(None, info, self.challenge, self.location, 'token')
        self.assertTrue(result.success)
        gate.require_location_pass(self.owner)

    def test_a_cobre_journey_needs_the_pass(self):
        from payment_accounts import cobre_journey_schema as schema
        info = SimpleNamespace(context=SimpleNamespace(META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        with patch('payment_accounts.schema._active_account', return_value=self.owner), \
                patch.object(schema, 'create_journey') as create:
            result = schema.CreateCobreJourney.mutate(
                None, info, local_account_id='l', crypto_account_id='c', copco_account_id='p',
                direction='to_bank', request_id='r', minimum_fx_output='1')
        self.assertFalse(result.success)
        self.assertIn('Verifica tu ubicación', result.errors[0])
        create.assert_not_called()

    def test_permit_owner_and_expiry(self):
        from payment_accounts.services import PaymentAccountError
        for permit in [None, gate.ApplicationPermit(9, time.time()+120), gate.ApplicationPermit(34, 0)]:
            with self.assertRaises(PaymentAccountError): gate.require_permit(permit, self.owner)

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_challenge_owner_expiration_and_malformed_input(self, decode, country):
        original = self.challenge
        for token in [signing.dumps({'owner': 99}, salt='breb-application'), 'invalid', 'x'*2049]:
            self.challenge = token
            with self.assertRaises(gate.LocationError): self.verify()
        with patch('django.core.signing.time.time', return_value=time.time()-200):
            self.challenge = signing.dumps({'owner': 34}, salt='breb-application')
        with self.assertRaises(gate.LocationError): self.verify()
        self.challenge = original
        decode.assert_not_called()

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token', side_effect=RuntimeError('upstream detail'))
    def test_decoder_failure_is_closed_and_sanitized(self, decode, country):
        with self.assertRaises(gate.LocationError) as caught: self.verify()
        self.assertNotIn('upstream detail', str(caught.exception))
        with self.assertRaises(gate.LocationError): self.verify()
        decode.assert_called_once()

    @patch.object(gate, 'country_for_request', return_value='CO')
    @patch.object(gate, 'decode_token')
    def test_concurrent_attempt_is_reserved_before_decode(self, decode, country):
        def during_decode(token):
            with self.assertRaises(gate.LocationError): self.verify()
            return self.verdict()
        decode.side_effect = during_decode
        gate.require_permit(self.verify(), self.owner)
        decode.assert_called_once()

    @patch.object(gate, 'country_for_request', return_value='CO')
    def test_challenge_rate_limit(self, country):
        gate.challenge(self.owner, {})
        with self.assertRaises(gate.LocationError): gate.challenge(self.owner, {})

    def test_provisioning_cannot_bypass_gate(self):
        from payment_accounts.services import provision_payment_account, create_funding_instruction, PaymentAccountError
        with self.assertRaises(PaymentAccountError):
            provision_payment_account(confio_account=self.owner, provider='cobre', identity=None,
                                      country='COL', asset='COP', ownership_structure='omnibus_subledger')
        account = SimpleNamespace(provider='cobre', provider_profile=SimpleNamespace(confio_account=self.owner))
        with self.assertRaises(PaymentAccountError):
            create_funding_instruction(financial_account=account, kind='breb_key')


    def test_a_bre_b_key_shows_only_with_a_current_pass(self):
        from payment_accounts.schema import FundingInstructionType
        colombia = SimpleNamespace(context=SimpleNamespace(META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        venezuela = SimpleNamespace(context=SimpleNamespace(META={'HTTP_CF_IPCOUNTRY': 'VE'}))
        account = SimpleNamespace(provider_profile=SimpleNamespace(confio_account=self.owner))
        key = SimpleNamespace(kind='breb_key', display_value='@ana', holder_display_name='Ana', financial_account=account)
        clabe = SimpleNamespace(kind='clabe', display_value='0123', holder_display_name='Ana', financial_account=account)
        with patch('payment_accounts.activation.usable', return_value=True):
            self.assertEqual(FundingInstructionType.resolve_display_value(key, colombia), '')
            self.assertEqual(FundingInstructionType.resolve_holder_display_name(key, colombia), '')
            self.assertEqual(FundingInstructionType.resolve_display_value(clabe, colombia), '0123')  # not Bre-B
            gate.grant_pass(self.owner)
            self.assertEqual(FundingInstructionType.resolve_display_value(key, colombia), '@ana')
            self.assertEqual(FundingInstructionType.resolve_holder_display_name(key, colombia), 'Ana')
            self.assertEqual(FundingInstructionType.resolve_display_value(key, venezuela), '')

    def test_the_receive_account_hides_a_bre_b_key_without_a_pass(self):
        from payment_accounts import local_money_schema as schema
        method = schema.local_money.Method('co_breb_receive', 'receive', 'COL', 'CO', 'COP', 'Bre-B', 'Key',
                                           instruction_kind='breb_key')
        view = dict(method=method, status='active', local=None, crypto=None, value='@ana', holder_name='Ana',
                    institution='', receive_same_name='', receive_third_party='')
        info = SimpleNamespace(context=SimpleNamespace(META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        with patch.object(schema, '_owner', return_value=self.owner), \
                patch.object(schema.local_money, 'receive_account', return_value=view):
            hidden = schema.LocalMoneyQuery.resolve_local_receive_account(None, info, 'co_breb_receive')
            gate.grant_pass(self.owner)
            shown = schema.LocalMoneyQuery.resolve_local_receive_account(None, info, 'co_breb_receive')
        self.assertEqual((hidden.status, hidden.value, hidden.holder_name), ('active', '', ''))
        self.assertEqual((shown.value, shown.holder_name), ('@ana', 'Ana'))


class BrebConfigurationTests(SimpleTestCase):
    @override_settings(BREB_LOCATION_ENABLED=True, BREB_IOS_APP_ATTEST_ENABLED=True, BREB_IOS_APP_ID='ABCDEFGHIJ.com.Confio.Confio',
                       BREB_PLAY_CLOUD_PROJECT_NUMBER='', BREB_PLAY_CERTIFICATE_DIGESTS=[],
                       CACHES={'default': {'BACKEND': 'django_redis.cache.RedisCache'}})
    def test_ios_independent_of_android_configuration(self):
        self.assertTrue(gate.configured('ios'))
        self.assertFalse(gate.configured('android'))
        with override_settings(BREB_IOS_APP_ATTEST_ENABLED=False): self.assertFalse(gate.configured('ios'))

    @override_settings(BREB_LOCATION_ENABLED=True, COBRE_PAYMENT_ACCOUNTS_ENABLED=False,
                       BREB_PLAY_CERTIFICATE_DIGESTS=['release'], BREB_PLAY_CLOUD_PROJECT_NUMBER='123456789')
    def test_requires_shared_cache_and_its_flag_not_cobre(self):
        with override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}):
            self.assertFalse(gate.configured())
        with override_settings(CACHES={'default': {'BACKEND': 'django_redis.cache.RedisCache'}}):
            self.assertTrue(gate.configured())
            # Infinia runs Bre-B while Cobre is off: the gate must work without it.
            with override_settings(COBRE_PAYMENT_ACCOUNTS_ENABLED=True): self.assertTrue(gate.configured())
            with override_settings(BREB_LOCATION_ENABLED=False): self.assertFalse(gate.configured())
            with override_settings(BREB_PLAY_CERTIFICATE_DIGESTS=[]): self.assertFalse(gate.configured())
            for project in ('', 'not-a-number', '0', str(2**63)):
                with override_settings(BREB_PLAY_CLOUD_PROJECT_NUMBER=project): self.assertFalse(gate.configured())


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BrebDecodeTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch('google.auth.default', return_value=(object(), 'project'))
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_quota_exhaustion_is_sanitized_and_not_retried(self, session, credentials):
        response = session.return_value.__enter__.return_value.post.return_value
        response.status_code = 429
        response.raise_for_status.side_effect = RuntimeError('sensitive response')
        with self.assertLogs(gate.logger, level='INFO') as logs, self.assertRaisesRegex(gate.LocationError, 'temporalmente'):
            gate.decode_token('private-token')
        self.assertIn('breb_integrity_quota_exhausted', ' '.join(logs.output))
        self.assertNotIn('private-token', ' '.join(logs.output))
        self.assertNotIn('sensitive response', ' '.join(logs.output))
        session.return_value.__enter__.return_value.post.assert_called_once()

    @patch('google.auth.default', return_value=(object(), 'project'))
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_usage_warning_and_success(self, session, credentials):
        key = f"breb-integrity-decodes:{time.strftime('%Y-%m-%d', time.gmtime())}"
        cache.set(key, 7999)
        response = session.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {'tokenPayloadExternal': {'verified': True}}
        with self.assertLogs(gate.logger, level='WARNING') as logs:
            self.assertEqual(gate.decode_token('token'), {'verified': True})
        self.assertIn('breb_integrity_quota_threshold', ' '.join(logs.output))
        self.assertEqual(cache.get(key), 8000)


class BrebListTests(SimpleTestCase):
    def resolve(self, country, enabled=True, eligible=True):
        from payment_accounts import local_money_schema as schema
        owner = SimpleNamespace(pk=34, account_type='personal')
        method = schema.local_money.Method('co_breb_receive', 'receive', 'COL', 'CO', 'COP', 'Bre-B', 'Key')
        rows = [dict(method=method, status='live', reason='', account_status='none', requirement=None)]
        with patch.object(schema, '_owner', return_value=owner), patch.object(schema, '_identity', return_value=object()), \
             patch.object(schema.local_money, 'methods', return_value=rows), \
             patch.object(gate, 'country_for_request', return_value=country), \
             patch.object(gate, 'configured', return_value=enabled), \
             patch('payment_accounts.eligibility.context_from_identity', return_value=object()), \
             patch('payment_accounts.eligibility.evaluate_active_policy', return_value=SimpleNamespace(allowed=eligible)), \
             override_settings(COBRE_PAYMENT_ACCOUNTS_ENABLED=True):
            return schema.LocalMoneyQuery.resolve_local_money_methods(None, SimpleNamespace(context=SimpleNamespace(META={})), 'receive')

    def test_the_list_never_depends_on_the_ip(self):
        # Bre-B is listed wherever the person is; its application checks the
        # location as a requirement and every operation checks it again.
        for country in ['VE', None, 'CO']:
            with self.subTest(country=country):
                self.assertEqual([(r.id, r.status) for r in self.resolve(country)], [('cobre_co_breb_receive', 'live')])
                self.assertEqual([(r.id, r.status) for r in self.resolve(country, enabled=False)],
                                 [('co_breb_receive', 'live')])

    def test_disabled_or_ineligible_does_not_offer_cobre(self):
        self.assertEqual([r.id for r in self.resolve('CO', enabled=False)], ['co_breb_receive'])
        self.assertEqual([r.id for r in self.resolve('CO', eligible=False)], ['co_breb_receive'])


class BrebDevIpCountryTests(SimpleTestCase):
    """The local-development country for a LAN IP never reaches a public IP or DEBUG=False."""
    def allowed(self, ip):
        with patch.object(gate, 'country_for_request', return_value=None):
            return gate.ip_allowed({'REMOTE_ADDR': ip})

    @override_settings(DEBUG=True, BREB_DEV_IP_COUNTRY='CO')
    def test_private_ip_in_debug_uses_the_dev_country(self):
        self.assertTrue(self.allowed('192.168.1.20'))
        with override_settings(BREB_DEV_IP_COUNTRY='VE'):
            self.assertFalse(self.allowed('192.168.1.20'))

    @override_settings(DEBUG=True, BREB_DEV_IP_COUNTRY='CO')
    def test_public_ip_never_uses_the_dev_country(self):
        self.assertFalse(self.allowed('8.8.8.8'))

    @override_settings(DEBUG=False, BREB_DEV_IP_COUNTRY='CO')
    def test_ignored_without_debug(self):
        self.assertFalse(self.allowed('192.168.1.20'))

    @override_settings(DEBUG=True, BREB_DEV_IP_COUNTRY='')
    def test_unset_keeps_unknown_geography_refused(self):
        self.assertFalse(self.allowed('192.168.1.20'))


class BrebRecordTests(SimpleTestCase):
    """What the compliance record stores, and that a refusal's record never raises."""
    evidence = {'platform': 'ios', 'latitude': 4.7, 'longitude': -74.0, 'accuracy': 12.0, 'timestamp': 1_700_000_000_000}

    def test_fields(self):
        with patch('payment_accounts.models.BrebLocationCheck.objects.create') as create, \
             patch.object(gate, 'country_for_request', return_value='CO'):
            gate._record(SimpleNamespace(pk=34), {'REMOTE_ADDR': '181.49.1.2'}, self.evidence, True, strict=True)
        fields = create.call_args.kwargs
        self.assertEqual((fields['confio_account_id'], fields['platform'], fields['passed']), (34, 'ios', True))
        self.assertEqual((fields['ip_address'], fields['ip_country']), ('181.49.1.2', 'CO'))
        self.assertEqual((fields['latitude'], fields['longitude'], fields['accuracy_m']), (4.7, -74.0, 12.0))
        self.assertEqual(fields['reading_at'].timestamp(), 1_700_000_000)

    def test_submitted_reading_is_bounded(self):
        self.assertEqual(gate._submitted('not-signed', 'x' * 3000), {})
        self.assertEqual(gate._submitted('not-signed', '[1, 2]'), {})
        self.assertEqual(gate._submitted('not-signed', '{"latitude": 95, "longitude": -74.0, "timestamp": -5}'),
                         {'longitude': -74.0})

    def test_invalid_signed_reading_still_records_bounded_refusal(self):
        challenge = signing.dumps({'owner': 34, 'platform': 'android'}, salt='breb-application')
        location = json.dumps({'latitude': 95, 'longitude': -74, 'accuracy': 10,
                               'timestamp': 1e100, 'mocked': False})
        with patch.object(gate, 'configured', return_value=True), \
             patch.object(gate, 'country_for_request', return_value='CO'), \
             patch('payment_accounts.models.BrebLocationCheck.objects.create') as create, \
             self.assertRaises(gate.LocationError):
            gate.verify(SimpleNamespace(pk=34), {}, challenge, location, 'token')
        create.assert_called_once()
        self.assertFalse(create.call_args.kwargs['passed'])
        self.assertIsNone(create.call_args.kwargs['latitude'])
        self.assertIsNone(create.call_args.kwargs['reading_at'])
        self.assertEqual(create.call_args.kwargs['longitude'], -74)

    def test_failed_record_never_logs_its_row(self):
        with patch('payment_accounts.models.BrebLocationCheck.objects.create',
                   side_effect=RuntimeError('failing row (4.7, -74.0, 181.49.1.2)')), \
             patch.object(gate, 'country_for_request', return_value='CO'), \
             self.assertLogs('payment_accounts.breb_location', 'WARNING') as logs:
            gate._record(SimpleNamespace(pk=34), {}, self.evidence, False, 'ip_not_allowed')
        output = '\n'.join(logs.output)
        self.assertIn('RuntimeError', output)
        self.assertNotIn('74.0', output)
        self.assertNotIn('181.49', output)

    def test_refusal_record_is_best_effort_and_pass_record_is_strict(self):
        with patch('payment_accounts.models.BrebLocationCheck.objects.create', side_effect=RuntimeError('down')), \
             patch.object(gate, 'country_for_request', return_value='CO'):
            gate._record(SimpleNamespace(pk=34), {}, {}, False, 'ip_not_allowed')
            with self.assertRaises(RuntimeError):
                gate._record(SimpleNamespace(pk=34), {}, self.evidence, True, strict=True)


class BrebPerimeterEdgeTests(SimpleTestCase):
    """Readings whose accuracy perimeter crosses the antimeridian or a pole."""
    def test_antimeridian_readings_are_outside_venezuela(self):
        for lon in (179.9999, -179.9999):
            with self.subTest(lon=lon):
                self.assertTrue(gate.outside_venezuela(-16.8, lon, 10))

    def test_near_pole_reading_does_not_fail(self):
        self.assertTrue(gate.outside_venezuela(89.9999, 0.0, 100))
        self.assertTrue(gate.outside_venezuela(-89.9999, 0.0, 100))

    def test_caracas_is_still_refused(self):
        self.assertFalse(gate.outside_venezuela(10.48, -66.9, 10))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BrebGenericMutationTests(SimpleTestCase):
    """The generic payout/transfer mutations cannot move Bre-B money without a
    current location pass from an allowed IP."""
    def setUp(self):
        cache.clear()
        self.owner = SimpleNamespace(pk=34)

    def account(self, provider='cobre', country='COL'):
        return SimpleNamespace(internal_id=uuid4(), provider_profile=SimpleNamespace(provider=provider), country=country)

    def payout(self, source, ip='CO', passed=False):
        from payment_accounts import schema
        with patch.object(schema, '_active_account', return_value=self.owner), \
             patch.object(schema.FinancialAccount.objects, 'select_related') as accounts, \
             patch.object(schema.PayoutDestination.objects, 'filter') as destinations, \
             patch.object(schema, 'create_and_submit_payout', return_value=None) as submit, \
             patch.object(gate, 'country_for_request', return_value=ip), \
             patch.object(gate, 'configured', return_value=True):
            accounts.return_value.filter.return_value.first.return_value = source
            destinations.return_value.first.return_value = object()
            if passed:
                gate.grant_pass(self.owner)
            result = schema.CreatePaymentPayout.mutate(
                None, SimpleNamespace(context=SimpleNamespace(META={})), uuid4(), uuid4(), Decimal('1'), uuid4())
        return result, submit

    def test_cobre_payout_needs_a_pass(self):
        result, submit = self.payout(self.account())
        self.assertFalse(result.success)
        # The exact refusal the app answers with one location check and retry.
        self.assertEqual(result.errors, ['Verifica tu ubicación para usar Bre-B.'])
        submit.assert_not_called()

    def test_cobre_payout_refused_from_venezuela_even_with_a_pass(self):
        result, submit = self.payout(self.account(), ip='VE', passed=True)
        self.assertFalse(result.success)
        submit.assert_not_called()

    def test_cobre_payout_with_a_pass_from_an_allowed_ip(self):
        result, submit = self.payout(self.account(), passed=True)
        self.assertTrue(result.success)
        submit.assert_called_once()

    def test_colombian_account_of_any_provider_is_gated(self):
        result, submit = self.payout(self.account(provider='infinia', country='COL'))
        self.assertFalse(result.success)
        submit.assert_not_called()

    def test_other_countries_are_not_location_gated(self):
        result, submit = self.payout(self.account(provider='infinia', country='MEX'))
        self.assertTrue(result.success)
        submit.assert_called_once()

    def provision(self, country):
        from payment_accounts import schema
        with patch.object(schema, '_active_account', return_value=self.owner), \
             patch.object(schema, '_verified_identity', return_value=object()), \
             patch('payment_accounts.activation.require_paid'), \
             patch.object(schema, 'provision_payment_account', return_value=(None, None)) as provision, \
             patch.object(gate, 'country_for_request', return_value='CO'), \
             patch.object(gate, 'configured', return_value=True), \
             override_settings(INFINIA_KYC_MODE='SELF_DECLARED'):
            result = schema.ProvisionPaymentAccount.mutate(
                None, SimpleNamespace(context=SimpleNamespace(META={})), 'infinia', country, 'COP', True)
        return result, provision

    def test_opening_a_colombian_account_needs_a_pass(self):
        result, provision = self.provision('COL')
        self.assertEqual(result.errors, ['Verifica tu ubicación para usar Bre-B.'])
        provision.assert_not_called()
        result, provision = self.provision('MEX')
        self.assertTrue(result.success)
        provision.assert_called_once()

    def test_a_colombian_receiving_instruction_needs_a_pass(self):
        from payment_accounts import schema
        with patch.object(schema, '_active_account', return_value=self.owner), \
             patch.object(schema.FinancialAccount.objects, 'select_related') as accounts, \
             patch.object(schema, 'create_funding_instruction') as create, \
             patch.object(gate, 'country_for_request', return_value='CO'), \
             patch.object(gate, 'configured', return_value=True):
            accounts.return_value.filter.return_value.first.return_value = self.account(provider='infinia')
            result = schema.CreateReceivingInstruction.mutate(
                None, SimpleNamespace(context=SimpleNamespace(META={})), uuid4(), 'breb_key')
        self.assertFalse(result.success)
        create.assert_not_called()

    def test_cobre_transfer_needs_a_pass(self):
        from payment_accounts import schema
        source, destination = self.account(), self.account()
        with patch.object(schema, '_active_account', return_value=self.owner), \
             patch.object(schema.FinancialAccount.objects, 'select_related') as accounts, \
             patch.object(schema, 'create_and_submit_transfer', return_value=None) as submit, \
             patch.object(gate, 'country_for_request', return_value='CO'), \
             patch.object(gate, 'configured', return_value=True):
            accounts.return_value.filter.return_value = [source, destination]
            result = schema.CreatePaymentTransfer.mutate(
                None, SimpleNamespace(context=SimpleNamespace(META={})),
                source.internal_id, destination.internal_id, Decimal('1'), uuid4())
        self.assertFalse(result.success)
        submit.assert_not_called()


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BrebDestinationPollTests(SimpleTestCase):
    """Polling a saved recipient's check reaches the provider, so a Colombian
    recipient needs a current location pass from an allowed IP."""
    def setUp(self):
        cache.clear()
        self.owner = SimpleNamespace(pk=34)

    def poll(self, country='COL', ip='CO', passed=False):
        from payment_accounts import local_money_schema as lms
        row = SimpleNamespace(country=country)
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        with patch.object(lms, '_owner', return_value=self.owner), \
             patch.object(lms.PayoutDestination.objects, 'filter') as rows, \
             patch.object(lms.local_money, 'refresh_destination', return_value=row) as refresh, \
             patch.object(lms, '_destination', return_value='destination'), \
             patch.object(gate, 'country_for_request', return_value=ip), \
             patch.object(gate, 'configured', return_value=True):
            rows.return_value.first.return_value = row
            if passed:
                gate.grant_pass(self.owner)
            try:
                result = lms.LocalMoneyQuery.resolve_local_destination(None, info, uuid4())
            except Exception as exc:  # the GraphQL error the app sees
                result = exc
        return result, refresh

    def test_colombian_recipient_needs_a_pass(self):
        result, refresh = self.poll()
        self.assertIsInstance(result, Exception)
        refresh.assert_not_called()

    def test_colombian_recipient_refused_from_venezuela(self):
        result, refresh = self.poll(ip='VE', passed=True)
        self.assertIsInstance(result, Exception)
        refresh.assert_not_called()

    def test_colombian_recipient_polls_with_a_pass(self):
        result, refresh = self.poll(passed=True)
        self.assertEqual(result, 'destination')
        refresh.assert_called_once()

    def test_other_countries_poll_without_a_pass(self):
        result, refresh = self.poll(country='MEX')
        self.assertEqual(result, 'destination')
        refresh.assert_called_once()
