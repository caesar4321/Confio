"""Tag existing Google Play pre-launch robot accounts (analytics only).

Same rule as security/platform_test_accounts.py: a session from a Google
network on a device that never produced a valid App Check token.
Dry run by default; --apply writes.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from security.models import IPDeviceUser
from security.platform_test_accounts import device_never_passed_app_check, is_google_network


class Command(BaseCommand):
    help = 'Tag Google Play pre-launch robot accounts so analytics excludes them.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the tags (default: dry run).')

    def handle(self, *args, **options):
        User = get_user_model()
        candidates = set()
        rows = (IPDeviceUser.objects.select_related('ip_address', 'device_fingerprint')
                .filter(user__is_platform_test_account=False))
        for row in rows.iterator():
            ip = getattr(row.ip_address, 'ip_address', '')
            fingerprint = getattr(row.device_fingerprint, 'fingerprint', '')
            if is_google_network(ip) and device_never_passed_app_check(fingerprint):
                candidates.add(row.user_id)
        self.stdout.write(f'{len(candidates)} pre-launch robot account(s): {sorted(candidates)}')
        if options['apply'] and candidates:
            updated = User.all_objects.filter(pk__in=candidates).update(is_platform_test_account=True)
            self.stdout.write(self.style.SUCCESS(f'Tagged {updated}.'))
        elif not options['apply']:
            self.stdout.write('Dry run: re-run with --apply to tag.')
