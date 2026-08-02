"""Enforce the owner-role invariants in the database, on every environment.

This trigger already existed on a developer database, in no migration and no
file in this repo, so it silently protected local testing while PRODUCTION HAD
NO SUCH PROTECTION. The eleventh Codex audit reported two P1s that the trigger
would have made impossible; checking the developer database made them look
like false positives, and checking production showed they were real.

The invariants:
  1. an Account holder's employee row must be role='owner' — so an owner
     cannot be demoted into a role that the permission gate then evaluates,
     locking them out of their own business;
  2. role='owner' requires an Account for that business — so ownership cannot
     be delegated to someone who owns nothing and thereby made irrevocable;
  3. at most one owner row per business.

Production data was verified clean against all three before this was written
(0 violations of each).
"""
from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION check_business_employee_constraints()
RETURNS TRIGGER AS $$
BEGIN
    -- 1. An Account holder can only hold the owner role in their own business.
    IF NEW.role != 'owner' AND EXISTS (
        SELECT 1 FROM users_account
        WHERE business_id = NEW.business_id
        AND user_id = NEW.user_id
        AND account_type = 'business'
        AND deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Business owner can only have owner role in their own business';
    END IF;

    -- 2. The owner role requires the Account that proves ownership.
    IF NEW.role = 'owner' AND NOT EXISTS (
        SELECT 1 FROM users_account
        WHERE business_id = NEW.business_id
        AND user_id = NEW.user_id
        AND account_type = 'business'
        AND deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Only business account holders can have owner role';
    END IF;

    -- 3. One owner per business.
    IF NEW.role = 'owner' AND EXISTS (
        SELECT 1 FROM users_businessemployee
        WHERE business_id = NEW.business_id
        AND role = 'owner'
        AND id != COALESCE(NEW.id, -1)
        AND deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Business can only have one owner';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """
DROP TRIGGER IF EXISTS business_employee_constraints ON users_businessemployee;
CREATE TRIGGER business_employee_constraints
    BEFORE INSERT OR UPDATE ON users_businessemployee
    FOR EACH ROW EXECUTE FUNCTION check_business_employee_constraints();
"""

DROP = """
DROP TRIGGER IF EXISTS business_employee_constraints ON users_businessemployee;
DROP FUNCTION IF EXISTS check_business_employee_constraints();
"""


def verify_clean(apps, schema_editor):
    """Refuse to install an invariant the data already violates."""
    with schema_editor.connection.cursor() as c:
        c.execute("""
            SELECT count(*) FROM users_businessemployee e
            WHERE e.deleted_at IS NULL AND e.role = 'owner'
              AND NOT EXISTS (SELECT 1 FROM users_account a
                              WHERE a.business_id = e.business_id AND a.user_id = e.user_id
                              AND a.account_type = 'business' AND a.deleted_at IS NULL)
        """)
        orphan_owners = c.fetchone()[0]
        c.execute("""
            SELECT count(*) FROM users_businessemployee e
            WHERE e.deleted_at IS NULL AND e.role != 'owner'
              AND EXISTS (SELECT 1 FROM users_account a
                          WHERE a.business_id = e.business_id AND a.user_id = e.user_id
                          AND a.account_type = 'business' AND a.deleted_at IS NULL)
        """)
        demoted_owners = c.fetchone()[0]
        c.execute("""
            SELECT count(*) FROM (
                SELECT business_id FROM users_businessemployee
                WHERE deleted_at IS NULL AND role = 'owner'
                GROUP BY business_id HAVING count(*) > 1) x
        """)
        multi_owner = c.fetchone()[0]
    if orphan_owners or demoted_owners or multi_owner:
        raise RuntimeError(
            f"ownership invariants already violated: {orphan_owners} owner rows "
            f"without an Account, {demoted_owners} Account owners not role=owner, "
            f"{multi_owner} businesses with several owners. Resolve before enforcing."
        )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_unified_amount_denomination'),
    ]

    operations = [
        migrations.RunPython(verify_clean, migrations.RunPython.noop),
        migrations.RunSQL(FUNCTION + CREATE_TRIGGER, reverse_sql=DROP),
    ]
