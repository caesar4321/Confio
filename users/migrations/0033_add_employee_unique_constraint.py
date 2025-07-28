from django.db import migrations, models
from django.db.models import UniqueConstraint, Q


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_add_employee_db_constraints'),
    ]

    operations = [
        # Remove the old unique_together constraint
        migrations.AlterUniqueTogether(
            name='businessemployee',
            unique_together=set(),
        ),
        
        # Add a unique constraint that excludes soft-deleted records
        migrations.AddConstraint(
            model_name='businessemployee',
            constraint=UniqueConstraint(
                fields=['business', 'user'],
                condition=Q(deleted_at__isnull=True),
                name='unique_active_business_employee'
            ),
        ),
        
        # Add a check constraint to prevent business owner from being an employee
        # This requires a custom migration operation since we need to join with Account table
        migrations.RunSQL(
            sql="""
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
            
            DROP TRIGGER IF EXISTS prevent_self_employment ON users_businessemployee;
            
            CREATE TRIGGER prevent_self_employment
            BEFORE INSERT OR UPDATE ON users_businessemployee
            FOR EACH ROW
            EXECUTE FUNCTION check_no_self_employment();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS prevent_self_employment ON users_businessemployee;
            DROP FUNCTION IF EXISTS check_no_self_employment();
            """
        ),
        
        # Add index for soft delete queries
        migrations.AddIndex(
            model_name='businessemployee',
            index=models.Index(
                fields=['business', 'user', 'deleted_at'],
                name='idx_business_user_deleted'
            ),
        ),
    ]