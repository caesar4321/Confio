from django.contrib import admin
from .models import (
    P2PPaymentMethod, 
    P2POffer, 
    P2PTrade, 
    P2PMessage, 
    P2PUserStats, 
    P2PEscrow
)

@admin.register(P2PPaymentMethod)
class P2PPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'display_name']
    ordering = ['display_name']

@admin.register(P2POffer)
class P2POfferAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'exchange_type', 'token_type', 'rate', 
        'available_amount', 'status', 'created_at'
    ]
    list_filter = [
        'exchange_type', 'token_type', 'status', 'created_at'
    ]
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['payment_methods']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'exchange_type', 'token_type', 'status')
        }),
        ('Pricing', {
            'fields': ('rate', 'min_amount', 'max_amount', 'available_amount')
        }),
        ('Payment & Terms', {
            'fields': ('payment_methods', 'terms', 'response_time_minutes')
        }),
        ('Auto-complete', {
            'fields': ('auto_complete_enabled', 'auto_complete_time_minutes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(P2PTrade)
class P2PTradeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'buyer', 'seller', 'crypto_amount', 'fiat_amount', 
        'status', 'created_at', 'expires_at'
    ]
    list_filter = [
        'status', 'offer__token_type', 'created_at', 'expires_at'
    ]
    search_fields = [
        'buyer__username', 'seller__username', 'offer__user__username'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'completed_at', 
        'disputed_at', 'resolved_at'
    ]
    
    fieldsets = (
        ('Trade Participants', {
            'fields': ('offer', 'buyer', 'seller')
        }),
        ('Trade Details', {
            'fields': (
                'crypto_amount', 'fiat_amount', 'rate_used', 
                'payment_method', 'status', 'expires_at'
            )
        }),
        ('Payment Info', {
            'fields': ('payment_reference', 'payment_notes')
        }),
        ('Completion', {
            'fields': ('crypto_transaction_hash', 'completed_at')
        }),
        ('Dispute Handling', {
            'fields': ('dispute_reason', 'disputed_at', 'resolved_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(P2PMessage)
class P2PMessageAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade', 'sender', 'message_type', 'is_read', 'created_at'
    ]
    list_filter = ['message_type', 'is_read', 'created_at']
    search_fields = [
        'trade__id', 'sender__username', 'content'
    ]
    readonly_fields = ['created_at', 'updated_at', 'read_at']

@admin.register(P2PUserStats)
class P2PUserStatsAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'total_trades', 'completed_trades', 'success_rate', 
        'avg_response_time', 'is_verified'
    ]
    list_filter = [
        'is_verified', 'verification_level', 'last_seen_online'
    ]
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'last_seen_online']

@admin.register(P2PEscrow)
class P2PEscrowAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade', 'escrow_amount', 'token_type', 
        'is_escrowed', 'is_released', 'created_at'
    ]
    list_filter = [
        'token_type', 'is_escrowed', 'is_released', 'created_at'
    ]
    search_fields = [
        'trade__id', 'escrow_transaction_hash', 'release_transaction_hash'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'escrowed_at', 'released_at'
    ]