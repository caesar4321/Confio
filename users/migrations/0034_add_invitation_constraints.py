from django.db import migrations, models
from django.db.models import UniqueConstraint, Q


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0033_add_employee_unique_constraint'),
    ]

    operations = [
        # Add a unique constraint for pending invitations per phone/business
        migrations.AddConstraint(
            model_name='employeeinvitation',
            constraint=UniqueConstraint(
                fields=['business', 'employee_phone', 'employee_phone_country'],
                condition=Q(status='pending') & Q(deleted_at__isnull=True),
                name='unique_pending_invitation_per_phone'
            ),
        ),
        
        # Add index for phone lookups
        migrations.AddIndex(
            model_name='employeeinvitation',
            index=models.Index(
                fields=['employee_phone', 'employee_phone_country', 'status'],
                name='idx_invitation_phone_status'
            ),
        ),
        
        # Add a function to check that invited phone doesn't belong to business owner
        migrations.RunSQL(
            sql="""
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
                
                -- Also check if user is already an employee
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
            
            DROP TRIGGER IF EXISTS prevent_invalid_invitation ON users_employeeinvitation;
            
            CREATE TRIGGER prevent_invalid_invitation
            BEFORE INSERT OR UPDATE ON users_employeeinvitation
            FOR EACH ROW
            EXECUTE FUNCTION check_no_self_invitation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS prevent_invalid_invitation ON users_employeeinvitation;
            DROP FUNCTION IF EXISTS check_no_self_invitation();
            """
        ),
    ]