from django.db import migrations
from django.utils import timezone


def mark_existing_claimed_events(apps, schema_editor):
    Event = apps.get_model("achievements", "ReferralRewardEvent")
    Transaction = apps.get_model("achievements", "ConfioRewardTransaction")

    reference_ids = Transaction.objects.filter(
        reference_type="referral_claim",
    ).values_list("reference_id", flat=True)

    claimed_ids = []
    for ref_id in reference_ids:
        try:
            claimed_ids.append(int(ref_id))
        except (TypeError, ValueError):
            continue

    if not claimed_ids:
        return

    Event.objects.filter(
        id__in=claimed_ids,
        reward_status="eligible",
    ).update(
        reward_status="claimed",
        updated_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("achievements", "0006_referralrewardevent"),
    ]

    operations = [
        migrations.RunPython(
            mark_existing_claimed_events,
            migrations.RunPython.noop,
        ),
    ]
