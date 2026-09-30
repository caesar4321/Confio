from django.db import migrations, models


def backfill(apps, schema_editor):
    # Same hash as security.models.banned_phone_hash, for the number
    # each already-banned account holds now.
    from security.models import banned_phone_hash
    UserBan = apps.get_model('security', 'UserBan')
    for ban in UserBan.objects.filter(phone_hash='').select_related('user').iterator():
        phone_hash = banned_phone_hash(ban.user.phone_key)
        if phone_hash:
            UserBan.objects.filter(pk=ban.pk).update(phone_hash=phone_hash)


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0020_face_check_challenge'),
    ]

    operations = [
        migrations.AddField(
            model_name='userban',
            name='phone_hash',
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
