from django.db import migrations, models


def keep_newest_active_reference(apps, schema_editor):
    """Leave one active reference per user (the newest) before the constraint."""
    FaceReference = apps.get_model('security', 'FaceReference')
    seen = set()
    for ref in FaceReference.objects.filter(is_active=True).order_by('user_id', '-created_at', '-id'):
        if ref.user_id in seen:
            FaceReference.objects.filter(pk=ref.pk).update(is_active=False)
        else:
            seen.add(ref.user_id)


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0013_face_step_up'),
    ]

    operations = [
        migrations.RunPython(keep_newest_active_reference, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='facereference',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)), fields=('user',),
                name='face_reference_one_active_per_user'),
        ),
    ]
