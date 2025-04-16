from django.contrib import admin
from .models import ZkLoginProof

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'is_verified', 'verified_at')
    list_filter = ('is_verified', 'created_at')
    search_fields = ('user__email', 'jwt')
    readonly_fields = ('created_at', 'verified_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Proof Details', {
            'fields': ('jwt', 'max_epoch', 'randomness', 'salt', 'proof_data')
        }),
        ('Verification Status', {
            'fields': ('is_verified', 'verified_at')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
