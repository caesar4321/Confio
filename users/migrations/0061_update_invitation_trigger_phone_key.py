from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0060_add_phone_key_and_employee_phone_key'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Replace owner self-invitation trigger to use employee_phone_key when available
            DROP TRIGGER IF EXISTS prevent_owner_self_invitation ON users_employeeinvitation;
            DROP FUNCTION IF EXISTS check_no_owner_self_invitation();

            CREATE OR REPLACE FUNCTION check_no_owner_self_invitation()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.employee_phone_key IS NOT NULL THEN
                    -- Compare using canonical phone_key
                    IF EXISTS (
                        SELECT 1 FROM users_user u
                        JOIN users_account a ON a.user_id = u.id
                        WHERE a.business_id = NEW.business_id 
                          AND a.account_type = 'business'
                          AND u.phone_key = NEW.employee_phone_key
                          AND a.deleted_at IS NULL
                    ) THEN
                        RAISE EXCEPTION 'Cannot invite business owner as an employee';
                    END IF;
                ELSE
                    -- Fallback to ISO + raw phone comparison for older records
                    IF EXISTS (
                        SELECT 1 FROM users_user u
                        JOIN users_account a ON a.user_id = u.id
                        WHERE a.business_id = NEW.business_id 
                          AND a.account_type = 'business'
                          AND u.phone_number = NEW.employee_phone
                          AND u.phone_country = NEW.employee_phone_country
                          AND a.deleted_at IS NULL
                    ) THEN
                        RAISE EXCEPTION 'Cannot invite business owner as an employee';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER prevent_owner_self_invitation
            BEFORE INSERT OR UPDATE ON users_employeeinvitation
            FOR EACH ROW
            EXECUTE FUNCTION check_no_owner_self_invitation();
            """,
            reverse_sql="""
            -- Revert to previous trigger/function definition that used ISO+number
            DROP TRIGGER IF EXISTS prevent_owner_self_invitation ON users_employeeinvitation;
            DROP FUNCTION IF EXISTS check_no_owner_self_invitation();

            CREATE OR REPLACE FUNCTION check_no_owner_self_invitation()
            RETURNS TRIGGER AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM users_user u
                    JOIN users_account a ON a.user_id = u.id
                    WHERE a.business_id = NEW.business_id 
                      AND a.account_type = 'business'
                      AND u.phone_number = NEW.employee_phone
                      AND u.phone_country = NEW.employee_phone_country
                      AND a.deleted_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'Cannot invite business owner as an employee';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER prevent_owner_self_invitation
            BEFORE INSERT OR UPDATE ON users_employeeinvitation
            FOR EACH ROW
            EXECUTE FUNCTION check_no_owner_self_invitation();
            """
        ),
    ]

