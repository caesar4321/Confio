from decimal import Decimal
from django.db import migrations
from django.utils import timezone


def create_pending_placeholders(apps, schema_editor):
    ReferralRewardEvent = apps.get_model("achievements", "ReferralRewardEvent")
    UserReferral = apps.get_model("achievements", "UserReferral")

    referrals = UserReferral.objects.select_related(
        "referred_user", "referrer_user"
    ).all()

    def ensure_event(user, referral, role, stage, reward_amount):
        if not user:
            return
        event, created = ReferralRewardEvent.objects.get_or_create(
            user=user,
            trigger="referral_pending",
            defaults={
                "referral": referral,
                "actor_role": role,
                "amount": Decimal("0"),
                "transaction_reference": "",
                "occurred_at": referral.created_at or timezone.now(),
                "reward_status": "pending",
                "referee_confio": reward_amount if role == "referee" else Decimal("0"),
                "referrer_confio": reward_amount if role == "referrer" else Decimal("0"),
                "metadata": {"stage": stage},
            },
        )
        if not created and event.referral_id != referral.id:
            event.referral = referral
            event.save(update_fields=["referral", "updated_at"])

    for referral in referrals:
        ensure_event(
            referral.referred_user,
            referral,
            "referee",
            "pending_first_transaction",
            referral.reward_referee_confio or Decimal("0"),
        )
        ensure_event(
            referral.referrer_user,
            referral,
            "referrer",
            "pending_referrer_bonus",
            referral.reward_referrer_confio or Decimal("0"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("achievements", "0007_mark_claimed_events"),
    ]

    operations = [
        migrations.RunPython(
            create_pending_placeholders,
            migrations.RunPython.noop,
        ),
    ]
