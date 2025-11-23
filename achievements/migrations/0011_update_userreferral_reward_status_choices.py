from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("achievements", "0010_userreferral_dual_reward_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userreferral",
            name="reward_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("eligible", "Elegible"),
                    ("failed", "Fallido"),
                    ("skipped", "Omitido"),
                    ("claimed", "Reclamado"),
                ],
                default="pending",
                help_text="Estado de elegibilidad en la bóveda on-chain",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="userreferral",
            name="referee_reward_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("eligible", "Elegible"),
                    ("failed", "Fallido"),
                    ("skipped", "Omitido"),
                    ("claimed", "Reclamado"),
                ],
                default="pending",
                help_text="Estado on-chain específico para el referido",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="userreferral",
            name="referrer_reward_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("eligible", "Elegible"),
                    ("failed", "Fallido"),
                    ("skipped", "Omitido"),
                    ("claimed", "Reclamado"),
                ],
                default="pending",
                help_text="Estado on-chain específico para el referidor",
                max_length=20,
            ),
        ),
    ]
