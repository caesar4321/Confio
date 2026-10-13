"""get_secret reads /confio/secrets/* from Parameter Store, falling back to Secrets Manager."""
import unittest
from unittest import mock

from botocore.exceptions import ClientError

from config import secrets


class GetSecretTests(unittest.TestCase):
    def setUp(self):
        secrets.get_secret.cache_clear()
        secrets._parameter_secrets_cache.clear()
        self.addCleanup(secrets.get_secret.cache_clear)
        self.addCleanup(secrets._parameter_secrets_cache.clear)
        session = mock.patch('config.secrets.boto3.session.Session')
        self.ssm, self.sm = mock.Mock(), mock.Mock()
        clients = {'ssm': self.ssm, 'secretsmanager': self.sm}
        session.start().return_value.client.side_effect = lambda service_name, region_name, **kw: clients[service_name]
        self.addCleanup(session.stop)
        self.pages = [{'Parameters': [
            {'Name': '/confio/secrets/prod/twilio-api', 'Value': '{"sid": "AC1"}'},
            {'Name': '/confio/secrets/prod/django-secret', 'Value': 'plain-value'},
        ]}]
        self.ssm.get_paginator.return_value.paginate.side_effect = lambda **kw: iter(self.pages)

    def test_reads_parameters_in_one_bulk_load(self):
        self.assertEqual(secrets.get_secret('prod/twilio-api'), {'sid': 'AC1'})
        self.assertEqual(secrets.get_secret('prod/django-secret'), 'plain-value')
        self.ssm.get_paginator.return_value.paginate.assert_called_once_with(
            Path='/confio/secrets/', Recursive=True, WithDecryption=True,
        )
        self.sm.get_secret_value.assert_not_called()

    def test_parameter_created_after_startup_is_found_without_restart(self):
        secrets.get_secret('prod/twilio-api')  # snapshot loaded
        self.ssm.get_parameter.return_value = {'Parameter': {'Value': '{"bot_token": "t"}'}}
        self.assertEqual(secrets.get_secret('prod/ops-alert-telegram'), {'bot_token': 't'})
        self.ssm.get_parameter.assert_called_once_with(
            Name='/confio/secrets/prod/ops-alert-telegram', WithDecryption=True,
        )
        self.sm.get_secret_value.assert_not_called()

    def test_missing_parameter_falls_back_to_secrets_manager(self):
        self.ssm.get_parameter.side_effect = ClientError(
            {'Error': {'Code': 'ParameterNotFound', 'Message': ''}}, 'GetParameter',
        )
        self.sm.get_secret_value.return_value = {'SecretString': '{"password": "pw"}'}
        self.assertEqual(secrets.get_secret('RDS_SECRET'), {'password': 'pw'})
        self.sm.get_secret_value.assert_called_once_with(SecretId='RDS_SECRET')
        self.ssm.get_parameter.assert_not_called()  # Secrets Manager-only by design

    def test_unknown_name_tries_parameter_then_secrets_manager(self):
        self.ssm.get_parameter.side_effect = ClientError(
            {'Error': {'Code': 'ParameterNotFound', 'Message': ''}}, 'GetParameter',
        )
        self.sm.get_secret_value.return_value = {'SecretString': 'legacy'}
        self.assertEqual(secrets.get_secret('prod/not-migrated'), 'legacy')
        self.ssm.get_parameter.assert_called_once()

    def test_failed_bulk_load_falls_back_and_is_not_cached(self):
        self.ssm.get_paginator.return_value.paginate.side_effect = ClientError(
            {'Error': {'Code': 'ThrottlingException', 'Message': ''}}, 'GetParametersByPath',
        )
        self.sm.get_secret_value.return_value = {'SecretString': 'from-sm'}
        self.assertEqual(secrets.get_secret('prod/telegram-bot'), 'from-sm')
        self.assertNotIn('eu-central-2', secrets._parameter_secrets_cache)


if __name__ == '__main__':
    unittest.main()
