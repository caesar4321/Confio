from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from users.country_codes import COUNTRY_CODES
import boto3
import uuid
import time


class Command(BaseCommand):
    help = (
        "Register an alphanumeric Sender ID for multiple countries via Pinpoint SMS and Voice v2.\n"
        "Examples:\n"
        "  manage.py register_sender_ids --sender-id CONFIO --exclude US,CA\n"
        "  manage.py register_sender_ids --sender-id CONFIO --countries CO,VE,PE,EC,PA,AR,ES,CH\n"
        "  manage.py register_sender_ids --sender-id CONFIO --dry-run\n"
    )

    def add_arguments(self, parser):
        parser.add_argument('--sender-id', default=None, help='Sender ID to register (defaults to SMS_SENDER_ID setting)')
        parser.add_argument('--countries', default=None, help='Comma-separated ISO country codes (if omitted, uses all from COUNTRY_CODES)')
        parser.add_argument('--exclude', default='US,CA', help='Comma-separated ISO country codes to exclude (default: US,CA)')
        parser.add_argument('--dry-run', action='store_true', help='List targets without performing registration')
        parser.add_argument('--sleep', type=float, default=0.0, help='Optional sleep seconds between API calls to avoid throttling')

    def handle(self, *args, **opts):
        sender_id = opts['sender_id'] or getattr(settings, 'SMS_SENDER_ID', None)
        if not sender_id:
            raise CommandError('Sender ID not provided; set --sender-id or SMS_SENDER_ID in settings/env.')

        region = getattr(settings, 'SMS_SNS_REGION', 'eu-central-2')
        client = boto3.client('pinpoint-sms-voice-v2', region_name=region)

        if opts['countries']:
            iso_list = [c.strip().upper() for c in opts['countries'].split(',') if c.strip()]
        else:
            # Use all ISO codes available in COUNTRY_CODES
            iso_list = sorted({row[2].upper() for row in COUNTRY_CODES if len(row) >= 3})

        exclude = {c.strip().upper() for c in (opts['exclude'] or '').split(',') if c.strip()}
        targets = [c for c in iso_list if c not in exclude]

        self.stdout.write(self.style.NOTICE(f"Region: {region}"))
        self.stdout.write(self.style.NOTICE(f"Sender ID: {sender_id}"))
        self.stdout.write(self.style.NOTICE(f"Countries to process: {len(targets)} (excluded: {', '.join(sorted(exclude)) or '-'} )"))

        if opts['dry_run']:
            self.stdout.write("Dry run — listing targets only:")
            self.stdout.write(','.join(targets))
            return

        ok = 0
        skipped = 0
        failed = 0
        for iso in targets:
            try:
                resp = client.request_sender_id(
                    SenderId=sender_id,
                    IsoCountryCode=iso,
                    MessageTypes=['TRANSACTIONAL'],
                    DeletionProtectionEnabled=False,
                    ClientToken=str(uuid.uuid4()),
                )
                status = resp.get('Status', 'PENDING') if isinstance(resp, dict) else 'PENDING'
                self.stdout.write(self.style.SUCCESS(f"Requested Sender ID '{sender_id}' for {iso} → status: {status}"))
                ok += 1
            except Exception as e:
                # If already exists or duplicate, treat as skipped
                msg = str(e)
                if 'ConflictException' in msg or 'already exists' in msg or 'Duplicate' in msg:
                    self.stdout.write(self.style.WARNING(f"Already exists/registered for {iso}; skipping."))
                    skipped += 1
                else:
                    self.stdout.write(self.style.ERROR(f"Failed for {iso}: {e}"))
                    failed += 1
            if opts['sleep']:
                time.sleep(opts['sleep'])

        self.stdout.write(self.style.SUCCESS(f"Done. ok={ok}, skipped={skipped}, failed={failed}"))
