from collections import Counter

from django.core.management.base import BaseCommand

from payroll.models import PayrollRun


class Command(BaseCommand):
    help = "Recompute PayrollRun.status from child PayrollItems (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the recomputed statuses. If omitted, only prints differences.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of runs processed (most recent first).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        limit = options.get("limit")

        qs = PayrollRun.objects.order_by("-created_at")
        if limit:
            qs = qs[:limit]

        updated = 0
        scanned = 0
        for run in qs:
            items_qs = run.items.filter(deleted_at__isnull=True)
            statuses = list(items_qs.values_list("status", flat=True))
            if not statuses:
                continue
            scanned += 1

            counts = Counter(statuses)
            status_set = set(statuses)
            new_status = run.status

            if status_set == {"CONFIRMED"}:
                new_status = "COMPLETED"
            elif status_set.issubset({"PENDING"}):
                new_status = "READY"
            elif status_set.issubset({"FAILED", "CANCELLED"}):
                new_status = "CANCELLED"
            elif status_set.intersection({"CONFIRMED", "SUBMITTED", "PREPARED"}):
                new_status = "PARTIAL"

            if new_status != run.status:
                self.stdout.write(
                    f"[{run.run_id}] {run.status} -> {new_status} | items={dict(counts)}"
                )
                if apply_changes:
                    run.status = new_status
                    run.save(update_fields=["status", "updated_at"])
                    updated += 1

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Updated {updated} runs (scanned {scanned})."))
        else:
            self.stdout.write(self.style.WARNING(f"Dry-run complete. {scanned} runs scanned; rerun with --apply to persist."))
