"""Run the same durable sandbox operations as the staff console."""
import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ramps.stereum_client import StereumError
from ramps.stereum_service import FIELDS, execute, refresh


class Command(BaseCommand):
    help = 'Exercise Stereum sandbox using server-configured credentials. Never credits wallets.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=[*FIELDS, 'refresh'])
        parser.add_argument('--actor', required=True, help='Existing active superuser username.')
        parser.add_argument('--request-id', help='Stable UUID; reuse for retries. Required for refresh.')
        parser.add_argument('--payload-file', help='JSON object. Do not include credentials.')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options['actor']).first()
        if actor is None:
            raise CommandError('Administrator not found.')
        try:
            data = {}
            if options['payload_file']:
                with open(options['payload_file']) as source:
                    data = json.load(source)
            if options['action'] == 'refresh':
                if not options['request_id']:
                    raise StereumError('--request-id is required for refresh.')
                result = refresh(actor, options['request_id'])
            else:
                identifier = options['request_id'] or str(uuid.uuid4())
                # Emit before the network call so a lost response can be recovered.
                self.stdout.write('Request ID: ' + identifier)
                result = execute(actor, options['action'], data, identifier)
        except (StereumError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps({
            'requestId': str(result.request_id), 'status': result.status,
            'providerId': result.provider_id, 'error': result.error,
            'response': result.response_data,
        }, indent=2, ensure_ascii=False))
        if result.status in {'failed', 'unknown'}:
            raise CommandError('Request did not complete successfully; inspect the saved operation.')
