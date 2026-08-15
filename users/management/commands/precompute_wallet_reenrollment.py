from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Precompute all legacy wallet reenrollment assessments before mobile rollout.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        from users.models import Account
        from users.tasks import assess_wallet_reenrollment_account
        from users.web3auth_schema import _wallet_reenrollment_assessment

        candidates = Account.objects.filter(
            account_type='personal',
            account_index=0,
            algorand_address__isnull=False,
            is_keyless_migrated=False,
            deleted_at__isnull=True,
        ).only(
            'id',
            'algorand_address',
            'bsc_address',
            'wallet_reenrollment_assessment',
        ).order_by('id')
        limit = max(0, int(options.get('limit') or 0))
        account_ids = []
        for account in candidates.iterator(chunk_size=200):
            if _wallet_reenrollment_assessment(account):
                continue
            account_ids.append(account.id)
            if limit and len(account_ids) >= limit:
                break

        results = {}
        for account_id in account_ids:
            status = assess_wallet_reenrollment_account.run(account_id)
            results[status] = results.get(status, 0) + 1

        remaining = 0
        remaining_candidates = Account.objects.filter(
            account_type='personal',
            account_index=0,
            algorand_address__isnull=False,
            is_keyless_migrated=False,
            deleted_at__isnull=True,
        ).only(
            'id',
            'algorand_address',
            'bsc_address',
            'wallet_reenrollment_assessment',
        )
        for account in remaining_candidates.iterator(chunk_size=200):
            if not _wallet_reenrollment_assessment(account):
                remaining += 1
        self.stdout.write(
            self.style.SUCCESS(
                f'wallet reenrollment assessments: processed={len(account_ids)} '
                f'results={results} remaining={remaining}'
            )
        )
        if remaining:
            raise CommandError(
                'Wallet reenrollment prewarm is incomplete; do not release the mobile client yet.'
            )
