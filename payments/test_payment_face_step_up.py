from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from payments.bsc_flow import _payment_step_up
from security import face_step_up as fsu
from security.models import FaceCheck, IdentityVerification
from users.models import Account, Business
from users.models_employee import BusinessEmployee

User = get_user_model()


def _verify(user=None, business=None, number='1065000100'):
    extra = {'risk_factors': {'account_type': 'business', 'business_id': str(business.id)}} if business else {}
    return IdentityVerification.all_documents.create(
        user=user, verified_first_name='Ana', verified_last_name='Perez',
        verified_date_of_birth='1994-07-21', verified_nationality='COL', verified_address='-',
        verified_city='-', verified_state='-', verified_country='COL', document_type='national_id',
        document_number=number, document_issuing_country='COL', status='verified',
        verified_at=timezone.now(), **extra)


def _passed(user, challenge='full', session='w-1'):
    return FaceCheck.objects.create(user=user, purpose='withdrawal', liveness_session_id=session,
                                    status='passed', challenge=challenge, completed_at=timezone.now())


def _invoice(business, amount='10', token_type='USDT'):
    from types import SimpleNamespace
    return SimpleNamespace(merchant_business=business, merchant_business_id=getattr(business, 'id', None),
                           merchant_account=None, amount=amount, token_type=token_type)


@override_settings(FACE_STEP_UP_ENABLED=True)
class PaymentFaceStepUpTests(TestCase):
    """The same rule as Send: every personal payment by a KYC'd payer asks Confío Face."""

    def setUp(self):
        self.payer = User.objects.create(username='payer', email='payer@example.com', firebase_uid='payer-uid')
        _verify(self.payer)
        owner = User.objects.create(username='owner', email='owner@example.com', firebase_uid='owner-uid')
        self.shop = Business.objects.create(name='Tienda verificada')
        Account.objects.create(user=owner, account_type='business', business=self.shop)
        _verify(owner, business=self.shop, number='900100200')

    def test_a_verified_merchant_asks_too(self):
        self.assertEqual(_payment_step_up(self.payer, None, self.shop), fsu.FACE_STEP_UP_MESSAGE)
        _passed(self.payer)
        self.assertEqual(_payment_step_up(self.payer, None, self.shop), '')

    def test_a_small_payment_inside_confio_takes_the_light_check(self):
        _passed(self.payer, challenge='light')
        self.assertEqual(_payment_step_up(self.payer, None, self.shop, invoice=_invoice(self.shop)), '')
        # Without the amount (or above the light limit) only the full check counts.
        self.assertEqual(_payment_step_up(self.payer, None, self.shop), fsu.FACE_STEP_UP_MESSAGE)
        self.assertEqual(_payment_step_up(self.payer, None, self.shop, invoice=_invoice(self.shop, amount='80')),
                         fsu.FACE_STEP_UP_MESSAGE)

    def test_paying_a_business_you_work_for_needs_the_full_check(self):
        BusinessEmployee.objects.create(user=self.payer, business=self.shop, role='cashier')
        _passed(self.payer, challenge='light')
        self.assertEqual(_payment_step_up(self.payer, None, self.shop, invoice=_invoice(self.shop)),
                         fsu.FACE_STEP_UP_MESSAGE)

    def test_a_deleted_employee_record_still_counts(self):
        employee = BusinessEmployee.objects.create(user=self.payer, business=self.shop, role='cashier')
        employee.soft_delete()
        _passed(self.payer, challenge='light')
        self.assertEqual(_payment_step_up(self.payer, None, self.shop, invoice=_invoice(self.shop)),
                         fsu.FACE_STEP_UP_MESSAGE)

    def test_paying_your_own_business_needs_the_full_check(self):
        own = Business.objects.create(name='Mi negocio')
        Account.objects.create(user=self.payer, account_type='business', business=own)
        _verify(self.payer, business=own, number='900100300')
        _passed(self.payer, challenge='light')
        self.assertEqual(_payment_step_up(self.payer, None, own, invoice=_invoice(own)), fsu.FACE_STEP_UP_MESSAGE)
        _passed(self.payer, session='w-2')
        self.assertEqual(_payment_step_up(self.payer, None, own, invoice=_invoice(own)), '')

    def test_exempt_payers(self):
        shop = Business.objects.create(name='Tienda sin KYB')
        # A business payer, and a payer who never did KYC.
        self.assertEqual(_payment_step_up(self.payer, object(), shop), '')
        no_kyc = User.objects.create(username='nokyc', email='nokyc@example.com', firebase_uid='nokyc-uid')
        self.assertEqual(_payment_step_up(no_kyc, None, shop), '')
