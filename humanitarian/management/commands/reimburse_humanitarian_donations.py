from django.core.management.base import BaseCommand, CommandError

from humanitarian.models import HumanitarianDonation
from humanitarian.services import HumanitarianReleaseService


class Command(BaseCommand):
    help = 'Reimburse confirmed humanitarian donations back to their donors on-chain.'

    def add_arguments(self, parser):
        parser.add_argument('--campaign', required=True, help='Campaign slug')
        parser.add_argument('--donation-id', type=int, help='Reimburse a single donation by id')
        parser.add_argument('--all', action='store_true', help='Reimburse every confirmed, not-yet-reimbursed donation')
        parser.add_argument('--dry-run', action='store_true', help='List what would be reimbursed without submitting')

    def handle(self, *args, **options):
        if not options['donation_id'] and not options['all']:
            raise CommandError('Pass --donation-id or --all')

        donations = HumanitarianDonation.objects.filter(
            campaign__slug=options['campaign'],
            status='confirmed',
        ).select_related('campaign', 'donor_user').order_by('donated_at')
        if options['donation_id']:
            donations = donations.filter(id=options['donation_id'])
            if not donations.exists():
                raise CommandError(f'No confirmed donation {options["donation_id"]} in campaign {options["campaign"]}')

        pending = [d for d in donations if not hasattr(d, 'reimbursement') or d.reimbursement.status in ('draft', 'failed')]
        skipped = [d for d in donations if d not in pending]
        for d in skipped:
            self.stdout.write(f'SKIP donation {d.id} ({d.amount} cUSD, {d.donor_user or d.donor_display_name}): already {d.reimbursement.status}')

        if options['dry_run']:
            for d in pending:
                self.stdout.write(f'WOULD reimburse donation {d.id}: {d.amount} cUSD -> {d.from_address} ({d.donor_user or d.donor_display_name})')
            self.stdout.write(f'Total: {sum(d.amount for d in pending)} cUSD across {len(pending)} donation(s)')
            return

        service = HumanitarianReleaseService()
        ok = failed = 0
        for d in pending:
            try:
                txid = service.reimburse_donation(d)
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f'FAILED donation {d.id} ({d.amount} cUSD): {exc}'))
                continue
            ok += 1
            self.stdout.write(self.style.SUCCESS(f'REIMBURSED donation {d.id}: {d.amount} cUSD -> {d.from_address} tx={txid}'))
        self.stdout.write(f'Done: {ok} reimbursed, {failed} failed, {len(skipped)} skipped')
