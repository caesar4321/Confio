from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from django.db.models import Q
from django.utils import timezone
from config.admin_mixins import EnhancedAdminMixin
from .models import SendTransaction, PhoneInvite

class SendTypeFilter(admin.SimpleListFilter):
    title = 'Send Type'
    parameter_name = 'send_type'

    def lookups(self, request, model_admin):
        return (
            ('confio_friend', 'Confío Friend'),
            ('non_confio_friend', 'Non-Confío Friend'),
            ('external_wallet', 'External Wallet'),
            ('external_deposit', 'External Deposit'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'confio_friend':
            return queryset.filter(recipient_user__isnull=False).exclude(sender_type='external')
        elif self.value() == 'non_confio_friend':
            return queryset.filter(recipient_user__isnull=True, recipient_phone__isnull=False).exclude(recipient_phone='').exclude(sender_type='external')
        elif self.value() == 'external_wallet':
            return queryset.filter(recipient_user__isnull=True).filter(Q(recipient_phone__isnull=True) | Q(recipient_phone='')).exclude(sender_type='external')
        elif self.value() == 'external_deposit':
            return queryset.filter(sender_type='external')
        return queryset

@admin.register(SendTransaction)
class SendTransactionAdmin(EnhancedAdminMixin, admin.ModelAdmin):
    """Admin configuration for SendTransaction model"""
    list_display = [
        'id',
        'sender_display',
        'recipient_type_display',
        'recipient_display', 
        'amount_display', 
        'token_type', 
        'is_invitation',
        'invitation_expires_at',
        'status', 
        'created_at',
        'transaction_hash_display'
    ]
    list_filter = [
        SendTypeFilter,
        'status', 
        'token_type',
        'sender_type',
        'recipient_type', 
        'is_invitation',
        'created_at', 
        'updated_at',
        'sender_user__is_active',
        'recipient_user__is_active'
    ]
    search_fields = [
        'transaction_hash',
        'sender_user__username', 
        'sender_user__email',
        'sender_business__name',
        'recipient_user__username',
        'recipient_user__email',
        'recipient_business__name',
        'sender_address',
        'recipient_address',
        'memo',
        'sender_display_name',
        'recipient_display_name'
    ]
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'transaction_hash',
        'amount_display'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    actions = ['retry_failed_transactions', 'mark_as_confirmed', 'mark_as_failed', 'clear_selected_invitations']
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('amount_display', 'amount', 'token_type', 'memo')
        }),
        ('Sender Details', {
            'fields': ('sender_type', 'sender_user', 'sender_business', 'sender_display_name'),
            'description': 'Either sender_user (personal) OR sender_business (business) should be set'
        }),
        ('Recipient Details', {
            'fields': ('recipient_type', 'recipient_user', 'recipient_business', 'recipient_display_name'),
            'description': 'Either recipient_user (personal) OR recipient_business (business) should be set'
        }),
        ('Blockchain Details', {
            'fields': ('sender_address', 'recipient_address', 'transaction_hash'),
            'classes': ('collapse',)
        }),
        ('Status & Timing', {
            'fields': ('status', 'error_message', 'created_at', 'updated_at')
        }),
        ('System Fields', {
            'fields': ('deleted_at',),
            'classes': ('collapse',)
        }),
    )
    
    def sender_display(self, obj):
        """Display sender with type indicator and colored badge"""
        if obj.sender_type == 'external':
            # External wallet deposit
            return format_html(
                '<span style="background-color: #6B7280; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">EXTERNAL</span>'
                '<code style="font-size: 11px;">{}</code>',
                obj.sender_address[:10] + '...' + obj.sender_address[-6:] if len(obj.sender_address) > 20 else obj.sender_address
            )
        elif obj.sender_business:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">BUSINESS</span>'
                '<strong>{}</strong>',
                obj.sender_business.name
            )
        elif obj.sender_user:
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">PERSONAL</span>'
                '{} {}',
                obj.sender_user.first_name or obj.sender_user.username,
                obj.sender_user.last_name or ''
            )
        return "Unknown Sender"
    sender_display.short_description = "Sender"
    sender_display.admin_order_field = 'sender_user__username'
    
    def recipient_type_display(self, obj):
        """Display the type of send transaction with colored badge"""
        if obj.sender_type == 'external':
            # External deposit
            return format_html(
                '<span style="background-color: #8B5CF6; color: white; padding: 3px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: 600; '
                'text-transform: uppercase; letter-spacing: 0.5px;">💰 External Deposit</span>'
            )
        elif obj.recipient_user:
            # Send to Confío friend
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 3px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: 600; '
                'text-transform: uppercase; letter-spacing: 0.5px;">👥 Confío Friend</span>'
            )
        elif obj.recipient_user is None and obj.recipient_phone:
            # Send to non-Confío friend (invitation via phone)
            return format_html(
                '<span style="background-color: #F59E0B; color: white; padding: 3px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: 600; '
                'text-transform: uppercase; letter-spacing: 0.5px;">📧 Non-Confío Friend</span>'
            )
        else:
            # External wallet address (direct address, not invitation)
            return format_html(
                '<span style="background-color: #6B7280; color: white; padding: 3px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: 600; '
                'text-transform: uppercase; letter-spacing: 0.5px;">🔗 External Wallet</span>'
            )
    recipient_type_display.short_description = "Send Type"
    
    def recipient_display(self, obj):
        """Display recipient with type indicator and colored badge"""
        if obj.recipient_business:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">BUSINESS</span>'
                '<strong>{}</strong>',
                obj.recipient_business.name
            )
        elif obj.recipient_user:
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">PERSONAL</span>'
                '{} {}',
                obj.recipient_user.first_name or obj.recipient_user.username,
                obj.recipient_user.last_name or ''
            )
        else:
            # External wallet - show truncated address
            if obj.recipient_address:
                return format_html(
                    '<span style="background-color: #6B7280; color: white; padding: 2px 6px; '
                    'border-radius: 4px; font-size: 11px; margin-right: 4px;">EXTERNAL</span>'
                    '<code>{}</code>',
                    f"{obj.recipient_address[:8]}...{obj.recipient_address[-6:]}"
                )
        return "Unknown Recipient"
    recipient_display.short_description = "Recipient"
    recipient_display.admin_order_field = 'recipient_user__username'
    
    def amount_display(self, obj):
        """Display amount in decimal format"""
        try:
            # Convert string amount to decimal and format
            from decimal import Decimal
            amount = Decimal(obj.amount)
            return f"{amount:,.2f} {obj.token_type}"
        except (ValueError, TypeError):
            return f"{obj.amount} {obj.token_type}"
    amount_display.short_description = "Amount"
    
    def transaction_hash_display(self, obj):
        """Display transaction hash with truncation"""
        if obj.transaction_hash:
            return f"{obj.transaction_hash[:8]}...{obj.transaction_hash[-8:]}"
        return "Pending"
    transaction_hash_display.short_description = "Transaction Hash"
    
    def retry_failed_transactions(self, request, queryset):
        """Retry failed send transactions"""
        updated = queryset.filter(status='FAILED').update(status='PENDING')
        self.message_user(request, f"{updated} failed send transactions marked for retry.")
    retry_failed_transactions.short_description = "Retry failed send transactions"
    
    def mark_as_confirmed(self, request, queryset):
        """Mark send transactions as confirmed"""
        updated = queryset.filter(status='PENDING').update(status='CONFIRMED')
        self.message_user(request, f"{updated} send transactions marked as confirmed.")
    mark_as_confirmed.short_description = "Mark as confirmed"
    
    def mark_as_failed(self, request, queryset):
        """Mark send transactions as failed"""
        updated = queryset.filter(status='PENDING').update(status='FAILED')
        self.message_user(request, f"{updated} send transactions marked as failed.")
    mark_as_failed.short_description = "Mark as failed"

    def clear_selected_invitations(self, request, queryset):
        """Soft-delete selected invitation SendTransaction records to unblock resends"""
        now = timezone.now()
        qs_invites = queryset.filter(is_invitation=True, deleted_at__isnull=True)
        count = 0
        for tx in qs_invites:
            tx.deleted_at = now
            tx.save(update_fields=['deleted_at'])
            count += 1
        self.message_user(request, f"Cleared {count} invitation transaction(s) (soft-deleted)", level=messages.SUCCESS)
    clear_selected_invitations.short_description = "Clear selected invitation records (soft-delete)"
    mark_as_failed.short_description = "Mark as failed"


@admin.register(PhoneInvite)
class PhoneInviteAdmin(EnhancedAdminMixin, admin.ModelAdmin):
    list_display = (
        'invitation_id', 'phone_key', 'amount', 'token_type', 'status', 'inviter', 'claimed_by', 'claimed_txid_short', 'send_transaction', 'claimed_at', 'expires_at', 'created_at'
    )
    search_fields = ('invitation_id', 'phone_key', 'phone_number', 'inviter_user__username')
    list_filter = ('status', 'token_type', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['clear_db_invitation']

    def inviter(self, obj):
        return obj.inviter_user and (obj.inviter_user.get_full_name() or obj.inviter_user.username)

    def claimed_txid_short(self, obj):
        if obj.claimed_txid:
            return f"{obj.claimed_txid[:8]}...{obj.claimed_txid[-8:]}"
        return '-'
    claimed_txid_short.short_description = 'Claim TXID'

    def clear_db_invitation(self, request, queryset):
        """Soft-delete PhoneInvite and related SendTransaction invitation rows for the phone"""
        now = timezone.now()
        cleared_tx = 0
        cleared_inv = 0
        for inv in queryset:
            # Clear matching SendTransaction rows
            digits = ''.join(ch for ch in (inv.phone_number or '') if ch.isdigit())
            tx_qs = SendTransaction.objects.filter(
                is_invitation=True,
                deleted_at__isnull=True
            ).filter(Q(recipient_phone=digits) | Q(recipient_display_name=digits))
            for tx in tx_qs:
                tx.deleted_at = now
                tx.save(update_fields=['deleted_at'])
                cleared_tx += 1
            # Soft-delete the PhoneInvite row
            if inv.deleted_at is None:
                inv.deleted_at = now
                if getattr(inv, 'status', None) == 'pending':
                    inv.status = 'reclaimed'
                inv.save(update_fields=['deleted_at', 'status', 'updated_at'])
                cleared_inv += 1
        self.message_user(request, f"Cleared {cleared_tx} invitation transactions and {cleared_inv} phone invite(s)", level=messages.SUCCESS)
    clear_db_invitation.short_description = "Clear DB invite for selected phone(s)"

    # Make visible and viewable to any staff user (read-only)
    def has_module_permission(self, request):
        return bool(getattr(request.user, 'is_staff', False))

    def has_view_permission(self, request, obj=None):
        return bool(getattr(request.user, 'is_staff', False))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def get_queryset(self, request):
        """Show only non-deleted transactions by default"""
        return super().get_queryset(request).filter(deleted_at__isnull=True)
    
    def has_delete_permission(self, request, obj=None):
        """Use soft delete instead of hard delete"""
        return True
    
    def delete_model(self, request, obj):
        """Override delete to use soft delete"""
        obj.delete()  # This will use the soft delete from SoftDeleteModel
    
    def delete_queryset(self, request, queryset):
        """Override bulk delete to use soft delete"""
        for obj in queryset:
            obj.delete()  # This will use the soft delete from SoftDeleteModel
