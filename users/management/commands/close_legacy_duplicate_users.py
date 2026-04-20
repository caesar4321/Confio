from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from blockchain.algorand_client import get_algod_client
from users.migration_safety import inspect_address_migration_risk
from users.models import Account, User


class Command(BaseCommand):
    help = "Soft-delete legacy duplicate users and their accounts after reviewing on-chain risk."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            action="append",
            dest="usernames",
            required=True,
            help="Username to close. Can be passed multiple times.",
        )
        parser.add_argument(
            "--allow-material-risk",
            action="store_true",
            help="Allow closing even when the legacy address still has material risk.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview closures without saving changes.",
        )

    def handle(self, *args, **options):
        usernames = options.get("usernames") or []
        dry_run = bool(options.get("dry_run"))
        allow_material_risk = bool(options.get("allow_material_risk"))
        algod = get_algod_client()

        for username in usernames:
            user = User.all_objects.filter(username=username, deleted_at__isnull=True).first()
            if not user:
                raise CommandError(f"Active user @{username} not found.")

            accounts = list(
                Account.all_objects.filter(user=user, deleted_at__isnull=True).order_by("account_type", "account_index")
            )
            if not accounts:
                self.stdout.write(self.style.WARNING(f"@{username}: no active accounts found; soft-deleting user only."))

            for account in accounts:
                risk = None
                if account.algorand_address:
                    risk = inspect_address_migration_risk(algod, account.algorand_address)

                self.stdout.write(
                    f"@{username} account={account.id} type={account.account_type}:{account.account_index} "
                    f"address={account.algorand_address} risk={risk}"
                )

                if risk and risk.get("has_material_risk") and not allow_material_risk:
                    raise CommandError(
                        f"Refusing to close @{username}; address {account.algorand_address} still has material risk. "
                        "Re-run with --allow-material-risk if this is intentional."
                    )

            if dry_run:
                continue

            with transaction.atomic():
                for account in accounts:
                    account.soft_delete()
                user.soft_delete()

            self.stdout.write(self.style.SUCCESS(f"Closed @{username} ({len(accounts)} account(s) soft-deleted)."))
