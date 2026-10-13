import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Print the SSM Parameter Store command for Telegram MTProto credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--secret-name', default='prod/telegram-mtproto')

    def handle(self, *args, **options):
        # config.secrets.get_secret('prod/x') reads the SecureString /confio/secrets/prod/x.
        parameter = f"/confio/secrets/{options['secret_name']}"
        payload = {
            'api_id': 123456,
            'api_hash': 'your_api_hash_here',
            'session_string': '',
        }
        self.stdout.write('Create parameter:')
        self.stdout.write(
            "aws ssm put-parameter --type SecureString "
            f"--region eu-central-2 --name {parameter} "
            f"--value '{json.dumps(payload)}'"
        )
        self.stdout.write('')
        self.stdout.write('Update it later after telegram_print_session returns a session_string:')
        payload['session_string'] = 'long_session_string_here'
        self.stdout.write(
            "aws ssm put-parameter --type SecureString --overwrite "
            f"--region eu-central-2 --name {parameter} "
            f"--value '{json.dumps(payload)}'"
        )
        self.stdout.write('')
        self.stdout.write('Restart the services afterwards — each process loads parameters once at startup.')
