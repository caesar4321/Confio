from django.core.management.base import BaseCommand
from send.models import PhoneInvite


class Command(BaseCommand):
    help = "Inspect pending PhoneInvite rows for a given phone key or digits"

    def add_arguments(self, parser):
        parser.add_argument('--phone-key', dest='phone_key', help='Canonical phone key cc:digits')
        parser.add_argument('--digits', dest='digits', help='Raw digits to match against phone_number')

    def handle(self, *args, **opts):
        phone_key = (opts.get('phone_key') or '').strip()
        digits = (opts.get('digits') or '').strip()

        if not phone_key and not digits:
            self.stderr.write('Provide --phone-key or --digits')
            return

        qs = PhoneInvite.objects.filter(status='pending', deleted_at__isnull=True)
        if phone_key:
            qs = qs.filter(phone_key=phone_key)
        if digits:
            qs = qs.filter(phone_number=digits)

        count = qs.count()
        self.stdout.write(f'Found {count} pending PhoneInvite row(s)')
        for inv in qs.order_by('-created_at')[:50]:
            self.stdout.write(
                f'- id={inv.id} invitation_id={inv.invitation_id} phone_key={inv.phone_key} '
                f'phone_number={inv.phone_number} country={inv.phone_country} status={inv.status}'
            )

