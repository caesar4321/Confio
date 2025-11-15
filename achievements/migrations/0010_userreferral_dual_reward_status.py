from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("achievements", "0009_alter_referralrewardevent_reward_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="userreferral",
            name="referee_reward_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("eligible", "Elegible"),
                    ("failed", "Fallido"),
                ],
                default="pending",
                help_text="Estado on-chain específico para el referido",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="userreferral",
            name="referrer_reward_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("eligible", "Elegible"),
                    ("failed", "Fallido"),
                ],
                default="pending",
                help_text="Estado on-chain específico para el referidor",
                max_length=20,
            ),
        ),
    ]
