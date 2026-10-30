"""Employee invitations by @usuario name the account, not its number."""
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from users.graphql_employee import AcceptInvitation, EmployeeQueries
from users.models import Business
from users.models_employee import BusinessEmployee, EmployeeInvitation

User = get_user_model()


class AccountInvitationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='inv-owner', firebase_uid='inv-owner')
        self.business = Business.objects.create(name='Tienda', category='retail')
        # Phone-less, like every account since phone-less signup.
        self.invitee = User.objects.create_user(username='inv-new', firebase_uid='inv-new')
        self.invitation = EmployeeInvitation.objects.create(
            business=self.business, employee_phone='', employee_phone_country='', employee_user=self.invitee,
            employee_username=self.invitee.username, role='cashier', invited_by=self.owner,
            expires_at=timezone.now() + timedelta(days=7))

    def _info(self, user):
        return SimpleNamespace(context=SimpleNamespace(user=user))

    def test_a_phoneless_account_sees_and_accepts_its_invitation(self):
        # protects=an @usuario invitation reaches an account with no verified number; fails_when=listing or accepting needs a phone; no_claim=who may send invitations
        mine = list(EmployeeQueries.resolve_my_invitations(None, self._info(self.invitee)))
        self.assertEqual([i.pk for i in mine], [self.invitation.pk])
        out = AcceptInvitation.mutate(None, self._info(self.invitee), self.invitation.invitation_code)
        self.assertTrue(out.success, out.errors)
        self.assertTrue(BusinessEmployee.objects.filter(business=self.business, user=self.invitee).exists())

    def test_no_one_else_can_accept_it(self):
        # protects=an invitation code alone does not make someone an employee; fails_when=another account accepts; no_claim=phone invitations
        other = User.objects.create_user(username='inv-other', firebase_uid='inv-other')
        self.assertEqual(list(EmployeeQueries.resolve_my_invitations(None, self._info(other))), [])
        out = AcceptInvitation.mutate(None, self._info(other), self.invitation.invitation_code)
        self.assertFalse(out.success)
