from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import USDCDeposit, USDCWithdrawal
from .models_unified import UnifiedUSDCTransactionTable


@admin.register(USDCDeposit)
class USDCDepositAdmin(admin.ModelAdmin):
    list_display = ['deposit_id', 'actor_display_name', 'actor_type', 'amount', 'status', 'created_at']
    list_filter = ['status', 'actor_type', 'network', 'created_at']
    search_fields = ['deposit_id', 'actor_display_name', 'source_address']
    readonly_fields = ['deposit_id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('deposit_id', 'status', 'error_message')
        }),
        ('Actor Info', {
            'fields': ('actor_user', 'actor_business', 'actor_type', 'actor_display_name', 'actor_address')
        }),
        ('Deposit Details', {
            'fields': ('amount', 'source_address', 'network')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at')
        }),
        ('Soft Delete', {
            'fields': ('is_deleted', 'deleted_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(USDCWithdrawal)
class USDCWithdrawalAdmin(admin.ModelAdmin):
    list_display = ['withdrawal_id', 'actor_display_name', 'actor_type', 'amount', 'status', 'created_at']
    list_filter = ['status', 'actor_type', 'network', 'created_at']
    search_fields = ['withdrawal_id', 'actor_display_name', 'destination_address']
    readonly_fields = ['withdrawal_id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('withdrawal_id', 'status', 'error_message')
        }),
        ('Actor Info', {
            'fields': ('actor_user', 'actor_business', 'actor_type', 'actor_display_name', 'actor_address')
        }),
        ('Withdrawal Details', {
            'fields': ('amount', 'destination_address', 'network', 'service_fee')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at')
        }),
        ('Soft Delete', {
            'fields': ('is_deleted', 'deleted_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(UnifiedUSDCTransactionTable)
class UnifiedUSDCTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'transaction_id_short', 'type_display', 'amount_display', 'status_display', 'actor_info', 'created_at', 'transaction_date']
    list_filter = ['transaction_type', 'status', 'actor_type', 'created_at']
    search_fields = ['transaction_id', 'actor_display_name', 'source_address', 'destination_address', 'transaction_hash']
    readonly_fields = [
        'id', 'usdc_deposit', 'usdc_withdrawal', 'conversion',
        'created_at', 'updated_at', 'transaction_date', 'completed_at',
        'source_transaction_link'
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('id', 'transaction_id', 'transaction_type', 'status', 'source_transaction_link')
        }),
        ('Actor Info', {
            'fields': ('actor_user', 'actor_business', 'actor_type', 'actor_display_name', 'actor_address')
        }),
        ('Transaction Details', {
            'fields': ('amount', 'currency', 'secondary_amount', 'secondary_currency', 'exchange_rate')
        }),
        ('Fees', {
            'fields': ('network_fee', 'service_fee')
        }),
        ('Addresses', {
            'fields': ('source_address', 'destination_address', 'transaction_hash', 'block_number', 'network')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'transaction_date', 'updated_at', 'completed_at')
        }),
        ('Error Info', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Source Transaction Links', {
            'fields': ('usdc_deposit', 'usdc_withdrawal', 'conversion'),
            'classes': ('collapse',)
        })
    )
    
    def has_add_permission(self, request):
        return False  # Created automatically via signals
    
    def has_delete_permission(self, request, obj=None):
        return False  # Don't allow manual deletion
    
    def transaction_id_short(self, obj):
        """Display shortened transaction ID"""
        if obj.transaction_id:
            return format_html(
                '<span title="{}" style="font-family: monospace;">{}</span>',
                obj.transaction_id,
                str(obj.transaction_id)[:8] + '...'
            )
        return "-"
    transaction_id_short.short_description = "Transaction ID"
    
    def type_display(self, obj):
        """Display transaction type with icon"""
        icons = {
            'deposit': '⬇️',
            'withdrawal': '⬆️',
            'conversion': '🔄'
        }
        colors = {
            'deposit': '#10B981',
            'withdrawal': '#EF4444',
            'conversion': '#3B82F6'
        }
        icon = icons.get(obj.transaction_type, '📄')
        color = colors.get(obj.transaction_type, '#6B7280')
        return format_html(
            '<span style="color: {};">{} {}</span>',
            color,
            icon,
            obj.transaction_type.title()
        )
    type_display.short_description = "Type"
    
    def amount_display(self, obj):
        """Display amount with currency"""
        try:
            amount_value = float(obj.amount)
            formatted_amount = f"{amount_value:,.2f}"
            return format_html(
                '<span style="font-weight: bold;">{}</span> {}',
                formatted_amount,
                obj.currency
            )
        except (ValueError, TypeError):
            return f"{obj.amount} {obj.currency}"
    amount_display.short_description = "Amount"
    
    def status_display(self, obj):
        """Display status with color"""
        colors = {
            'PENDING': 'orange',
            'PROCESSING': 'blue',
            'COMPLETED': 'green',
            'FAILED': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.status
        )
    status_display.short_description = "Status"
    
    def actor_info(self, obj):
        """Display actor with type badge"""
        if obj.actor_type == 'business':
            type_badge = format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">BUSINESS</span> '
            )
        else:
            type_badge = format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">PERSONAL</span> '
            )
        return format_html('{}{}', type_badge, obj.actor_display_name or 'Unknown')
    actor_info.short_description = "Actor"
    
    def source_transaction_link(self, obj):
        """Display link to source transaction"""
        if obj.usdc_deposit:
            url = reverse('admin:usdc_transactions_usdcdeposit_change', args=[obj.usdc_deposit.id])
            return format_html('<a href="{}">USDC Deposit #{}</a>', url, obj.usdc_deposit.id)
        elif obj.usdc_withdrawal:
            url = reverse('admin:usdc_transactions_usdcwithdrawal_change', args=[obj.usdc_withdrawal.id])
            return format_html('<a href="{}">USDC Withdrawal #{}</a>', url, obj.usdc_withdrawal.id)
        elif obj.conversion:
            url = reverse('admin:conversion_conversion_change', args=[obj.conversion.id])
            return format_html('<a href="{}">Conversion #{}</a>', url, obj.conversion.id)
        return "No source"
    source_transaction_link.short_description = "Source"
    
    def transaction_date(self, obj):
        """Display the original transaction date"""
        if obj.transaction_date:
            return obj.transaction_date.strftime('%Y-%m-%d %H:%M:%S')
        return "-"
    transaction_date.short_description = "Original Date"
    transaction_date.admin_order_field = 'transaction_date'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related(
            'actor_user', 'actor_business',
            'usdc_deposit', 'usdc_withdrawal', 'conversion'
        )