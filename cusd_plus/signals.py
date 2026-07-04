# Referral activation for savings deposits.
#
# The referral reward normally fires as two events: a USDCDeposit >= $19
# records the `top_up` checkpoint (usdc_transactions/signals.py) and a
# completed usdc_to_cusd Conversion pays out (users/signals.py). A user who
# moves money straight into their savings (cUSD -> cUSD+, or a savings-rail
# top-up that lands as a to_savings conversion) never touches that path, yet
# it is the same economic act. Owner decision 2026-07-05: a completed
# to_savings conversion of >= $19 activates the referral reward too.
#
# We fire the SAME two event slugs in order, so the vault config, duplicate
# guards, and notifications in achievements/services/referral_rewards.py
# apply unchanged.

import logging
from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import CusdPlusConversion

logger = logging.getLogger(__name__)

REFERRAL_MIN_USD = Decimal('19')


@receiver(pre_save, sender=CusdPlusConversion)
def cache_previous_conversion_status(sender, instance, **kwargs):
    if instance.pk:
        previous = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
        instance._previous_status = previous
    else:
        instance._previous_status = None


@receiver(post_save, sender=CusdPlusConversion)
def handle_savings_conversion_referral(sender, instance, created, **kwargs):
    """Completed to_savings conversion >= $19 activates the referral reward."""
    try:
        previous_status = getattr(instance, '_previous_status', None)
        just_completed = instance.status == 'COMPLETED' and previous_status != 'COMPLETED'
        if not (
            just_completed
            and instance.direction == 'to_savings'
            and instance.actor_user_id
            and Decimal(instance.amount_usd) >= REFERRAL_MIN_USD
        ):
            return

        from achievements.services.referral_rewards import (
            EventContext,
            sync_referral_reward_for_event,
        )

        logger.info(
            'Referral savings activation: user=%s conversion=%s amount=%s',
            instance.actor_user_id,
            instance.internal_id,
            instance.amount_usd,
        )

        metadata = {
            'cusd_plus_conversion_id': str(instance.internal_id),
            'source': 'cusd_plus_to_savings',
        }
        amount = Decimal(instance.amount_usd)

        # Checkpoint first, then the paying event — same order as the
        # deposit + conversion path. Duplicate guards in the service make
        # both calls no-ops if the user already activated another way.
        sync_referral_reward_for_event(
            instance.actor_user,
            EventContext(event='top_up', amount=amount, metadata=metadata),
        )
        sync_referral_reward_for_event(
            instance.actor_user,
            EventContext(event='conversion_usdc_to_cusd', amount=amount, metadata=metadata),
        )
    except Exception:
        logger.exception(
            'Error processing referral reward for cUSD+ conversion %s', instance.pk,
        )
