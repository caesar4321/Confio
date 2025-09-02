from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


DEFAULT_APPS = [
    # Core contrib apps that depend on AUTH_USER_MODEL
    'admin',
    'auth',
    'contenttypes',
    'sessions',
    'users',
    'achievements',
    'security',
    'telegram_verification',
    'sms_verification',
    'send',
    'payments',
    'p2p_exchange',
    'exchange_rates',
    'conversion',
    'usdc_transactions',
    'presale',
    'notifications',
    'blockchain',
]


class Command(BaseCommand):
    help = (
        "Delete migration history rows from django_migrations for the given apps, "
        "so you can run 'migrate --fake-initial' cleanly without dropping data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apps',
            type=str,
            default=','.join(DEFAULT_APPS),
            help='Comma-separated app labels to reset (default: common local apps).',
        )
        parser.add_argument(
            '--noinput',
            action='store_true',
            help='Do not prompt for confirmation.',
        )

    def handle(self, *args, **options):
        apps_arg = options['apps']
        noinput = options['noinput']
        apps = [a.strip() for a in apps_arg.split(',') if a.strip()]

        if not apps:
            raise CommandError('No apps provided to reset.')

        self.stdout.write(self.style.WARNING(
            'This will DELETE migration history rows in django_migrations for:\n  - ' + '\n  - '.join(apps)
        ))
        self.stdout.write(self.style.WARNING(
            'It will NOT drop tables or data. It only resets migration history.'
        ))

        if not noinput:
            confirm = input('Type "YES" to continue: ').strip()
            if confirm != 'YES':
                raise CommandError('Aborted by user.')

        placeholders = ','.join(['%s'] * len(apps))
        sql = f"DELETE FROM django_migrations WHERE app IN ({placeholders})"

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, apps)

        self.stdout.write(self.style.SUCCESS('Migration history reset complete.'))
        self.stdout.write(self.style.SUCCESS('Next: run "python manage.py migrate --fake-initial"'))
