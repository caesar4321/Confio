from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import Business, Account, User
from payroll.models import PayrollRecipient
from users.models_employee import BusinessEmployee

class Command(BaseCommand):
    help = 'Ensure each business owner is added as a payroll recipient using their personal account (index 0).'

    def handle(self, *args, **options):
        added = 0
        skipped = 0
        missing_account = 0
        try:
            businesses = Business.objects.all()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to load businesses: {e}"))
            return

        for biz in businesses:
            owner_emp = BusinessEmployee.objects.filter(
                business=biz,
                role__iexact='owner',
                is_active=True,
                deleted_at__isnull=True,
            ).select_related('user').first()
            if not owner_emp or not owner_emp.user:
                skipped += 1
                continue

            user: User = owner_emp.user
            personal = Account.objects.filter(
                user=user,
                account_type='personal',
                account_index=0,
                deleted_at__isnull=True,
            ).first()
            if not personal:
                missing_account += 1
                continue

            try:
                with transaction.atomic():
                    obj, created = PayrollRecipient.objects.get_or_create(
                        business=biz,
                        recipient_user=user,
                        recipient_account=personal,
                        defaults={'display_name': f"{user.first_name} {user.last_name}".strip() or user.username or 'Propietario'},
                    )
                    if created:
                        added += 1
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"Failed for business {biz.id}: {e}"))
                continue

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Added: {added}, skipped (no owner): {skipped}, missing personal account: {missing_account}"))
