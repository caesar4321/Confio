from django.test import TestCase
from django.contrib.auth import get_user_model
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.testcases import JSONWebTokenTestCase
from graphql_jwt.exceptions import PermissionDenied
from graphql_jwt.utils import jwt_encode
import json
from users.jwt import jwt_payload_handler, verify_auth_token_version
from users.phone_utils import find_user_by_phone, phone_lookup_key
from users.migration_safety import (
    MATERIAL_SPENDABLE_ALGO_MICROS,
    get_address_reassignment_blocker,
    inspect_address_migration_risk,
)

User = get_user_model()


class UserSoftDeleteAuthTestCase(TestCase):
    def test_soft_deleted_users_are_hidden_from_default_manager(self):
        user = User.objects.create_user(
            username='deleteduser',
            email='deleted@example.com',
            password='testpass123',
            firebase_uid='deleted-firebase-uid',
        )

        user.soft_delete()

        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertTrue(User.all_objects.filter(id=user.id).exists())

        deleted_user = User.all_objects.get(id=user.id)
        self.assertFalse(deleted_user.is_active)
        self.assertIsNotNone(deleted_user.deleted_at)
        self.assertEqual(deleted_user.auth_token_version, 2)

    def test_soft_delete_invalidates_existing_jwt(self):
        user = User.objects.create_user(
            username='tokenuser',
            email='token@example.com',
            password='testpass123',
            firebase_uid='token-firebase-uid',
        )
        token = jwt_encode(jwt_payload_handler(user))

        user.soft_delete()

        with self.assertRaises(PermissionDenied):
            verify_auth_token_version(token)

class AccountBalanceQueryTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

    def test_account_balance_query(self):
        """Test that account balance query returns correct values"""
        from .schema import Query
        
        # Mock the GraphQL context
        class MockContext:
            def __init__(self, user):
                self.user = user
        
        # Mock the GraphQL info object
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext(self.user)
        info = MockInfo(context)
        
        # Test the resolver directly
        query = Query()
        
        # Test cUSD balance
        result = query.resolve_account_balance(info, 'cUSD')
        self.assertEqual(result, '2850.35')
        
        # Test CONFIO balance
        result = query.resolve_account_balance(info, 'CONFIO')
        self.assertEqual(result, '234.18')
        
        # Test USDC balance
        result = query.resolve_account_balance(info, 'USDC')
        self.assertEqual(result, '458.22')
        
        # Test unknown token type
        result = query.resolve_account_balance(info, 'UNKNOWN')
        self.assertEqual(result, '0')

    def test_account_balance_requires_authentication(self):
        """Test that account balance query requires authentication"""
        from .schema import Query
        
        # Mock the GraphQL context with no user
        class MockContext:
            def __init__(self):
                self.user = None
        
        # Mock the GraphQL info object
        class MockInfo:
            def __init__(self, context):
                self.context = context
        
        context = MockContext()
        info = MockInfo(context)
        
        # Test the resolver directly
        query = Query()
        result = query.resolve_account_balance(info, 'cUSD')
        self.assertEqual(result, '0')


class MigrationSafetyTestCase(TestCase):
    class FakeAlgodClient:
        def __init__(self, responses):
            self.responses = responses

        def account_info(self, address):
            return self.responses[address]

    def test_detects_relevant_asset_balance(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 500000,
                'min-balance': 400000,
                'assets': [
                    {'asset-id': 31566704, 'amount': 123456},
                ],
            }
        })

        risk = inspect_address_migration_risk(algod, 'legacy')
        self.assertTrue(risk['has_material_risk'])
        self.assertEqual(risk['relevant_assets'][31566704], 123456)

    def test_detects_spendable_algo_even_without_assets(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 400000 + MATERIAL_SPENDABLE_ALGO_MICROS,
                'min-balance': 400000,
                'assets': [],
            }
        })

        risk = inspect_address_migration_risk(algod, 'legacy')
        self.assertTrue(risk['has_material_risk'])
        self.assertEqual(risk['spendable_algo'], MATERIAL_SPENDABLE_ALGO_MICROS)

    def test_blocks_reassignment_when_legacy_wallet_still_holds_value(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 828500,
                'min-balance': 400000,
                'assets': [
                    {'asset-id': 31566704, 'amount': 111850196},
                ],
            }
        })

        blocker = get_address_reassignment_blocker(algod, 'legacy', 'new')
        self.assertIsNotNone(blocker)

    def test_allows_reassignment_when_old_wallet_is_empty(self):
        algod = self.FakeAlgodClient({
            'legacy': {
                'amount': 0,
                'min-balance': 0,
                'assets': [],
            }
        })

        blocker = get_address_reassignment_blocker(algod, 'legacy', 'new')
        self.assertIsNone(blocker)


class PhoneLookupTestCase(TestCase):
    """A send identifies its recipient by the FULL number — calling code plus
    subscriber digits. Every spelling of a full number lands on the same user;
    anything less than a full number lands on nobody."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='phoneuser',
            email='phone@example.com',
            password='testpass123',
            firebase_uid='phone-firebase-uid',
            phone_country='CO',
            phone_number='3132587634',
        )

    def test_canonical_key_resolves(self):
        # What `phoneKey` hands the app, and what the transaction list passes
        # through as fromPhone/toPhone.
        self.assertEqual(find_user_by_phone('57:3132587634'), self.user)

    def test_e164_resolves(self):
        self.assertEqual(find_user_by_phone('+573132587634'), self.user)

    def test_formatted_e164_resolves(self):
        self.assertEqual(find_user_by_phone('+57 313 258 7634'), self.user)

    def test_bare_local_digits_never_resolve(self):
        # A local number names no country. "3132587634" is dialable in
        # Colombia and elsewhere, so matching it would pick a country at
        # random. Refusing is correct even though this user's local digits
        # are exactly that.
        self.assertEqual(phone_lookup_key('3132587634'), '')
        self.assertIsNone(find_user_by_phone('3132587634'))

    def test_unknown_number_returns_none(self):
        self.assertIsNone(find_user_by_phone('57:3009998877'))

    def test_blank_input_returns_none(self):
        self.assertIsNone(find_user_by_phone(''))
        self.assertIsNone(find_user_by_phone(None))

    def test_bare_digits_never_guess_a_calling_code(self):
        # "3132587634" also reads as +31 (Netherlands) 32587634. Guessing a
        # split on an unprefixed number could pay the wrong person.
        self.assertEqual(phone_lookup_key('3132587634'), '')

    def test_partial_number_never_matches_a_full_one(self):
        # The wrong-payment path: +57 3009998877 has no Colombian user, but a
        # US user's LOCAL number is 3009998877. Matching on anything less than
        # the full number would pay them.
        us_user = User.objects.create_user(
            username='ususer',
            email='us@example.com',
            password='testpass123',
            firebase_uid='us-firebase-uid',
            phone_country='US',
            phone_number='3009998877',
        )
        self.assertEqual(phone_lookup_key('+573009998877'), '57:3009998877')
        self.assertIsNone(find_user_by_phone('+573009998877'))
        # ...and the bare local digits don't reach the US user either.
        self.assertIsNone(find_user_by_phone('3009998877'))
        # Only the full US number does.
        self.assertEqual(find_user_by_phone('+13009998877'), us_user)

    def test_argentina_mobile_nine_collapses_to_stored_key(self):
        # canonicalize_phone_digits drops the optional mobile 9, so every
        # spelling of the same AR number must reach the one stored key.
        ar_user = User.objects.create_user(
            username='aruser',
            email='ar@example.com',
            password='testpass123',
            firebase_uid='ar-firebase-uid',
            phone_country='AR',
            phone_number='2231234567',
        )
        self.assertEqual(ar_user.phone_key, '54:2231234567')
        for shape in ('+54 9 223 1234567', '+542231234567', '54:92231234567', '54:2231234567'):
            self.assertEqual(find_user_by_phone(shape), ar_user, shape)

    def test_ambiguous_number_is_refused_not_guessed(self):
        # Production carries a partial unique index on phone_key, but it lives
        # in no migration — so a freshly-migrated environment (including this
        # test DB) can hold duplicates. Paying an arbitrary one of two matching
        # users is worse than refusing.
        from django.db import IntegrityError, transaction
        try:
            with transaction.atomic():
                User.objects.create_user(
                    username='dupe',
                    email='dupe@example.com',
                    password='testpass123',
                    firebase_uid='dupe-firebase-uid',
                    phone_country='CO',
                    phone_number='3132587634',
                )
        except IntegrityError:
            self.skipTest('this database enforces phone_key uniqueness; nothing to refuse')
        self.assertIsNone(find_user_by_phone('57:3132587634'))

    def test_deactivated_user_does_not_receive(self):
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(find_user_by_phone('57:3132587634'))

    def test_full_digits_of_one_number_are_not_another_users_local_number(self):
        # A US user whose stored local digits spell out the Colombian user's
        # full international number must not be reachable as that number.
        collider = User.objects.create_user(
            username='collider',
            email='collider@example.com',
            password='testpass123',
            firebase_uid='collider-firebase-uid',
            phone_country='US',
            phone_number='573132587634',
        )
        self.assertEqual(collider.phone_number, '573132587634')
        self.assertEqual(find_user_by_phone('57:3132587634'), self.user)
        self.assertEqual(find_user_by_phone('+573132587634'), self.user)
