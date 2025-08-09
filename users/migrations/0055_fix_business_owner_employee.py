# Generated manually to fix business owner employee constraint

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0054_rename_firebase_uid_to_account_key'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Drop the incorrect trigger that prevents owners from being employees
            DROP TRIGGER IF EXISTS prevent_self_employment ON users_businessemployee;
            DROP FUNCTION IF EXISTS check_no_self_employment();
            
            -- Create a corrected trigger that:
            -- 1. Allows owners to have a BusinessEmployee record with role='owner'
            -- 2. Prevents business owners from being non-owner employees
            -- 3. Ensures only one owner per business
            CREATE OR REPLACE FUNCTION check_business_employee_constraints()
            RETURNS TRIGGER AS $$
            BEGIN
                -- Check 1: If user owns the business (has an Account record),
                -- they can only be an employee with role='owner'
                IF NEW.role != 'owner' AND EXISTS (
                    SELECT 1 FROM users_account 
                    WHERE business_id = NEW.business_id 
                    AND user_id = NEW.user_id 
                    AND account_type = 'business'
                    AND deleted_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'Business owner can only have owner role in their own business';
                END IF;
                
                -- Check 2: If role is 'owner', user must have an Account record for this business
                IF NEW.role = 'owner' AND NOT EXISTS (
                    SELECT 1 FROM users_account 
                    WHERE business_id = NEW.business_id 
                    AND user_id = NEW.user_id 
                    AND account_type = 'business'
                    AND deleted_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'Only business account holders can have owner role';
                END IF;
                
                -- Check 3: Ensure only one owner per business
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
            
            CREATE TRIGGER check_business_employee_constraints
            BEFORE INSERT OR UPDATE ON users_businessemployee
            FOR EACH ROW
            EXECUTE FUNCTION check_business_employee_constraints();
            """,
            reverse_sql="""
            -- Revert to the original trigger
            DROP TRIGGER IF EXISTS check_business_employee_constraints ON users_businessemployee;
            DROP FUNCTION IF EXISTS check_business_employee_constraints();
            
            CREATE OR REPLACE FUNCTION check_no_self_employment()
            RETURNS TRIGGER AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM users_account 
                    WHERE business_id = NEW.business_id 
                    AND user_id = NEW.user_id 
                    AND account_type = 'business'
                    AND deleted_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'Business owner cannot be an employee of their own business';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            
            CREATE TRIGGER prevent_self_employment
            BEFORE INSERT OR UPDATE ON users_businessemployee
            FOR EACH ROW
            EXECUTE FUNCTION check_no_self_employment();
            """
        ),
    ]