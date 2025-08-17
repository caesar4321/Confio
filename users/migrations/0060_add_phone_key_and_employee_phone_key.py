from django.db import migrations, models


def backfill_user_phone_keys(apps, schema_editor):
    User = apps.get_model('users', 'User')
    from users.country_codes import COUNTRY_CODES  # safe to import constants
    from users.phone_utils import normalize_phone
    for u in User.objects.all():
        if getattr(u, 'phone_number', None):
            try:
                # phone_country stores ISO (e.g., 'US'); normalize_phone accepts ISO or calling code
                key = normalize_phone(u.phone_number or '', u.phone_country or '')
                if key:
                    u.phone_key = key
                    u.save(update_fields=['phone_key'])
            except Exception:
                continue


def backfill_employee_phone_keys(apps, schema_editor):
    EI = apps.get_model('users', 'EmployeeInvitation')
    from users.phone_utils import normalize_phone
    for inv in EI.objects.all():
        try:
            key = normalize_phone(inv.employee_phone or '', inv.employee_phone_country or '')
            if key:
                inv.employee_phone_key = key
                inv.save(update_fields=['employee_phone_key'])
        except Exception:
            continue


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0059_add_pending_blockchain_status'),
    ]

    atomic = False

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE users_user ADD COLUMN IF NOT EXISTS phone_key varchar(32) NULL"
                    ),
                    reverse_sql=(
                        "ALTER TABLE users_user DROP COLUMN IF EXISTS phone_key"
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE users_employeeinvitation ADD COLUMN IF NOT EXISTS employee_phone_key varchar(32) NULL"
                    ),
                    reverse_sql=(
                        "ALTER TABLE users_employeeinvitation DROP COLUMN IF EXISTS employee_phone_key"
                    ),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='user',
                    name='phone_key',
                    field=models.CharField(blank=True, max_length=32, null=True, help_text='Canonical phone key for uniqueness across ISO variations'),
                ),
                migrations.AddField(
                    model_name='employeeinvitation',
                    name='employee_phone_key',
                    field=models.CharField(blank=True, max_length=32, null=True, help_text='Canonical phone key (callingcode:digits) for the invited employee'),
                ),
            ],
        ),
        migrations.RunPython(backfill_user_phone_keys, migrations.RunPython.noop),
        migrations.RunPython(backfill_employee_phone_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                fields=['phone_key'],
                name='unique_user_phone_key_active',
                condition=models.Q(phone_key__isnull=False) & models.Q(deleted_at__isnull=True),
            ),
        ),
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['phone_key'], name='idx_user_phone_key'),
        ),
        migrations.AddIndex(
            model_name='employeeinvitation',
            index=models.Index(fields=['employee_phone_key', 'status'], name='idx_invitation_phonekey_status'),
        ),
        migrations.AddConstraint(
            model_name='employeeinvitation',
            constraint=models.UniqueConstraint(
                fields=['business', 'employee_phone_key'],
                name='unique_pending_invitation_per_phonekey',
                condition=models.Q(status='pending') & models.Q(employee_phone_key__isnull=False) & models.Q(deleted_at__isnull=True),
            ),
        ),
    ]
