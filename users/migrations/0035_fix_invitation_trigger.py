from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0034_add_invitation_constraints'),
    ]

    operations = [
        # Update the trigger to be less restrictive
        migrations.RunSQL(
            sql="""
            -- Drop the old trigger and function
            DROP TRIGGER IF EXISTS prevent_invalid_invitation ON users_employeeinvitation;
            DROP FUNCTION IF EXISTS check_no_self_invitation();
            
            -- Create updated function that only checks for owner self-invitation
            CREATE OR REPLACE FUNCTION check_no_owner_self_invitation()
            RETURNS TRIGGER AS $$
            BEGIN
                -- Only check if the phone number belongs to a business owner
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
            
            -- Create new trigger with updated function
            CREATE TRIGGER prevent_owner_self_invitation
            BEFORE INSERT OR UPDATE ON users_employeeinvitation
            FOR EACH ROW
            EXECUTE FUNCTION check_no_owner_self_invitation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS prevent_owner_self_invitation ON users_employeeinvitation;
            DROP FUNCTION IF EXISTS check_no_owner_self_invitation();
            
            -- Restore the original function and trigger
            CREATE OR REPLACE FUNCTION check_no_self_invitation()
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
                
                IF EXISTS (
                    SELECT 1 FROM users_user u
                    JOIN users_businessemployee be ON be.user_id = u.id
                    WHERE be.business_id = NEW.business_id
                    AND u.phone_number = NEW.employee_phone
                    AND u.phone_country = NEW.employee_phone_country
                    AND be.deleted_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'User is already an employee of this business';
                END IF;
                
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            
            CREATE TRIGGER prevent_invalid_invitation
            BEFORE INSERT OR UPDATE ON users_employeeinvitation
            FOR EACH ROW
            EXECUTE FUNCTION check_no_self_invitation();
            """
        ),
    ]