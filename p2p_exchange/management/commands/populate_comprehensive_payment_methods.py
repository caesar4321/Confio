from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deprecated alias for populate_payment_methods. Keeps the Koywe-only catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hard-delete-unsupported",
            action="store_true",
            help="Permanently delete unsupported payment methods after deactivating them.",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "populate_comprehensive_payment_methods is deprecated. Running Koywe-only payment method sync instead."
            )
        )
        call_command(
            "populate_payment_methods",
            hard_delete_unsupported=options["hard_delete_unsupported"],
        )
