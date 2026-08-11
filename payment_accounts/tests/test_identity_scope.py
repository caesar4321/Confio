from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from payment_accounts.schema import PaymentAccountError, _verified_identity
from security.models import IdentityVerification
from users.models import Account, Business


class PaymentAccountIdentityScopeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='scope-user',
            firebase_uid='scope-user-firebase',
            password='secret',
        )
        self.business = Business.objects.create(name='Acme SAS', category='services')
        self.personal_account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0
        )
        self.business_account = Account.objects.create(
            user=self.user,
            account_type='business',
            account_index=0,
            business=self.business,
        )

    def identity(self, *, document_number, risk_factors):
        return IdentityVerification.objects.create(
            user=self.user,
            verified_first_name='Ana',
            verified_last_name='Perez',
            verified_date_of_birth=date(1990, 1, 1),
            verified_nationality='COL',
            verified_address='Calle 1',
            verified_city='Bogota',
            verified_state='Cundinamarca',
            verified_country='COL',
            document_type='national_id',
            document_number=document_number,
            document_issuing_country='COL',
            status='verified',
            risk_factors=risk_factors,
        )

    def test_business_account_requires_exact_business_didit_kyb(self):
        self.identity(
            document_number='personal-1',
            risk_factors={'provider': 'didit'},
        )
        wrong_business = self.identity(
            document_number='business-wrong',
            risk_factors={
                'provider': 'didit',
                'account_type': 'business',
                'business_id': '999999',
                'didit': {'session': {'session_kind': 'business'}},
            },
        )

        with self.assertRaisesRegex(PaymentAccountError, 'business Didit KYB'):
            _verified_identity(self.business_account)

        correct = self.identity(
            document_number='business-correct',
            risk_factors={
                'provider': 'didit',
                'account_type': 'business',
                'business_id': str(self.business.id),
                'didit': {'session': {'session_kind': 'business'}},
            },
        )
        self.assertEqual(_verified_identity(self.business_account), correct)
        self.assertNotEqual(_verified_identity(self.business_account), wrong_business)

    def test_personal_account_never_reuses_business_kyb(self):
        self.identity(
            document_number='business-only',
            risk_factors={
                'provider': 'didit',
                'account_type': 'business',
                'business_id': str(self.business.id),
                'didit': {'session': {'session_kind': 'business'}},
            },
        )

        with self.assertRaisesRegex(PaymentAccountError, 'Didit KYC'):
            _verified_identity(self.personal_account)
