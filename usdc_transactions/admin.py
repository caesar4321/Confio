from django.contrib import admin
from .models import USDCDeposit, USDCWithdrawal


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
