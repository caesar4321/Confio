import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from payroll.models import PayrollRecipient
from users.models_employee import BusinessEmployee
from users.models import Account

logger = logging.getLogger(__name__)


def _get_personal_account(user):
    try:
        return Account.objects.filter(user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()
    except Exception:
        return None


@receiver(post_save, sender=BusinessEmployee)
def ensure_payroll_recipient_for_employee(sender, instance, **kwargs):
    """Auto-create payroll recipient when an employee is active; remove when deactivated/deleted."""
    try:
        business = instance.business
        user = instance.user
        should_have = instance.is_active and instance.deleted_at is None

        if should_have:
            account = _get_personal_account(user)
            if not account:
                return
            with transaction.atomic():
                PayrollRecipient.objects.get_or_create(
                    business=business,
                    recipient_user=user,
                    recipient_account=account,
                    defaults={'display_name': user.get_full_name() or user.username}
                )
        else:
            PayrollRecipient.objects.filter(
                business=business,
                recipient_user=user,
                deleted_at__isnull=True
            ).update(deleted_at=timezone.now())
    except Exception:
        logger.exception("Error syncing payroll recipient for employee %s", instance.id)
