from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('achievements', '0005_userreferral_reward_box_name_and_more'),
        ('users', '0002_last_activity_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReferralRewardEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger', models.CharField(help_text='Evento que activó la recompensa (send, payment, etc.)', max_length=40)),
                ('actor_role', models.CharField(choices=[('referrer', 'Referrer'), ('referee', 'Referee')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=6, default=0, max_digits=19, help_text='Monto asociado con el evento (ej. USDC convertido)')),
                ('transaction_reference', models.CharField(blank=True, help_text='Hash o ID de referencia para el evento', max_length=128)),
                ('occurred_at', models.DateTimeField()),
                ('reward_status', models.CharField(choices=[('pending', 'Pendiente'), ('eligible', 'Elegible'), ('failed', 'Fallido'), ('skipped', 'Omitido')], default='pending', max_length=20)),
                ('referee_confio', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('referrer_confio', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('reward_tx_id', models.CharField(blank=True, max_length=128)),
                ('error', models.TextField(blank=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('referral', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reward_events', to='achievements.userreferral')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='referral_reward_events', to='users.user')),
            ],
            options={
                'ordering': ['-occurred_at'],
                'verbose_name': 'Referral Reward Event',
                'verbose_name_plural': 'Referral Reward Events',
            },
        ),
        migrations.AddConstraint(
            model_name='referralrewardevent',
            constraint=models.UniqueConstraint(fields=('user', 'trigger'), name='unique_first_reward_event_per_trigger'),
        ),
        migrations.AddIndex(
            model_name='referralrewardevent',
            index=models.Index(fields=['user', 'trigger', 'reward_status'], name='reward_event_lookup'),
        ),
    ]
