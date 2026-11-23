from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('assistant', '0014_assistant_memory')]

    operations = [
        migrations.AddField(
            model_name='gmailconnection', name='can_calendar', field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name='gmailconnection', name='calendar_checked_on', field=models.DateField(blank=True, null=True)),
        migrations.AddField(
            model_name='gmailconnection', name='last_urgent_on', field=models.DateField(blank=True, null=True)),
        migrations.AlterField(
            model_name='mailneed', name='kind',
            field=models.CharField(max_length=12, choices=[
                ('payment', 'Pago'), ('ticket', 'Pasaje o entrada'), ('trip', 'Viaje'), ('deadline', 'Vencimiento'),
                ('reply', 'Correo por responder'), ('appointment', 'Cita o reunión'), ('delivery', 'Entrega'),
                ('money', 'Dinero recibido o por recibir')])),
    ]
