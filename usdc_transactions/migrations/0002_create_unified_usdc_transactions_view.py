# Generated migration for unified USDC transactions view

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usdc_transactions', '0001_initial'),
        ('conversion', '0004_remove_legacy_fields'),  # Ensure conversion tables exist
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE VIEW unified_usdc_transactions AS
            -- USDC Deposits
            SELECT 
                CAST(d.deposit_id AS TEXT) as transaction_id,
                'deposit' as transaction_type,
                d.actor_user_id,
                d.actor_business_id,
                d.actor_type,
                d.actor_display_name,
                d.actor_address,
                d.amount,
                'USDC' as currency,
                CAST(NULL AS DECIMAL(19,6)) as secondary_amount,
                '' as secondary_currency,
                CAST(NULL AS DECIMAL(10,6)) as exchange_rate,
                d.network_fee,
                CAST(0 AS DECIMAL(19,6)) as service_fee,
                d.source_address,
                '' as destination_address,
                d.transaction_hash,
                d.block_number,
                d.network,
                d.status,
                d.error_message,
                d.created_at,
                d.updated_at,
                d.completed_at
            FROM usdc_deposits d
            WHERE d.is_deleted = false

            UNION ALL

            -- USDC Withdrawals
            SELECT 
                CAST(w.withdrawal_id AS TEXT) as transaction_id,
                'withdrawal' as transaction_type,
                w.actor_user_id,
                w.actor_business_id,
                w.actor_type,
                w.actor_display_name,
                w.actor_address,
                w.amount,
                'USDC' as currency,
                CAST(NULL AS DECIMAL(19,6)) as secondary_amount,
                '' as secondary_currency,
                CAST(NULL AS DECIMAL(10,6)) as exchange_rate,
                w.network_fee,
                w.service_fee,
                '' as source_address,
                w.destination_address,
                w.transaction_hash,
                w.block_number,
                w.network,
                w.status,
                w.error_message,
                w.created_at,
                w.updated_at,
                w.completed_at
            FROM usdc_withdrawals w
            WHERE w.is_deleted = false

            UNION ALL

            -- USDC Conversions (from conversion table)
            SELECT 
                CAST(c.conversion_id AS TEXT) as transaction_id,
                'conversion' as transaction_type,
                c.actor_user_id,
                c.actor_business_id,
                c.actor_type,
                c.actor_display_name,
                c.actor_address,
                c.from_amount as amount,
                CASE 
                    WHEN c.conversion_type = 'usdc_to_cusd' THEN 'USDC'
                    WHEN c.conversion_type = 'cusd_to_usdc' THEN 'cUSD'
                    ELSE 'USDC'
                END as currency,
                c.to_amount as secondary_amount,
                CASE 
                    WHEN c.conversion_type = 'usdc_to_cusd' THEN 'cUSD'
                    WHEN c.conversion_type = 'cusd_to_usdc' THEN 'USDC'
                    ELSE 'cUSD'
                END as secondary_currency,
                c.exchange_rate,
                CAST(0 AS DECIMAL(19,6)) as network_fee,
                c.fee_amount as service_fee,
                '' as source_address,
                '' as destination_address,
                c.to_transaction_hash as transaction_hash,
                CAST(NULL AS BIGINT) as block_number,
                'SUI' as network,
                c.status,
                c.error_message,
                c.created_at,
                c.updated_at,
                c.completed_at
            FROM conversions c
            WHERE c.is_deleted = false

            ORDER BY created_at DESC;
            """,
            reverse_sql="DROP VIEW IF EXISTS unified_usdc_transactions;"
        )
    ]