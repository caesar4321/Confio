from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0022_edd_forwarded_terminal')]
    operations = [migrations.CreateModel(
        name='AutomaticPayin',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('status', models.CharField(max_length=20, default='pending', choices=[('pending', 'Pending'), ('started', 'Started'), ('review', 'Review')])),
            ('reason', models.CharField(max_length=100, blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('entry', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='automatic_payin', to='payment_accounts.ledgerentry')),
        ])]
