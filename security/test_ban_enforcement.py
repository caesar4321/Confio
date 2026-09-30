from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from types import SimpleNamespace
from unittest import mock
import time

from security.middleware import SecurityMiddleware
from security.models import UserBan
from users.models import Account, Business
from users.models_employee import BusinessEmployee


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BanEnforcementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='ban-enforcement')
        self.middleware = SecurityMiddleware(lambda request: None)
        cache.clear()

    def test_new_ban_is_not_hidden_by_cached_allow(self):
        self.assertFalse(self.middleware.check_user_banned(self.user))
        UserBan.objects.create(user=self.user, ban_type='permanent', reason='fraud')
        self.assertTrue(self.middleware.check_user_banned(self.user))

    def test_bulk_lift_is_not_hidden_by_cached_deny(self):
        ban = UserBan.objects.create(user=self.user, ban_type='permanent', reason='fraud')
        self.assertTrue(self.middleware.check_user_banned(self.user))
        UserBan.objects.filter(pk=ban.pk).update(deleted_at=timezone.now())
        self.assertFalse(self.middleware.check_user_banned(self.user))


class PreparedBusinessSendAuthorityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create(username='spend-owner', firebase_uid='spend-owner')
        self.employee = get_user_model().objects.create(username='spend-employee', firebase_uid='spend-employee')
        self.business = Business.objects.create(name='Spending authority test')
        Account.objects.create(user=self.owner, business=self.business, account_type='business')
        self.membership = BusinessEmployee.objects.create(
            user=self.employee, business=self.business, role='manager')

    def assert_submit_denied(self):
        from send.bsc_flow import submit_bsc_send
        from send.invite_bsc_flow import submit_create
        from cusd_plus.sponsor_7702 import PolicyError
        send = SimpleNamespace(
            sender_user_id=self.employee.pk, sender_business_id=self.business.pk,
            sender_business=self.business, status='PENDING', bsc_calls_json='{}',
            sender_address='0x' + '11' * 20)
        invite = SimpleNamespace(
            inviter_user_id=self.employee.pk, status='draft', send_transaction=send,
            inviter_address=send.sender_address, invitation_id='ab' * 32, token_type='USDT')
        deadline = str(int(time.time()) + 600)
        # Stop after the authority boundary, without executing RPC/signing.
        with mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch') as broadcast, \
                mock.patch('send.bsc_flow._validate_send_batch', side_effect=PolicyError('past_authority_gate')), \
                mock.patch('send.invite_bsc_flow._stored_create_calls', return_value=[{}]), \
                mock.patch('send.invite_bsc_flow._validate_create_batch', side_effect=PolicyError('past_authority_gate')):
            self.assertEqual(submit_bsc_send(self.employee, send, '0', deadline, 'unused'),
                             {'success': False, 'error': 'sender_not_authorized'})
            self.assertEqual(submit_create(self.employee, invite, '0', deadline, 'unused'),
                             {'success': False, 'error': 'sender_not_authorized'})
        broadcast.assert_not_called()

    def test_deactivated_employee_cannot_submit_prepared_send_or_invite(self):
        self.membership.is_active = False
        self.membership.save(update_fields=['is_active'])
        self.assert_submit_denied()

    def test_revoked_permission_cannot_submit_prepared_send_or_invite(self):
        self.membership.permissions = {'send_funds': False}
        self.membership.save(update_fields=['permissions'])
        self.assert_submit_denied()

    def test_deleted_employee_cannot_submit_prepared_send_or_invite(self):
        self.membership.soft_delete()
        self.assert_submit_denied()

    def test_current_owner_and_manager_remain_authorized(self):
        from users.jwt_context import business_permission_is_current
        self.assertTrue(business_permission_is_current(self.owner, self.business.pk, 'send_funds'))
        self.assertTrue(business_permission_is_current(self.employee, self.business.pk, 'send_funds'))

    def test_demoted_employee_is_denied(self):
        self.membership.role = 'cashier'
        self.membership.save(update_fields=['role'])
        self.assert_submit_denied()

    def test_deleted_business_is_denied(self):
        self.business.soft_delete()
        self.assert_submit_denied()

    def test_owner_account_retains_authority_despite_employee_override(self):
        from users.jwt_context import business_permission_is_current
        membership, _ = BusinessEmployee.objects.get_or_create(
            user=self.owner, business=self.business, defaults={'role': 'owner'})
        membership.permissions = {'send_funds': False}
        membership.save(update_fields=['permissions'])
        self.assertTrue(business_permission_is_current(self.owner, self.business.pk, 'send_funds'))
