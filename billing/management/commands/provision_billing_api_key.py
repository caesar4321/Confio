from django.core.management.base import BaseCommand, CommandError

from billing.api.authentication import (
    SUPPORTED_SCOPES,
    create_business_api_key,
)
from users.models import Business


class Command(BaseCommand):
    help = 'Provision an institutional billing API key and print it once.'

    def add_arguments(self, parser):
        parser.add_argument('--business-id', type=int, required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--mode', choices=('test', 'live'), default='test')
        parser.add_argument(
            '--scope', action='append', dest='scopes', required=True,
            choices=sorted(SUPPORTED_SCOPES),
            help='Repeat for every scope granted to this key.')

    def handle(self, *args, **options):
        try:
            business = Business.objects.get(id=options['business_id'])
        except Business.DoesNotExist as exc:
            raise CommandError('Business not found.') from exc
        try:
            row, token = create_business_api_key(
                business=business, name=options['name'], mode=options['mode'],
                scopes=options['scopes'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f'Created {row.public_id} for business {business.id} ({row.mode}).')
        self.stdout.write('Copy this key now; it cannot be recovered:')
        self.stdout.write(token)
