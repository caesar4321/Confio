from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from payment_accounts.compliance import _contact
from payment_accounts.models import ProviderProfile
from ramps import profile_push
from ramps.contact_phone import has_provider_phone, normalize_contact_phone, provider_phone
from ramps.koywe_client import KoyweClient, KoyweError
from ramps.mexico_economic_activities import MEXICO_ECONOMIC_ACTIVITIES
from ramps.models import RampUserAddress
from ramps.schema import UpsertRampUserAddress, _is_ramp_address_complete
from users.models import Account

ACTIVITY = sorted(MEXICO_ECONOMIC_ACTIVITIES)[0]
BOLIVIAN = '+59171234567'


def _info(user):
    return SimpleNamespace(context=SimpleNamespace(user=user, META={}))


def _user(name, **fields):
    fields.setdefault('country', 'BO')
    return get_user_model().objects.create(username=name, email=f'{name}@example.com', firebase_uid=name, **fields)


def _save(user, **extra):
    fields = dict(address_street='Calle 1', address_city='La Paz', address_state='LP', address_zip_code='0000',
                  economic_activity=ACTIVITY)
    fields.update(extra)
    return UpsertRampUserAddress.mutate(None, _info(user), **fields)


def _address(user, country='BOL'):
    return SimpleNamespace(user=user, address_street='Calle 1', address_city='La Paz', address_state='LP',
                           address_zip_code='0000', address_country=country, economic_activity=ACTIVITY)


@patch('ramps.profile_push.queue_profile_push')
class SaveTests(TestCase):
    def setUp(self):
        self.user = _user('nophone')

    def test_normalizes_real_numbers_only(self, _push):
        self.assertEqual(normalize_contact_phone('+591 7123-4567'), BOLIVIAN)
        for bad in ('', '0000000000', '+0000000000', '+57300', '+5700000000', '+999123456789012345'):
            self.assertIsNone(normalize_contact_phone(bad), bad)

    def test_phone_and_address_save_together(self, _push):
        result = _save(self.user, contact_phone=BOLIVIAN)
        self.assertTrue(result.success, result.error)
        row = RampUserAddress.objects.get(user=self.user)
        self.assertEqual((row.address_street, row.contact_phone), ('Calle 1', BOLIVIAN))

    def test_a_bad_number_saves_nothing(self, _push):
        result = _save(self.user, contact_phone='0000000000')
        self.assertFalse(result.success)
        self.assertFalse(RampUserAddress.objects.filter(user=self.user).exists())

    def test_saving_never_touches_the_verified_phone_fields(self, _push):
        _save(self.user, contact_phone=BOLIVIAN)
        self.user.refresh_from_db()
        self.assertFalse(self.user.phone_number)
        self.assertFalse(self.user.phone_key)

    def test_a_verified_user_can_change_the_number_providers_get(self, _push):
        verified = _user('verified', phone_number='3001234567', phone_country='CO')
        key = verified.phone_key
        self.assertEqual(provider_phone(verified), '+573001234567')
        _save(verified, contact_phone=BOLIVIAN)
        verified.refresh_from_db()
        self.assertEqual(provider_phone(verified), BOLIVIAN)
        self.assertEqual((verified.phone_number, verified.phone_key), ('3001234567', key))

    def test_address_is_incomplete_without_a_phone(self, _push):
        self.assertFalse(_is_ramp_address_complete(_address(self.user)))
        _save(self.user, contact_phone=BOLIVIAN)
        self.assertTrue(_is_ramp_address_complete(_address(self.user)))

    def test_phone_verified_accounts_never_need_the_new_step(self, _push):
        verified = SimpleNamespace(pk=None, phone_number='3001234567')
        self.assertTrue(has_provider_phone(verified))
        self.assertTrue(_is_ramp_address_complete(_address(verified, 'COL')))

    def test_the_number_the_person_set_wins_at_the_handoff(self, _push):
        _save(self.user, contact_phone=BOLIVIAN)
        decision = {'contact_details': {'email': 'a@example.com', 'phone': '+573001234567'}}
        self.assertEqual(_contact(decision, self.user)[1], BOLIVIAN)

    def test_picked_country_is_stored_as_alpha3(self, _push):
        self.assertTrue(_save(self.user, address_country='pe').success)
        self.assertEqual(RampUserAddress.objects.get(user=self.user).address_country, 'PER')

    def test_unknown_country_is_refused(self, _push):
        self.assertFalse(_save(self.user, address_country='ZZ').success)

    def test_older_builds_sending_no_country_keep_the_saved_one(self, _push):
        _save(self.user, address_country='PE')
        self.assertTrue(_save(self.user).success)
        self.assertEqual(RampUserAddress.objects.get(user=self.user).address_country, 'PER')

    def test_picking_leaves_the_residence_alone(self, _push):
        _save(self.user, address_country='PE')
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, 'BO')

    def test_only_a_provider_field_change_queues_a_push(self, push):
        _save(self.user, contact_phone=BOLIVIAN)
        self.assertEqual(push.call_count, 1)
        _save(self.user)
        self.assertEqual(push.call_count, 1)
        _save(self.user, address_street='Calle 2')
        self.assertEqual(push.call_count, 2)
        _save(self.user, contact_phone='+59176543210')
        self.assertEqual(push.call_count, 3)


class ProviderPushTests(TestCase):
    def setUp(self):
        with patch('ramps.profile_push.queue_profile_push'):
            self.user = _user('pusher')
            _save(self.user, contact_phone=BOLIVIAN)
        self.account = Account.objects.filter(user=self.user).first() or Account.objects.create(
            user=self.user, account_type='personal', account_index=0)

    def _profile(self, **fields):
        defaults = dict(confio_account=self.account, provider='infinia', provider_owner_id='owner-1',
                        owner_type='individual', kyc_mode='SELF_DECLARED')
        return ProviderProfile.objects.create(**{**defaults, **fields})

    @patch('payment_accounts.clients.InfiniaClient')
    def test_infinia_owner_gets_the_new_phone_and_address(self, client):
        self._profile()
        self.assertEqual(profile_push._push_to_infinia(self.user), 1)
        owner, payload = client.return_value.update_owner.call_args.args
        self.assertEqual(owner, 'owner-1')
        self.assertEqual(payload['individual']['phone_number'], BOLIVIAN)
        self.assertEqual(payload['individual']['address']['line_1'], 'Calle 1')
        self.assertEqual(payload['individual']['address']['country'], 'BO')

    @patch('payment_accounts.clients.InfiniaClient')
    def test_no_open_infinia_account_calls_nothing(self, client):
        self._profile(provider_owner_id='')
        self.assertEqual(profile_push._push_to_infinia(self.user), 0)
        client.return_value.update_owner.assert_not_called()

    def test_koywe_is_skipped_without_an_order(self):
        with patch('ramps.koywe_client.KoyweClient.push_account_profile') as push:
            self.assertFalse(profile_push._push_to_koywe(self.user))
        push.assert_not_called()

    def test_one_failing_provider_does_not_stop_the_other(self):
        with patch.object(profile_push, '_push_to_koywe', side_effect=RuntimeError('down')), \
                patch.object(profile_push, '_push_to_infinia') as infinia:
            self.assertEqual(profile_push.push_to_providers(self.user.id), ['koywe'])
        infinia.assert_called_once()

    def test_koywe_push_puts_the_full_profile(self):
        client = KoyweClient.__new__(KoyweClient)
        client._normalize_contact_profile = MagicMock(return_value={'phone': BOLIVIAN})
        client._build_account_profile_payload = MagicMock(return_value={'personalInfo': {'phoneNumber': BOLIVIAN}})
        client._build_migration_payload = MagicMock(return_value={'email': 'a@example.com'})
        client.get_account = MagicMock(return_value={'email': 'a@example.com'})
        client.update_account = MagicMock()
        self.assertTrue(client.push_account_profile(email='A@example.com', country_code='BO', contact_profile={}))
        client.update_account.assert_called_once_with(email='a@example.com', payload={'email': 'a@example.com'})

    def test_koywe_push_ignores_an_account_that_does_not_exist(self):
        client = KoyweClient.__new__(KoyweClient)
        client._normalize_contact_profile = MagicMock(return_value={'phone': BOLIVIAN})
        client._build_account_profile_payload = MagicMock(return_value={'x': 1})
        client.get_account = MagicMock(side_effect=KoyweError('account not found'))
        client._is_account_not_found_error = MagicMock(return_value=True)
        client.update_account = MagicMock()
        self.assertFalse(client.push_account_profile(email='a@example.com', country_code='BO', contact_profile={}))
        client.update_account.assert_not_called()
