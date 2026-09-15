from unittest import mock

from django.test import SimpleTestCase, override_settings

from payment_accounts.clients import InfiniaClient


@override_settings(INFINIA_SECRET_ID='id', INFINIA_SECRET_PASSWORD='secret', INFINIA_COMPANY_ID='',
                   PAYMENT_PROVIDER_TIMEOUT_SECONDS=20, LOCAL_MONEY_VALIDATION_TIMEOUT_SECONDS=8)
class RecipientLookupTimeoutTests(SimpleTestCase):
    def client_with(self, session):
        session.request.return_value = mock.Mock(
            ok=True, status_code=200, text='', json=lambda: {'status': 'success', 'data': {'id': 'v1'}})
        return InfiniaClient(session=session)

    def test_recipient_lookups_use_the_short_timeout(self):
        session = mock.Mock()
        client = self.client_with(session)
        client.create_bank_account_validation({'country': 'MX'})
        self.assertEqual(session.request.call_args.kwargs['timeout'], 8)
        client.get_bank_account_validation('v1')
        self.assertEqual(session.request.call_args.kwargs['timeout'], 8)

    def test_other_calls_keep_the_provider_timeout(self):
        session = mock.Mock()
        client = self.client_with(session)
        client.get_account_limits('a1')
        self.assertEqual(session.request.call_args.kwargs['timeout'], 20)
