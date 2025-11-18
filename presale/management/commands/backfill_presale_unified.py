from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from presale.models import PresalePurchase
from users.models_unified import UnifiedTransactionTable


class Command(BaseCommand):
    help = "Backfill UnifiedTransactionTable entries for completed presale purchases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database",
        )
        parser.add_argument(
            "--purchase-id",
            type=int,
            help="Optionally limit to a single PresalePurchase ID",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        purchase_id = options.get("purchase_id")

        purchases = PresalePurchase.objects.filter(status="completed")
        if purchase_id:
            purchases = purchases.filter(id=purchase_id)

        vault_address = getattr(settings, "ALGORAND_PRESALE_VAULT_ADDRESS", "") or "ConfioPresaleVault"

        total = purchases.count()
        created = 0
        skipped = 0

        for purchase in purchases.select_related("user", "phase"):
            ref = f"presale_purchase:{purchase.id}"
            exists = UnifiedTransactionTable.objects.filter(
                transaction_type="presale",
                payment_reference_id=ref,
            ).exists()
            if exists:
                skipped += 1
                continue

            user = purchase.user
            user_display = user.get_full_name() or user.username or user.email or "Tú"
            amount_str = format(purchase.confio_amount.normalize(), "f")
            description = f"Compra de preventa Fase {getattr(purchase.phase, 'phase_number', '')}".strip()

            defaults = {
                "amount": amount_str,
                "token_type": "CONFIO",
                "status": "CONFIRMED",
                "transaction_hash": purchase.transaction_hash or "",
                "error_message": "",
                "sender_user": None,
                "sender_business": None,
                "sender_type": "external",
                "sender_display_name": "Confío Preventa",
                "sender_phone": "",
                "sender_address": vault_address,
                "counterparty_user": user,
                "counterparty_business": None,
                "counterparty_type": "user",
                "counterparty_display_name": user_display,
                "counterparty_phone": "",
                "counterparty_address": purchase.from_address or "",
                "description": description,
                "invoice_id": None,
                "payment_reference_id": ref,
                "payment_transaction_id": None,
                "from_address": vault_address,
                "to_address": purchase.from_address or "",
                "is_invitation": False,
                "invitation_claimed": False,
                "invitation_reverted": False,
                "invitation_expires_at": None,
                "transaction_date": purchase.completed_at or timezone.now(),
            }

            if dry_run:
                self.stdout.write(f"[DRY RUN] Would create unified transaction for purchase {purchase.id}")
            else:
                UnifiedTransactionTable.objects.update_or_create(
                    transaction_type="presale",
                    payment_reference_id=ref,
                    defaults=defaults,
                )
            created += 1

        created_msg = created if not dry_run else f"0 (would create {created})"
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {total} purchases → created {created_msg} entries, skipped {skipped}"
            )
        )
