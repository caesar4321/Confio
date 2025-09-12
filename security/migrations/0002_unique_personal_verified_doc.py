from django.db import migrations


def create_partial_unique_index(apps, schema_editor):
    # Only for PostgreSQL: create a partial unique index that prevents
    # duplicate personal-context verified records for the same user+document.
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            DO $$
            DECLARE tbl_owner TEXT;
            BEGIN
                SELECT tableowner INTO tbl_owner
                FROM pg_tables
                WHERE schemaname = 'public' AND tablename = 'security_identityverification';

                IF tbl_owner IS NULL THEN
                    RAISE NOTICE 'security_identityverification not found; skipping index creation';
                    RETURN;
                END IF;

                IF tbl_owner = current_user THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'i'
                          AND c.relname = 'uniq_iv_personal_verified_doc_per_user'
                    ) THEN
                        CREATE UNIQUE INDEX uniq_iv_personal_verified_doc_per_user
                        ON security_identityverification (user_id, document_number)
                        WHERE status = 'verified'
                          AND ((risk_factors ->> 'account_type') IS NULL OR (risk_factors ->> 'account_type') <> 'business');
                    END IF;
                ELSE
                    RAISE NOTICE 'Current user % is not owner of security_identityverification (owner: %); skipping index', current_user, tbl_owner;
                END IF;
            END
            $$;
            """
        )


def drop_partial_unique_index(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            DO $$
            DECLARE tbl_owner TEXT;
            BEGIN
                SELECT tableowner INTO tbl_owner
                FROM pg_tables
                WHERE schemaname = 'public' AND tablename = 'security_identityverification';

                IF tbl_owner IS NULL THEN
                    RETURN;
                END IF;

                IF tbl_owner = current_user THEN
                    IF EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'i'
                          AND c.relname = 'uniq_iv_personal_verified_doc_per_user'
                    ) THEN
                        DROP INDEX uniq_iv_personal_verified_doc_per_user;
                    END IF;
                END IF;
            END
            $$;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ('security', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(create_partial_unique_index, drop_partial_unique_index),
    ]
