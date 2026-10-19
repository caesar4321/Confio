"""Ask people on app builds too old for the update gate to update.

Builds before 5.2.6 ignore AppVersionPolicy.minimum_version (no blocking
screen) and some predate even the dismissible prompt. The server still
knows each device's version (FCMToken.app_version, refreshed on register),
so they can be reached by push + an in-app notification, which every build
renders. Typical use at the stock-fee cutover:

    manage.py notify_outdated_builds --below 5.2.6            # dry run: counts
    manage.py notify_outdated_builds --below 5.2.6 --send     # sends

A person is targeted only when their MOST RECENTLY ACTIVE device (any
platform; `updated_at`, which only app-start registration moves: a push
delivery's queryset update never touches it) is below the version, so
someone who already updated on their main phone is left alone. Once per run.
Older builds can't open a store link from a notification, so the text itself
says where to update. Dry run is the default; sending is outward-facing and
needs an explicit --send.
"""
from django.core.management.base import BaseCommand, CommandError

STORE_URLS = {
    'android': 'https://play.google.com/store/apps/details?id=com.Confio.Confio',
    'ios': 'https://apps.apple.com/app/id6472662314',
}
STORE_NAMES = {'android': 'Google Play', 'ios': 'la App Store'}
DEFAULT_TITLE = 'Actualiza Confío'
DEFAULT_MESSAGE = (
    'Tu versión de Confío ya no es compatible con algunas funciones, como la compra y venta de '
    'acciones. Abre {store}, busca Confío y toca Actualizar.'
)


class Command(BaseCommand):
    help = 'Push + in-app notice to people whose main device runs a build below --below'

    def add_arguments(self, parser):
        parser.add_argument('--below', required=True, help='Target devices with app_version < this, e.g. 5.2.6')
        parser.add_argument('--platform', choices=('ios', 'android', 'all'), default='all')
        parser.add_argument('--title', default=DEFAULT_TITLE)
        parser.add_argument('--message', default=DEFAULT_MESSAGE)
        parser.add_argument('--limit', type=int, default=0, help='Cap the number of people (0 = no cap)')
        parser.add_argument('--send', action='store_true', help='Actually send (default: dry run)')

    def handle(self, *args, **options):
        from notifications.models import FCMDeviceToken, NotificationType
        from notifications.utils import create_notification
        from security.face_client import _version

        below = _version(options['below'])
        if below is None:
            raise CommandError(f"unparseable --below {options['below']!r}")
        platforms = ('ios', 'android') if options['platform'] == 'all' else (options['platform'],)

        # The newest active device per user, across ALL platforms, decides;
        # --platform then only narrows who is notified.
        latest = {}
        for token in (FCMDeviceToken.objects.filter(is_active=True, device_type__in=('ios', 'android'))
                      .order_by('user_id', '-updated_at', '-id')
                      .only('user_id', 'device_type', 'app_version', 'updated_at')):
            latest.setdefault(token.user_id, token)
        targets = []
        unknown = 0
        for user_id, token in latest.items():
            if token.device_type not in platforms:
                continue
            version = _version(token.app_version)
            if version is None:
                unknown += 1  # never guess: an unreadable version is not "old"
                continue
            if version < below:
                targets.append((user_id, token.device_type, token.app_version))
        if options['limit']:
            targets = targets[:options['limit']]

        by_version = {}
        for _uid, platform, version in targets:
            by_version[(platform, version)] = by_version.get((platform, version), 0) + 1
        self.stdout.write(f"People whose main device is below {options['below']}: {len(targets)} "
                          f"(skipped {unknown} with an unreadable version)")
        for (platform, version), count in sorted(by_version.items()):
            self.stdout.write(f'  {platform} {version}: {count}')
        if not options['send']:
            self.stdout.write(self.style.WARNING('DRY RUN: nothing sent. Re-run with --send.'))
            return

        from users.models import User

        users = User.objects.in_bulk([uid for uid, _p, _v in targets])
        sent = 0
        for user_id, platform, version in targets:
            user = users.get(user_id)
            if user is None:
                continue
            create_notification(
                user=user,
                notification_type=NotificationType.ANNOUNCEMENT,
                title=options['title'],
                message=options['message'].format(store=STORE_NAMES[platform]),
                # Not an action_url: older builds route unknown links nowhere.
                data={'kind': 'outdated_build', 'below': options['below'], 'reported_version': version,
                      'store_url': STORE_URLS[platform]},
                send_push=True,
            )
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'Notified {sent} people.'))
