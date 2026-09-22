from django.contrib import admin
from django.test import SimpleTestCase

from send.admin import SendTransactionAdmin
from send.models import SendTransaction


class SendSenderDisplayTests(SimpleTestCase):
    def setUp(self):
        self.model_admin = SendTransactionAdmin(SendTransaction, admin.site)

    def test_savings_credit_displays_its_name_without_a_wallet(self):
        row = SendTransaction(sender_type='external', sender_address='',
                              sender_display_name='Ahorro acreditado', token_type='CUSD_PLUS')
        self.assertIn('Ahorro acreditado', self.model_admin.sender_display(row))

    def test_external_wallet_address_takes_precedence_over_generic_name(self):
        row = SendTransaction(sender_type='external', sender_address='0x' + 'a' * 40,
                              sender_display_name='Depósito externo')
        result = self.model_admin.sender_display(row)
        self.assertIn('0xaaaaaaaa...aaaaaa', result)
        self.assertNotIn('Depósito externo', result)

    def test_missing_sender_has_an_explicit_fallback(self):
        row = SendTransaction(sender_type='external', sender_address='', sender_display_name='')
        self.assertIn('Unknown Sender', self.model_admin.sender_display(row))

    def test_sender_name_is_html_escaped(self):
        row = SendTransaction(sender_type='external', sender_address='',
                              sender_display_name='<script>alert(1)</script>')
        result = self.model_admin.sender_display(row)
        self.assertNotIn('<script>', result)
        self.assertIn('&lt;script&gt;', result)
