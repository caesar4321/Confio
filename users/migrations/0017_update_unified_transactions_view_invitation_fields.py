# Generated manually for adding invitation fields to unified transactions view

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_create_unified_transactions_view'),
        ('send', '0012_add_invitation_tracking_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE VIEW unified_transactions_view AS
            SELECT 
                -- Common fields
                'send' as transaction_type,
                st.id,
                st.created_at,
                st.updated_at,
                st.deleted_at,
                st.amount,
                st.token_type,
                st.status,
                st.transaction_hash,
                st.error_message,
                
                -- Sender info
                st.sender_user_id,
                st.sender_business_id,
                st.sender_type,
                st.sender_display_name,
                st.sender_phone,
                st.sender_address,
                
                -- Recipient info (map to counterparty fields)
                st.recipient_user_id as counterparty_user_id,
                st.recipient_business_id as counterparty_business_id,
                st.recipient_type as counterparty_type,
                st.recipient_display_name as counterparty_display_name,
                st.recipient_phone as counterparty_phone,
                st.recipient_address as counterparty_address,
                
                -- Additional send-specific fields
                st.memo as description,
                NULL as invoice_id,
                NULL as payment_transaction_id,
                
                -- Computed direction field based on current user context (will be filtered in Django)
                st.sender_address as from_address,
                st.recipient_address as to_address,
                
                -- Invitation fields
                st.is_invitation,
                st.invitation_claimed,
                st.invitation_reverted,
                st.invitation_expires_at
                
            FROM send_sendtransaction st
            WHERE st.deleted_at IS NULL
            
            UNION ALL
            
            SELECT 
                -- Common fields
                'payment' as transaction_type,
                pt.id,
                pt.created_at,
                pt.updated_at,
                pt.deleted_at,
                pt.amount,
                pt.token_type,
                pt.status,
                pt.transaction_hash,
                pt.error_message,
                
                -- Payer info (sender)
                pt.payer_user_id as sender_user_id,
                pt.payer_business_id as sender_business_id,
                pt.payer_type as sender_type,
                pt.payer_display_name as sender_display_name,
                pt.payer_phone as sender_phone,
                pt.payer_address as sender_address,
                
                -- Merchant info (recipient/counterparty)
                pt.merchant_account_user_id as counterparty_user_id,
                pt.merchant_business_id as counterparty_business_id,
                pt.merchant_type as counterparty_type,
                pt.merchant_display_name as counterparty_display_name,
                NULL as counterparty_phone,  -- Merchants don't have phone in payment context
                pt.merchant_address as counterparty_address,
                
                -- Payment-specific fields
                pt.description,
                pt.invoice_id,
                pt.payment_transaction_id,
                
                -- Computed direction fields
                pt.payer_address as from_address,
                pt.merchant_address as to_address,
                
                -- Invitation fields (payments are never invitations)
                FALSE as is_invitation,
                FALSE as invitation_claimed,
                FALSE as invitation_reverted,
                NULL as invitation_expires_at
                
            FROM payments_paymenttransaction pt
            WHERE pt.deleted_at IS NULL;
            """,
            reverse_sql="""
            CREATE OR REPLACE VIEW unified_transactions_view AS
            SELECT 
                -- Common fields
                'send' as transaction_type,
                st.id,
                st.created_at,
                st.updated_at,
                st.deleted_at,
                st.amount,
                st.token_type,
                st.status,
                st.transaction_hash,
                st.error_message,
                
                -- Sender info
                st.sender_user_id,
                st.sender_business_id,
                st.sender_type,
                st.sender_display_name,
                st.sender_phone,
                st.sender_address,
                
                -- Recipient info (map to counterparty fields)
                st.recipient_user_id as counterparty_user_id,
                st.recipient_business_id as counterparty_business_id,
                st.recipient_type as counterparty_type,
                st.recipient_display_name as counterparty_display_name,
                st.recipient_phone as counterparty_phone,
                st.recipient_address as counterparty_address,
                
                -- Additional send-specific fields
                st.memo as description,
                NULL as invoice_id,
                NULL as payment_transaction_id,
                
                -- Computed direction field based on current user context (will be filtered in Django)
                st.sender_address as from_address,
                st.recipient_address as to_address
                
            FROM send_sendtransaction st
            WHERE st.deleted_at IS NULL
            
            UNION ALL
            
            SELECT 
                -- Common fields
                'payment' as transaction_type,
                pt.id,
                pt.created_at,
                pt.updated_at,
                pt.deleted_at,
                pt.amount,
                pt.token_type,
                pt.status,
                pt.transaction_hash,
                pt.error_message,
                
                -- Payer info (sender)
                pt.payer_user_id as sender_user_id,
                pt.payer_business_id as sender_business_id,
                pt.payer_type as sender_type,
                pt.payer_display_name as sender_display_name,
                pt.payer_phone as sender_phone,
                pt.payer_address as sender_address,
                
                -- Merchant info (recipient/counterparty)
                pt.merchant_account_user_id as counterparty_user_id,
                pt.merchant_business_id as counterparty_business_id,
                pt.merchant_type as counterparty_type,
                pt.merchant_display_name as counterparty_display_name,
                NULL as counterparty_phone,  -- Merchants don't have phone in payment context
                pt.merchant_address as counterparty_address,
                
                -- Payment-specific fields
                pt.description,
                pt.invoice_id,
                pt.payment_transaction_id,
                
                -- Computed direction fields
                pt.payer_address as from_address,
                pt.merchant_address as to_address
                
            FROM payments_paymenttransaction pt
            WHERE pt.deleted_at IS NULL;
            """
        ),
    ]