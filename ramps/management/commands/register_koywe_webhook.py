from django.conf import settings
from django.core.management.base import BaseCommand

from ramps.koywe_client import KoyweClient, KoyweError


class Command(BaseCommand):
    help = 'Register or update the Koywe webhook URL for this environment'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            type=str,
            default='https://confio.lat/api/koywe/webhook/',
            help='Webhook URL to register (default: https://confio.lat/api/koywe/webhook/)',
        )
        parser.add_argument(
            '--secret',
            type=str,
            default=None,
            help='Webhook secret. If omitted, uses KOYWE_WEBHOOK_SECRET from settings.',
        )

    def handle(self, *args, **options):
        client = KoyweClient()
        if not client.is_configured:
            self.stderr.write(self.style.ERROR('Koywe credentials are not configured'))
            return

        url = options['url']
        secret = options['secret'] or getattr(settings, 'KOYWE_WEBHOOK_SECRET', '') or ''

        self.stdout.write(f'Registering webhook with Koywe...')
        self.stdout.write(f'  Environment: {getattr(settings, "KOYWE_ENV", "unknown")}')
        self.stdout.write(f'  API URL:     {client.base_url}')
        self.stdout.write(f'  Webhook URL: {url}')
        self.stdout.write(f'  Secret:      {"(provided)" if secret else "(none)"}')

        try:
            result = client.register_webhook(url=url, secret=secret or None)
            self.stdout.write(self.style.SUCCESS(f'Webhook registered successfully: {result}'))
        except KoyweError as exc:
            self.stderr.write(self.style.ERROR(f'Failed to register webhook: {exc}'))
