"""Employee invitations by @usuario name the account (employee_user) and keep
no copy of its verified number. Existing ones are linked to the account the
username names, and lose the number that was copied from it."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def link_username_invitations(apps, schema_editor):
    Invitation = apps.get_model('users', 'EmployeeInvitation')
    User = apps.get_model('users', 'User')
    seen_pending = set()
    rows = Invitation.objects.exclude(employee_username__isnull=True).exclude(employee_username='').order_by('-created_at')
    for inv in rows.iterator():
        # The copied number goes whatever happens below.
        fields = {'employee_phone': '', 'employee_phone_country': '', 'employee_phone_key': None}
        live = inv.status == 'pending' and inv.deleted_at is None
        # Usernames change and get reused: the account is the invitee only if
        # it still holds the number that was copied from the invitee.
        user = User.objects.filter(username__iexact=inv.employee_username.lstrip('@')).first()
        proven = bool(user and inv.employee_phone_key and user.phone_key == inv.employee_phone_key)
        if proven and (not live or (inv.business_id, user.pk) not in seen_pending):
            fields['employee_user'] = user
            if live:
                seen_pending.add((inv.business_id, user.pk))
        elif live:
            # Unproven (or a duplicate): it can no longer reach anyone safely.
            fields['status'] = 'cancelled'
        Invitation.objects.filter(pk=inv.pk).update(**fields)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0059_location_readings'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='employeeinvitation',
            name='unique_pending_invitation_per_phone',
        ),
        migrations.AddField(
            model_name='employeeinvitation',
            name='employee_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='employee_invitations_received', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(link_username_invitations, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='employeeinvitation',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'pending'), ('deleted_at__isnull', True), models.Q(('employee_phone', ''), _negated=True)), fields=('business', 'employee_phone', 'employee_phone_country'), name='unique_pending_invitation_per_phone'),
        ),
        migrations.AddConstraint(
            model_name='employeeinvitation',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'pending'), ('employee_user__isnull', False), ('deleted_at__isnull', True)), fields=('business', 'employee_user'), name='unique_pending_invitation_per_user'),
        ),
    ]
