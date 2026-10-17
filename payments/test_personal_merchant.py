"""Personal accounts accept Pay like a business: same invoice, same 0.9%."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from payments.bsc_flow import _payment_step_up
from payments.models import Invoice
from payments.schema import CreateInvoice, InvoiceType
from payments.test_payment_face_step_up import _verify
from security import face_step_up as fsu
from users.models import Account, Business

User = get_user_model()
SELLER_BSC = '0x' + '5' * 40


class CreatePersonalInvoiceTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create(
            username='rosa', email='rosa@example.com', firebase_uid='rosa-uid',
            first_name='Rosa', last_name='Mendoza')
        self.account = Account.objects.create(
            user=self.seller, account_type='personal', account_index=0, bsc_address=SELLER_BSC)

    def create(self, chain='BSC', account_type='personal', business_id=None, **extra):
        request = RequestFactory().post('/graphql')
        request.user = self.seller
        info = SimpleNamespace(context=request)
        ctx = {'account_type': account_type, 'account_index': 0, 'business_id': business_id}
        data = dict(amount='12.50', token_type='CUSD_PLUS', settlement_chain=chain,
                    description='Arepas', expires_in_hours=None, **extra)
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation',
                        return_value=ctx):
            return CreateInvoice.mutate(None, info, SimpleNamespace(**data))

    def test_personal_account_creates_a_charge(self):
        result = self.create()
        self.assertTrue(result.success, result.errors)
        invoice = result.invoice
        self.assertIsNone(invoice.merchant_business)
        self.assertEqual(invoice.merchant_type, 'user')
        self.assertEqual(invoice.merchant_account, self.account)
        self.assertEqual(invoice.merchant_display_name, 'Rosa Mendoza')
        self.assertEqual(invoice.settlement_chain, 'BSC')
        self.assertIn('Rosa Mendoza', str(invoice))

    def test_personal_charge_is_bsc_only(self):
        result = self.create(chain='ALGORAND')
        self.assertFalse(result.success)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_personal_charge_needs_a_bsc_address(self):
        self.account.bsc_address = ''
        self.account.save(update_fields=['bsc_address'])
        result = self.create()
        self.assertEqual(result.errors, ['merchant_not_ready'])

    def test_business_charge_unchanged(self):
        shop = Business.objects.create(name='Bodega La 22')
        Account.objects.create(user=self.seller, account_type='business', account_index=0,
                               business=shop, bsc_address='0x' + '6' * 40)
        result = self.create(account_type='business', business_id=shop.id)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.invoice.merchant_business, shop)
        self.assertEqual(result.invoice.merchant_type, 'business')
        self.assertEqual(result.invoice.merchant_display_name, 'Bodega La 22')

    def test_merchant_verified_follows_the_persons_id(self):
        invoice = self.create().invoice
        self.assertFalse(InvoiceType.resolve_merchant_verified(invoice, None))
        _verify(self.seller, number='1065000999')
        self.assertTrue(InvoiceType.resolve_merchant_verified(invoice, None))


@override_settings(FACE_STEP_UP_ENABLED=True)
class PersonalMerchantFaceStepUpTests(TestCase):
    """Paying a person follows Send's rule: Confío Face for a KYC'd payer, verified seller or not."""

    def setUp(self):
        self.payer = User.objects.create(username='payer', email='payer@example.com', firebase_uid='payer-uid')
        _verify(self.payer)
        self.seller = User.objects.create(username='seller', email='seller@example.com', firebase_uid='seller-uid')
        account = Account.objects.create(user=self.seller, account_type='personal', account_index=0)
        self.invoice = SimpleNamespace(
            merchant_business=None, merchant_business_id=None, merchant_account=account,
            amount='10', token_type='CUSD_PLUS')

    def test_a_verified_person_asks_too_and_a_light_check_is_enough(self):
        from security.models import FaceCheck
        from django.utils import timezone
        _verify(self.seller, number='1065000200')
        self.assertEqual(_payment_step_up(self.payer, None, None, invoice=self.invoice), fsu.FACE_STEP_UP_MESSAGE)
        FaceCheck.objects.create(user=self.payer, purpose='withdrawal', liveness_session_id='p-1', status='passed',
                                 challenge='light', completed_at=timezone.now())
        self.assertEqual(_payment_step_up(self.payer, None, None, invoice=self.invoice), '')

    def test_charging_yourself_needs_the_full_check(self):
        from payments.bsc_flow import _payment_face_terms
        self.invoice.merchant_account.user = self.payer
        self.assertTrue(_payment_face_terms(self.payer, self.invoice)['cash_out'])

    def test_business_payer_exempt_as_before(self):
        self.assertEqual(_payment_step_up(self.payer, object(), None, invoice=self.invoice), '')
