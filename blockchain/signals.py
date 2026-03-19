from django.db.models.signals import post_save
from django.dispatch import receiver

from conversion.models import Conversion
from usdc_transactions.models import USDCDeposit

from blockchain.auto_swap_state import ensure_pending_usdc_auto_swap, sync_pending_auto_swap_from_conversion


@receiver(post_save, sender=USDCDeposit)
def create_pending_auto_swap_for_usdc_deposit(sender, instance, **kwargs):
    ensure_pending_usdc_auto_swap(instance)


@receiver(post_save, sender=Conversion)
def sync_pending_auto_swap_for_conversion(sender, instance, **kwargs):
    sync_pending_auto_swap_from_conversion(instance)
