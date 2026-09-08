from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from billing.models import (
    BillingOutboxMessage, InstitutionApplication, InstitutionConnection,
    WebhookDelivery,
)


class Command(BaseCommand):
    help = 'Institutional billing configuration checks and queue ages (not release certification).'

    def handle(self, *args, **options):
        self.stdout.write('SCOPE configuration only; correction/refund workflow and device/load certification remain release gates')
        checks = []
        checks.append(('API key pepper', bool(settings.BILLING_API_KEY_PEPPER)))
        checks.append(('institution token key', bool(settings.BILLING_INSTITUTION_TOKEN_KEY)))
        live_connections = InstitutionConnection.objects.filter(
            mode='live', status='active')
        incomplete = live_connections.filter(live_approved=False).count()
        incomplete += sum(
            not (item.settlement_authority and item.refund_authority
                 and item.application_url)
            for item in live_connections.filter(live_approved=True))
        checks.append(('live institution authority', bool(live_connections) and incomplete == 0))
        checks.append(('live API explicitly enabled', bool(settings.BILLING_LIVE_API_KEYS_ENABLED)))

        now = timezone.now()
        oldest_outbox = BillingOutboxMessage.objects.filter(
            status__in=('pending', 'failed')).order_by('available_at').first()
        oldest_webhook = WebhookDelivery.objects.filter(
            status__in=('pending', 'retrying', 'leased')).order_by('available_at').first()
        oldest_application = InstitutionApplication.objects.filter(
            status='application_pending').order_by('available_at').first()

        for name, passed in checks:
            self.stdout.write(f'{"PASS" if passed else "BLOCK"} {name}')
        for label, row in (
                ('outbox', oldest_outbox), ('webhook', oldest_webhook),
                ('institution_application', oldest_application)):
            age = int((now - row.available_at).total_seconds()) if row else 0
            self.stdout.write(f'BACKLOG {label} oldest_due_age_seconds={max(age, 0)}')
        if not all(passed for _, passed in checks):
            raise CommandError('institutional billing is not live-ready')
