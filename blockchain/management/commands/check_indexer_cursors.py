from django.core.management.base import BaseCommand
from django.conf import settings
from blockchain.models import IndexerAssetCursor


class Command(BaseCommand):
    help = (
        "Inspect IndexerAssetCursor rows vs configured assets. "
        "Flags any unknown asset IDs and can optionally delete them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-unknown",
            action="store_true",
            help="Delete any cursor rows not matching configured asset IDs",
        )

    def handle(self, *args, **options):
        # Configured assets (ignore falsy/zero)
        configured = set(
            int(a)
            for a in [
                getattr(settings, "ALGORAND_USDC_ASSET_ID", 0),
                getattr(settings, "ALGORAND_CUSD_ASSET_ID", 0),
                getattr(settings, "ALGORAND_CONFIO_ASSET_ID", 0),
            ]
            if a
        )

        rows = list(
            IndexerAssetCursor.objects.all().values(
                "asset_id", "last_scanned_round", "updated_at"
            ).order_by("asset_id")
        )

        self.stdout.write(self.style.NOTICE("Configured asset IDs:"))
        for aid in sorted(configured):
            self.stdout.write(f"  - {aid}")

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"Found {len(rows)} cursor row(s):"))
        for r in rows:
            mark = ""
            if int(r["asset_id"]) not in configured:
                mark = "  (UNKNOWN)"
            self.stdout.write(
                f"  - asset_id={r['asset_id']}, last_scanned_round={r['last_scanned_round']}, "
                f"updated_at={r['updated_at']}{mark}"
            )

        # Determine unknowns
        unknown = [r for r in rows if int(r["asset_id"]) not in configured]
        if unknown:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Unknown cursors present: {len(unknown)} (not in configured set)."
                )
            )
            # Root-cause hint
            self.stdout.write(
                "Likely cause: a worker/beat running with stale env variables "
                "for asset IDs, which created these rows during a scan."
            )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("No unknown cursors. All match configured asset IDs."))

        if options.get("delete_unknown") and unknown:
            ids = [int(r["asset_id"]) for r in unknown]
            deleted, _ = IndexerAssetCursor.objects.filter(asset_id__in=ids).delete()
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} row(s) for asset_id(s): {ids}"))

