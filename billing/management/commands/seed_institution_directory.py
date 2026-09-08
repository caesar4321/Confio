"""Seed a discoverable institution so members can find their colegio in-app.

Deliberately separate from setup_cip_sandbox_pilot: that command wires a
merchant user, a receiving BSC address, a roster member and a due, because it
seeds a payable pilot. A directory entry needs none of that. It is the name a
member sees while looking for their institution, and it must be creatable long
before anyone can pay through it.

The entry is listed but NOT linkable until its connection carries a
verification_url, status='active' and live_approved. That derivation lives in
the resolver, so seeding cannot accidentally advertise readiness.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from billing.models import InstitutionConnection
from users.models import Business


class Command(BaseCommand):
    help = 'Idempotently create a listed (not yet linkable) institution directory entry.'

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True, help='Institution name as members will read it')
        parser.add_argument('--provider', required=True, help='Connector slug, e.g. cip')

    @transaction.atomic
    def handle(self, *args, **options):
        name = options['name'].strip()
        provider = options['provider'].strip().lower()
        if not name or len(name) > 200:
            raise CommandError('--name must contain 1 to 200 characters')
        if not provider.replace('-', '').replace('_', '').isalnum():
            raise CommandError('--provider must be a slug')

        businesses = Business.objects.filter(name=name, deleted_at__isnull=True)
        if businesses.count() > 1:
            raise CommandError(f'{businesses.count()} live businesses already named {name!r}')
        business = businesses.first() or Business.objects.create(name=name, category='services')

        connection, created = InstitutionConnection.objects.get_or_create(
            business=business, provider=provider, mode='live',
            # Defaults keep it listed but unlinkable: no endpoint, not approved.
            defaults={'status': 'sandbox', 'live_approved': False},
        )
        linkable = bool(
            connection.verification_url and connection.status == 'active'
            and connection.live_approved)
        self.stdout.write(
            f'{"created" if created else "already present"}: {name} '
            f'({provider}, {connection.public_id}) '
            f'linking_available={linkable}'
        )
