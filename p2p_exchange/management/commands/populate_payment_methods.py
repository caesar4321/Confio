from django.core.management.base import BaseCommand
from django.db.models.deletion import ProtectedError
from django.db import transaction

from ramps.koywe import (
    deactivate_unsupported_payment_methods,
    get_country_ramp_config,
    get_supported_country_codes,
    sync_all_country_payment_methods,
)
from p2p_exchange.models import P2PPaymentMethod


class Command(BaseCommand):
    help = "Sync P2P payment methods to the Koywe-supported catalog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hard-delete-unsupported",
            action="store_true",
            help="Permanently delete unsupported payment methods after deactivating them.",
        )

    def handle(self, *args, **options):
        hard_delete_unsupported = options["hard_delete_unsupported"]

        with transaction.atomic():
            deactivated_count = deactivate_unsupported_payment_methods()
            synced_methods = sync_all_country_payment_methods()

            deleted_count = 0
            if hard_delete_unsupported:
                unsupported_methods = []
                for payment_method in P2PPaymentMethod.objects.filter(is_active=False):
                    config = get_country_ramp_config(payment_method.country_code)
                    supported_names = {
                        method["code"].lower().replace("-", "_")
                        for method in (config or {}).get("methods", [])
                    }
                    if payment_method.name not in supported_names:
                        unsupported_methods.append(payment_method.pk)
                if unsupported_methods:
                    protected_count = 0
                    for payment_method in P2PPaymentMethod.objects.filter(pk__in=unsupported_methods):
                        try:
                            with transaction.atomic():
                                payment_method.delete()
                            deleted_count += 1
                        except ProtectedError:
                            protected_count += 1
                    if protected_count:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Unsupported payment methods kept inactive because they are referenced by historical records: {protected_count}"
                            )
                        )

        self.stdout.write(self.style.SUCCESS("Koywe payment method sync complete."))
        self.stdout.write(f"Supported countries: {', '.join(get_supported_country_codes(include_empty_methods=False))}")
        self.stdout.write(f"Active Koywe payment methods synced: {len(synced_methods)}")
        self.stdout.write(f"Unsupported payment methods deactivated: {deactivated_count}")
        if hard_delete_unsupported:
            self.stdout.write(f"Unsupported payment methods deleted: {deleted_count}")
