"""
Inspect a user's wallet-recovery options.

Used to triage cases like percybeltran@gmail.com where a user reports their
wallet isn't recovering on Google sign-in. The output tells support whether
the user can recover simply by signing in with iOS (Apple) — i.e. whether
Firebase has Apple linked to their UID and we have an Algorand address
already bound — or whether they need the Drive picker / manual recovery.

Usage:
    myvenv/bin/python manage.py inspect_wallet_recovery --email user@example.com
    myvenv/bin/python manage.py inspect_wallet_recovery --firebase-uid xxx
"""

from django.core.management.base import BaseCommand, CommandError

from users.models import User
from security.models import UserSession, IntegrityVerdict


class Command(BaseCommand):
    help = "Dump every signal we have about a user's wallet/backup history."

    def add_arguments(self, parser):
        parser.add_argument('--email', help='Email address to look up')
        parser.add_argument('--firebase-uid', help='Firebase UID to look up')

    def handle(self, *args, **options):
        email = options.get('email')
        firebase_uid = options.get('firebase_uid')
        if not email and not firebase_uid:
            raise CommandError('Pass --email or --firebase-uid')

        qs = User.all_objects.all()
        if email:
            qs = qs.filter(email__iexact=email)
        if firebase_uid:
            qs = qs.filter(firebase_uid=firebase_uid)
        rows = list(qs)

        if not rows:
            self.stdout.write(self.style.WARNING('No User rows found.'))
            return

        self.stdout.write(self.style.NOTICE(
            f'Found {len(rows)} User row(s). Note: Apple Sign-In and Google Sign-In '
            f'produce different Firebase UIDs unless the user explicitly linked '
            f'them, so multiple rows for the same person are normal.'
        ))

        try:
            from firebase_admin import auth as fb_auth
        except Exception as e:
            fb_auth = None
            self.stdout.write(self.style.WARNING(f'firebase_admin not importable: {e}'))

        for u in rows:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'--- User id={u.id}  firebase_uid={u.firebase_uid} ---'
            ))
            self.stdout.write(f'  email                = {u.email}')
            self.stdout.write(f'  username             = {u.username}')
            self.stdout.write(f'  deleted_at           = {u.deleted_at}')
            self.stdout.write(f'  date_joined          = {u.date_joined}')
            self.stdout.write(f'  last_login           = {u.last_login}')
            self.stdout.write(f'  platform_os          = {u.platform_os}  (set on signup only)')
            self.stdout.write(f'  backup_provider      = {u.backup_provider}')
            self.stdout.write(f'  backup_verified_at   = {u.backup_verified_at}')
            self.stdout.write(f'  backup_device_name   = {u.backup_device_name}')

            # Firebase linked providers — the smoking gun for "did he ever
            # sign in with Apple?". If 'apple.com' is present, recovery via
            # iOS Apple Sign-In is the right path.
            providers = []
            if fb_auth is not None:
                try:
                    fb_user = fb_auth.get_user(u.firebase_uid)
                    providers = [p.provider_id for p in (fb_user.provider_data or [])]
                    self.stdout.write(f'  firebase email       = {fb_user.email}')
                    self.stdout.write(f'  firebase email_verified = {fb_user.email_verified}')
                    self.stdout.write(f'  firebase providers   = {providers}')
                    md = fb_user.user_metadata
                    self.stdout.write(f'  firebase created     = {md.creation_timestamp}')
                    self.stdout.write(f'  firebase last signin = {md.last_sign_in_timestamp}')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f'  firebase lookup failed: {e}'
                    ))

            # Session OS history — secondary signal. iOS sessions confirm
            # the user actually got the app running on an iPhone/iPad.
            os_values = list(
                UserSession.objects.filter(user=u)
                .exclude(os_name='')
                .values_list('os_name', flat=True)
                .distinct()
            )
            self.stdout.write(f'  UserSession os_name  = {os_values}')

            # Play Integrity verdicts only fire on Android. Presence implies
            # Android use; absence is consistent with iOS-only.
            iv_count = IntegrityVerdict.objects.filter(user=u).count()
            self.stdout.write(f'  IntegrityVerdict ct  = {iv_count}  (Android-only signal)')

            # Algorand addresses currently bound. If a non-null address
            # exists, "sign in with Apple" only recovers if the derived
            # wallet matches one of these. Otherwise we'd hit the
            # address-mismatch guard during login.
            accounts = u.accounts.all()
            for acc in accounts:
                self.stdout.write(
                    f'  account id={acc.id} type={acc.account_type} '
                    f'index={acc.account_index} algorand_address={acc.algorand_address}'
                )

            # Verdict
            has_apple = 'apple.com' in providers
            has_google = any('google' in p for p in providers)
            has_icloud_backup = u.backup_provider == 'icloud'
            has_ios_session = any('ios' in (s or '').lower() or 'iphone' in (s or '').lower()
                                  or 'ipad' in (s or '').lower() for s in os_values)

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('  Verdict:'))
            if has_apple and (has_icloud_backup or has_ios_session):
                self.stdout.write(self.style.SUCCESS(
                    '    Apple Sign-In is linked AND we have evidence of iOS use. '
                    'Easiest recovery: have the user tap "Continuar con Apple" on '
                    'an iPhone with the same iCloud account. The V2 master secret '
                    'will be restored from iCloud Keychain (or Drive if enabled), '
                    'and the derived address should match this account.'
                ))
            elif has_apple:
                self.stdout.write(self.style.WARNING(
                    '    Apple is linked at Firebase but we have no iCloud/iOS '
                    'history on this User row. The Apple sign-in may create a '
                    'SEPARATE Firebase UID with no Algorand address bound — '
                    'check Firebase Console for another UID under this email.'
                ))
            elif has_google and not has_apple:
                self.stdout.write(self.style.WARNING(
                    '    Google-only — iOS sign-in path is NOT available. '
                    'Recovery requires Google Drive picker (Profile > Respaldo '
                    'en Nube) on a device where the user still has the local '
                    'secret OR access to their Drive backup.'
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    '    Insufficient signal — review the raw fields above.'
                ))
