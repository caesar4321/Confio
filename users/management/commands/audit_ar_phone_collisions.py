from collections import defaultdict
import json

from django.core.management.base import BaseCommand

from blockchain.algorand_client import get_algod_client
from users.migration_safety import inspect_address_migration_risk
from users.models import Account, User
from users.phone_utils import canonicalize_phone_digits, normalize_phone


class Command(BaseCommand):
    help = (
        "Audit Argentina phone collisions after canonicalizing the optional mobile "
        "`9` variant. Reports duplicate groups and whether they are safe to merge."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of human-readable text.",
        )

    def handle(self, *args, **options):
        algod = get_algod_client()
        users = list(
            User.all_objects.filter(
                deleted_at__isnull=True,
                phone_country="AR",
            ).order_by("created_at", "id")
        )

        groups = defaultdict(list)
        for user in users:
            canonical = canonicalize_phone_digits(user.phone_number or "", user.phone_country or "")
            if canonical:
                groups[canonical].append(user)

        report = []
        for canonical, members in groups.items():
            if len(members) <= 1:
                continue

            members_sorted = sorted(members, key=lambda u: (u.created_at, u.id))
            survivor = members_sorted[-1]  # Newest account wins for merge planning
            member_rows = []
            merge_blockers = []

            for user in members_sorted:
                account = Account.all_objects.filter(
                    user=user,
                    account_type="personal",
                    account_index=0,
                    deleted_at__isnull=True,
                ).first()
                risk = None
                if account and account.algorand_address:
                    risk = inspect_address_migration_risk(algod, account.algorand_address)
                    if risk.get("has_material_risk"):
                        merge_blockers.append(
                            {
                                "user_id": user.id,
                                "username": user.username,
                                "address": account.algorand_address,
                                "relevant_assets": risk.get("relevant_assets", {}),
                                "spendable_algo": risk.get("spendable_algo", 0),
                            }
                        )

                member_rows.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "created_at": user.created_at.isoformat(),
                        "phone_number": user.phone_number,
                        "phone_key": user.phone_key,
                        "canonical_phone_number": canonical,
                        "canonical_phone_key": normalize_phone(user.phone_number or "", user.phone_country or ""),
                        "verification_status": user.verification_status,
                        "account_id": getattr(account, "id", None),
                        "algorand_address": getattr(account, "algorand_address", None),
                        "is_keyless_migrated": getattr(account, "is_keyless_migrated", None),
                        "material_risk": risk,
                    }
                )

            report.append(
                {
                    "canonical_phone_number": canonical,
                    "survivor_user_id": survivor.id,
                    "survivor_username": survivor.username,
                    "eligible_for_merge": len(merge_blockers) == 0,
                    "merge_blockers": merge_blockers,
                    "members": member_rows,
                }
            )

        if options.get("json"):
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return

        if not report:
            self.stdout.write(self.style.SUCCESS("No Argentina phone collisions found."))
            return

        self.stdout.write(self.style.WARNING(f"Found {len(report)} Argentina phone collision groups."))
        for group in report:
            self.stdout.write("")
            self.stdout.write(
                f"Canonical {group['canonical_phone_number']} -> survivor @{group['survivor_username']} "
                f"(user {group['survivor_user_id']})"
            )
            self.stdout.write(f"Eligible for merge: {'yes' if group['eligible_for_merge'] else 'no'}")
            for member in group["members"]:
                self.stdout.write(
                    f"  - user {member['id']} @{member['username']} phone={member['phone_number']} "
                    f"account={member['account_id']} address={member['algorand_address']}"
                )
            if group["merge_blockers"]:
                self.stdout.write("  Merge blockers:")
                for blocker in group["merge_blockers"]:
                    self.stdout.write(
                        f"    - @{blocker['username']} address={blocker['address']} "
                        f"assets={blocker['relevant_assets']} spendable_algo={blocker['spendable_algo']}"
                    )
