"""
Repair SendTransaction rows that call a real Confío user an external wallet.

The Algorand inbound indexer scan records serverless INTERNAL transfers
(emergency exit, P2P USDC withdrawal) as well as genuine external deposits,
because those transfers have no SendTransaction of their own and the recipient
would otherwise never be notified. Until the accompanying fix, every row it
wrote was stamped sender_type='external' regardless of who actually sent it,
so the history list labels a known Confío user "Billetera externa".

The scan is fixed going forward. This repairs the rows already written.

Usage:
  python manage.py repair_mislabeled_external_senders            # dry run
  python manage.py repair_mislabeled_external_senders --apply

Scope and safety:
  - ONLY rows written by that scan (idempotency_key 'ALG:…'). BSC receipts
    ('BSC:…') and cUSD+ arrivals ('cp:…') are external on purpose.
    backfill_external_deposits writes the same 'ALG:' shape for the same kind
    of row, so its rows are in scope too — deliberately.
  - Only rows whose sender_address resolves to exactly ONE Account. A genuinely
    external deposit matches nothing; an ambiguous address is skipped rather
    than attributed to an arbitrary one of its owners.
  - The sponsor/admin address is skipped: the scan treats its deposits as
    external ON PURPOSE. If that address cannot be resolved, --apply refuses to
    run unless you pass --allow-unknown-sponsor.
  - Relabels sender_type ONLY. It does not set sender_user/sender_business:
    the unified feed scopes personal history with
    Q(sender_user=user) | Q(counterparty_user=user), so linking the sender
    would retroactively publish these recipient-side rows into that user's own
    history as outgoing transfers, duplicating the P2P trade's exchange row.
  - Writes with queryset.update() rather than save(), so no post_save receiver
    fires. save() would re-run handle_first_cusd_on_send_receive, which stamps
    first_cusd_acquired_at from the freshly advanced updated_at and can arm a
    rating prompt for a transaction that settled months ago. The unified row is
    re-synced explicitly instead.
"""
from django.core.management.base import BaseCommand, CommandError

from send.models import SendTransaction
from users.models import Account


class Command(BaseCommand):
    help = 'Repair SendTransaction rows that mislabel a Confío sender as an external wallet.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the repairs. Without this the command only reports.')
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Stop after N repairable rows (0 = no limit).')
        parser.add_argument(
            '--allow-unknown-sponsor', action='store_true',
            help='Proceed with --apply even if the sponsor address cannot be '
                 'resolved. Sponsor-sent rows may then be relabelled.')

    def handle(self, *args, **options):
        apply_changes = bool(options['apply'])
        limit = int(options['limit'])
        allow_unknown_sponsor = bool(options['allow_unknown_sponsor'])

        sponsor_address = None
        try:
            from blockchain.kms_manager import get_kms_signer_from_settings
            sponsor_address = get_kms_signer_from_settings().address
        except Exception:  # noqa: BLE001 — handled below
            pass
        if not sponsor_address:
            message = (
                'Could not resolve the sponsor address. Sponsor deposits are '
                'meant to STAY external, and without the address they cannot '
                'be excluded.')
            if apply_changes and not allow_unknown_sponsor:
                raise CommandError(
                    message + ' Refusing to --apply. Re-run with '
                    '--allow-unknown-sponsor to override.')
            self.stdout.write(self.style.WARNING(message))

        # Provenance filter: only the Algorand inbound scan writes 'ALG:' keys.
        #
        # sender_display_name is the HISTORICAL evidence, and it is what makes
        # this safe. The scan called resolve_sender_name() at write time, so a
        # row it recognised as internal carries the sender's real name while a
        # genuinely external one carries the literal 'Billetera externa' — and
        # backfill_external_deposits hardcodes that same placeholder for every
        # row it writes. Selecting on "has a real name but is typed external"
        # therefore picks out exactly the rows the bug mislabelled, and cannot
        # retroactively re-attribute a historical deposit just because some
        # external depositor's address was registered to an account later.
        candidates = SendTransaction.all_objects.filter(
            sender_type='external',
            sender_user__isnull=True,
            sender_business__isnull=True,
            idempotency_key__startswith='ALG:',
        ).exclude(
            sender_address=''
        ).exclude(
            sender_address__isnull=True
        ).exclude(
            sender_display_name='Billetera externa'
        ).exclude(
            sender_display_name=''
        ).exclude(
            sender_display_name__isnull=True
        )
        if sponsor_address:
            candidates = candidates.exclude(sender_address=sponsor_address)

        total = candidates.count()
        self.stdout.write(f'Examining {total} ALG: external-sender rows...')

        repairable = 0
        repaired = 0
        ambiguous = 0
        failed = 0
        for tx in candidates.iterator():
            addr = (tx.sender_address or '').strip()
            if not addr:
                continue
            # Exactly one owner, or leave it alone: these address columns carry
            # no uniqueness constraint. Count through all_objects — the default
            # manager hides soft-deleted accounts, so an address shared by one
            # live and one deleted account would look unambiguous and get
            # attributed to whoever happens to still be active.
            matches = list(
                Account.all_objects.filter(algorand_address=addr)
                .select_related('user', 'business')[:2]
            )
            if len(matches) > 1:
                ambiguous += 1
                self.stdout.write(self.style.WARNING(
                    f'  {tx.internal_id}: {addr[:10]}… maps to multiple '
                    f'accounts (incl. deleted) — skipped'))
                continue
            if not matches:
                continue  # genuinely external — leave it alone
            account = matches[0]
            if account.deleted_at is not None:
                ambiguous += 1
                self.stdout.write(self.style.WARNING(
                    f'  {tx.internal_id}: {addr[:10]}… belongs only to a '
                    f'deleted account — skipped'))
                continue

            is_business = bool(account.account_type == 'business' and account.business_id)
            new_type = 'business' if is_business else 'user'
            name = (
                account.business.name if is_business
                else (account.user.get_full_name() or account.user.username or '')
                if account.user else ''
            )

            repairable += 1
            self.stdout.write(
                f'  {tx.internal_id} {tx.token_type} {tx.amount} '
                f'from {addr[:10]}… -> {new_type} {name or "?"}')

            if apply_changes:
                fields = {'sender_type': new_type}
                # Only fill the name if it is missing or still the placeholder;
                # the scan already resolved it correctly in most rows.
                if not tx.sender_display_name or tx.sender_display_name == 'Billetera externa':
                    fields['sender_display_name'] = name
                # Both writes or neither. The source row is what this command
                # selects on, so a relabelled row with a stale unified mirror
                # is UNREPAIRABLE by re-running: the next pass no longer sees
                # it as external. create_unified_transaction_from_send also
                # swallows its own errors and returns None rather than raising,
                # so a falsy result has to be treated as the failure it is.
                from django.db import transaction as db_transaction
                from users.signals import create_unified_transaction_from_send
                try:
                    with db_transaction.atomic():
                        # update() — never save(): no post_save receivers, and
                        # updated_at (auto_now) stays at the real settlement
                        # time rather than jumping to now.
                        SendTransaction.all_objects.filter(pk=tx.pk).update(**fields)
                        # Re-READ before syncing: the helper rewrites every
                        # mirrored field from the instance it is handed, so our
                        # pre-update copy would push stale values into the
                        # table the history list reads.
                        fresh = SendTransaction.all_objects.select_related(
                            'sender_user', 'sender_business',
                            'recipient_user', 'recipient_business',
                        ).get(pk=tx.pk)
                        if create_unified_transaction_from_send(fresh) is None:
                            raise RuntimeError('unified sync returned None')
                    repaired += 1
                except Exception as exc:  # noqa: BLE001 — report, keep going
                    failed += 1
                    self.stdout.write(self.style.ERROR(
                        f'  {tx.internal_id}: NOT repaired ({exc}) — rolled '
                        f'back, safe to re-run'))

            if limit and repairable >= limit:
                self.stdout.write(self.style.WARNING(f'Stopping at --limit {limit}'))
                break

        if ambiguous:
            self.stdout.write(self.style.WARNING(
                f'{ambiguous} row(s) skipped for ambiguous sender addresses.'))
        if failed:
            self.stdout.write(self.style.ERROR(
                f'{failed} row(s) FAILED and were rolled back — re-run to '
                f'retry them.'))
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(
                f'Repaired {repaired} of {repairable} mislabeled rows '
                f'({total} examined).'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{repairable} of {total} rows are mislabeled and would be '
                f'repaired. Re-run with --apply to write.'))
