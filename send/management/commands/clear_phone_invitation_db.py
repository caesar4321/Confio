from django.core.management.base import BaseCommand
from django.utils import timezone
from users.phone_utils import normalize_phone
from send.models import SendTransaction
try:
    from send.models import PhoneInvite
except Exception:
    PhoneInvite = None


class Command(BaseCommand):
    help = "Soft-delete DB invite records for a phone so tests can resend without touching on-chain."

    def add_arguments(self, parser):
        parser.add_argument('--phone', required=True, help='Phone number digits (e.g., 9293993619)')
        parser.add_argument('--phone-country', dest='phone_country', default=None, help='ISO code (e.g., US) or calling code (+1)')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without changing data')
        parser.add_argument('--tx-id', dest='tx_id', type=int, default=None, help='Specific SendTransaction ID to clear')

    def handle(self, *args, **options):
        phone = options['phone']
        phone_country = options.get('phone_country')
        dry_run = options.get('dry_run', False)

        phone_key = normalize_phone(phone, phone_country)
        digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
        now = timezone.now()

        self.stdout.write(self.style.NOTICE(f'Cleaning DB invite records for phone_key={phone_key} (digits={digits})'))

        # Clean PhoneInvite rows if model exists
        if PhoneInvite is not None:
            qs_inv = PhoneInvite.objects.filter(phone_key=phone_key, deleted_at__isnull=True)
            count_inv = qs_inv.count()
            if dry_run:
                self.stdout.write(self.style.WARNING(f'[Dry-run] Would soft-delete {count_inv} PhoneInvite row(s)'))
            else:
                for inv in qs_inv:
                    inv.deleted_at = now
                    # Optionally mark as reclaimed to avoid confusion
                    if inv.status == 'pending':
                        inv.status = 'reclaimed'
                    inv.save(update_fields=['deleted_at', 'status', 'updated_at'])
                self.stdout.write(self.style.SUCCESS(f'Soft-deleted {count_inv} PhoneInvite row(s)'))
        else:
            self.stdout.write('PhoneInvite model not present; skipping')

        # Clean SendTransaction invitation rows (soft delete)
        # Option A: direct ID
        tx_id = options.get('tx_id')
        matched = []
        if tx_id:
            tx = SendTransaction.objects.filter(id=tx_id, deleted_at__isnull=True).first()
            if tx:
                matched.append(tx)
        else:
            # Broad search and normalize fields to match various formats
            candidates = SendTransaction.objects.filter(is_invitation=True, deleted_at__isnull=True)
            def clean(s: str | None) -> str:
                return ''.join(ch for ch in (s or '') if ch.isdigit())
            for tx in candidates:
                rp = clean(getattr(tx, 'recipient_phone', ''))
                rd = clean(getattr(tx, 'recipient_display_name', ''))
                # Exact digits or last-10 match
                cond = False
                if rp == digits or rd == digits:
                    cond = True
                elif len(digits) >= 7:
                    # check suffix match (last 7-10)
                    for L in (10, 9, 8, 7):
                        if len(rp) >= L and len(digits) >= L and rp[-L:] == digits[-L:]:
                            cond = True
                            break
                        if len(rd) >= L and len(digits) >= L and rd[-L:] == digits[-L:]:
                            cond = True
                            break
                if cond:
                    matched.append(tx)
        count_tx = len(matched)
        if dry_run:
            self.stdout.write(self.style.WARNING(f'[Dry-run] Would soft-delete {count_tx} SendTransaction row(s): {[t.id for t in matched]}'))
        else:
            for tx in matched:
                tx.deleted_at = now
                tx.save(update_fields=['deleted_at'])
            self.stdout.write(self.style.SUCCESS(f'Soft-deleted {count_tx} SendTransaction row(s): {[t.id for t in matched]}'))

        self.stdout.write(self.style.SUCCESS('Done.'))
