#!/usr/bin/env python
"""
Backfill missing ReferralRewardEvent records for pending referrals.

Bug: The signal in achievements/signals.py was using get_or_create with only
(user, trigger="referral_pending") but missing the referral field. This caused
users with multiple referrals to have only ONE pending event instead of one per referral.

This script creates the missing pending events for all active referrals.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from achievements.models import UserReferral, ReferralRewardEvent
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q

def backfill_pending_events():
    """Create missing pending events for all referrals."""

    # Find all active/pending referrals
    referrals = UserReferral.objects.filter(
        Q(status='pending') | Q(status='active'),
        deleted_at__isnull=True,
    ).select_related('referred_user', 'referrer_user')

    print(f"Found {referrals.count()} active/pending referrals")

    created_referee = 0
    created_referrer = 0

    for referral in referrals:
        # Check if referee event exists
        if referral.referred_user:
            referee_event, created = ReferralRewardEvent.objects.get_or_create(
                user=referral.referred_user,
                trigger="referral_pending",
                referral=referral,
                defaults={
                    "actor_role": "referee",
                    "amount": Decimal("0"),
                    "transaction_reference": "",
                    "occurred_at": referral.created_at or timezone.now(),
                    "reward_status": (referral.referee_reward_status or "pending").lower(),
                    "referee_confio": referral.reward_referee_confio or Decimal("0"),
                    "referrer_confio": Decimal("0"),
                    "metadata": {"stage": "pending_first_transaction"},
                }
            )
            if created:
                created_referee += 1
                print(f"  ✓ Created referee event for referral {referral.id} (user {referral.referred_user.id})")

        # Check if referrer event exists
        if referral.referrer_user:
            referrer_event, created = ReferralRewardEvent.objects.get_or_create(
                user=referral.referrer_user,
                trigger="referral_pending",
                referral=referral,
                defaults={
                    "actor_role": "referrer",
                    "amount": Decimal("0"),
                    "transaction_reference": "",
                    "occurred_at": referral.created_at or timezone.now(),
                    "reward_status": (referral.referrer_reward_status or "pending").lower(),
                    "referee_confio": Decimal("0"),
                    "referrer_confio": referral.reward_referrer_confio or Decimal("0"),
                    "metadata": {"stage": "pending_referrer_bonus"},
                }
            )
            if created:
                created_referrer += 1
                print(f"  ✓ Created referrer event for referral {referral.id} (user {referral.referrer_user.id})")

    print(f"\n✅ Backfill complete!")
    print(f"   Created {created_referee} referee events")
    print(f"   Created {created_referrer} referrer events")
    print(f"   Total: {created_referee + created_referrer} new events")

if __name__ == "__main__":
    backfill_pending_events()
