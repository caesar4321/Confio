"""Ramps are OWNER-ONLY for business accounts.

Moving money between a business balance and a BANK is the owner's authority,
never an employee's. This was previously enforced in the app UI alone, and
with the wrong permissions: Recargar was gated on `manage_p2p` and Retirar on
`send_funds`, so any employee who could pay a supplier could also drain the
business to a bank account, and a direct GraphQL call bypassed even that
(CreateRampOrder resolved its account with required_permission=None).

`manage_bank_accounts` deliberately does NOT grant this: it governs which
payout methods are on file, not the authority to move funds out. Owners carry
no BusinessEmployee row — get_jwt_business_context_with_validation authorizes
them through Account ownership — so employee_record's presence is exactly the
deny signal.

    myvenv/bin/python manage.py test ramps.tests.test_ramp_owner_only
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ramps import schema as ramps_schema


def _ctx(account_type='business', employee_record=None):
    """A decoded JWT context the way jwt_context returns it."""
    ctx = {
        'user_id': 1,
        'account_type': account_type,
        'account_index': 0,
        'business_id': 42 if account_type == 'business' else None,
    }
    if employee_record is not None:
        ctx['employee_record'] = employee_record
    return ctx


def _patch_ctx(ctx):
    return mock.patch(
        'users.jwt_context.get_jwt_business_context_with_validation',
        return_value=ctx,
    )


def _patch_is_employee(value):
    """The guard asks the BusinessEmployee table directly, so tests must say
    what that table would answer (SimpleTestCase has no DB)."""
    return mock.patch('users.jwt_context.is_business_employee', return_value=value)


class EmployeeRampDenialTests(SimpleTestCase):
    """_employee_ramp_denial is the API half of the dual enforcement."""

    def test_business_employee_is_denied(self):
        with _patch_ctx(_ctx()), _patch_is_employee(True):
            denial = ramps_schema._employee_ramp_denial(mock.Mock())
        self.assertIsNotNone(denial)
        self.assertIn('dueño del negocio', denial)

    def test_privileged_employee_roles_are_denied_too(self):
        # admin/manager hold manage_bank_accounts, which is about payout
        # METHODS. It must not be mistaken for authority to move funds.
        for role in ('admin', 'manager'):
            with self.subTest(role=role):
                with _patch_ctx(_ctx()), _patch_is_employee(True):
                    self.assertIsNotNone(
                        ramps_schema._employee_ramp_denial(mock.Mock()))

    def test_business_owner_is_allowed(self):
        # Owners are authorized via Account ownership and never get an
        # employee_record attached to the context.
        with _patch_ctx(_ctx()), _patch_is_employee(False):
            self.assertIsNone(ramps_schema._employee_ramp_denial(mock.Mock()))

    def test_personal_account_is_allowed(self):
        with _patch_ctx(_ctx(account_type='personal')), _patch_is_employee(True):
            # Even a stray employee row cannot matter on a personal context.
            self.assertIsNone(ramps_schema._employee_ramp_denial(mock.Mock()))

    def test_no_jwt_context_falls_through(self):
        # Unauthenticated/personal-token callers are handled by the mutation's
        # own auth check; this guard must not invent a denial for them.
        with _patch_ctx(None):
            self.assertIsNone(ramps_schema._employee_ramp_denial(mock.Mock()))

    def test_employee_record_on_personal_context_is_ignored(self):
        # Only a BUSINESS context can carry business authority.
        with _patch_ctx(_ctx(account_type='personal')), _patch_is_employee(True):
            self.assertIsNone(ramps_schema._employee_ramp_denial(mock.Mock()))


class CreateRampOrderGuardTests(SimpleTestCase):
    """The guard must run BEFORE any order is built, on both mutations."""

    def _authenticated_info(self):
        return SimpleNamespace(context=SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, id=1)))

    def test_create_ramp_order_refuses_employee(self):
        with _patch_ctx(_ctx()), _patch_is_employee(True), \
             mock.patch.object(ramps_schema, '_get_ramp_account_for_user') as acct:
            result = ramps_schema.CreateRampOrder().mutate(
                self._authenticated_info(),
                direction='OFF_RAMP',
                amount='10',
                payment_method_code='PSE',
            )
        self.assertFalse(result.success)
        self.assertIn('dueño del negocio', result.error)
        # Refused before the account (and any provider call) is touched.
        acct.assert_not_called()


class GuardarianProxyGuardTests(SimpleTestCase):
    """The REST proxy must enforce the SAME rule as the GraphQL mutations.

    It creates real Guardarian orders (off-ramps included), so guarding only
    GraphQL would leave the whole rule bypassable by calling the URL directly.
    """

    def test_proxy_refuses_business_employee(self):
        from django.test import RequestFactory
        from config import views

        req = RequestFactory().post(
            '/api/guardarian/transaction/', data='{}', content_type='application/json')
        req.META['HTTP_AUTHORIZATION'] = 'JWT faketoken'

        with mock.patch.object(views, 'jwt_decode', return_value={
                    'user_id': 7, 'account_type': 'business', 'business_id': 42}), \
             mock.patch('users.models.User.objects.get', return_value=SimpleNamespace(id=7)), \
             mock.patch('users.jwt_context.is_business_employee', return_value=True), \
             mock.patch('security.integrity_service.app_check_service.verify_request_header',
                        return_value={'success': True}), \
             mock.patch.object(views.settings, 'GUARDARIAN_API_KEY', 'k', create=True):
            resp = views.guardarian_transaction_proxy(req)

        # JsonResponse escapes non-ASCII, so decode rather than substring-match.
        self.assertEqual(resp.status_code, 403)
        self.assertIn('dueño del negocio', json.loads(resp.content)['error'])

    def test_proxy_allows_business_owner(self):
        """An owner must pass the guard (it may fail later for other reasons —
        we assert only that it is NOT the 403 this guard produces)."""
        from django.test import RequestFactory
        from config import views

        req = RequestFactory().post(
            '/api/guardarian/transaction/', data='{}', content_type='application/json')
        req.META['HTTP_AUTHORIZATION'] = 'JWT faketoken'

        with mock.patch.object(views, 'jwt_decode', return_value={
                    'user_id': 7, 'account_type': 'business', 'business_id': 42}), \
             mock.patch('users.models.User.objects.get', return_value=SimpleNamespace(id=7)), \
             mock.patch('users.jwt_context.is_business_employee', return_value=False), \
             mock.patch('security.integrity_service.app_check_service.verify_request_header',
                        return_value={'success': True}), \
             mock.patch.object(views.settings, 'GUARDARIAN_API_KEY', 'k', create=True):
            try:
                resp = views.guardarian_transaction_proxy(req)
            except Exception:
                # Got PAST the guard and failed deeper in the proxy (it needs a
                # fuller user/session than this unit test provides). That is the
                # assertion: the owner is not stopped by the owner-only check.
                return
        body = json.loads(resp.content) if resp.content else {}
        self.assertNotEqual(resp.status_code, 403)
        self.assertNotIn('dueño del negocio', str(body.get('error', '')))


class EmployeeLookupFailClosedTests(SimpleTestCase):
    """A lookup that blows up must DENY, never silently grant."""

    def test_lookup_exception_denies(self):
        from users.jwt_context import is_business_employee
        with mock.patch('users.models_employee.BusinessEmployee.objects.filter',
                        side_effect=RuntimeError('db down')):
            self.assertTrue(is_business_employee(SimpleNamespace(id=1), 42))

    def test_no_business_id_is_not_an_employee(self):
        from users.jwt_context import is_business_employee
        self.assertFalse(is_business_employee(SimpleNamespace(id=1), None))
