import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Print the AWS Secrets Manager JSON template for Telegram MTProto credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--secret-name', default='prod/telegram-mtproto')

    def handle(self, *args, **options):
        secret_name = options['secret_name']
        payload = {
            'api_id': 123456,
            'api_hash': 'your_api_hash_here',
            'session_string': '',
        }
        self.stdout.write('Create secret:')
        self.stdout.write(
            "aws secretsmanager create-secret "
            f"--region eu-central-2 --name {secret_name} "
            f"--secret-string '{json.dumps(payload)}'"
        )
        self.stdout.write('')
        self.stdout.write('Update secret later after telegram_print_session returns a session_string:')
        payload['session_string'] = 'long_session_string_here'
        self.stdout.write(
            "aws secretsmanager put-secret-value "
            f"--region eu-central-2 --secret-id {secret_name} "
            f"--secret-string '{json.dumps(payload)}'"
        )
