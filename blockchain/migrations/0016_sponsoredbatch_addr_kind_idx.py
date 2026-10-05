import django.db.models.functions.text
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class AddIndexConcurrentlyOnPostgres(AddIndexConcurrently):
    """CONCURRENTLY where it exists (PostgreSQL); a plain index elsewhere
    (config/settings_local_sqlite.py rebuilds), which has no such option."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        return migrations.AddIndex.database_forwards(self, app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            return super().database_backwards(app_label, schema_editor, from_state, to_state)
        return migrations.AddIndex.database_backwards(self, app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    """Per-wallet stock history lookups (Tu mes "Tus acciones"): an index on
    the expression __iexact compiles to, so they stop reading every stock
    batch of every user on each open and settling poll.

    Built CONCURRENTLY: a plain CREATE INDEX holds a write lock on
    sponsored_batches for the whole build, stalling every sponsored send,
    payment and receipt confirmation during the deploy."""

    atomic = False

    dependencies = [
        ('blockchain', '0015_include_cusd_in_payment_uniqueness'),
    ]

    operations = [
        AddIndexConcurrentlyOnPostgres(
            model_name='sponsoredbatch',
            index=models.Index(
                django.db.models.functions.text.Upper('user_bsc_address'),
                models.F('kind'),
                name='cpsb_addr_kind_idx',
            ),
        ),
    ]
