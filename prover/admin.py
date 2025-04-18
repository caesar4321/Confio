from django.contrib import admin
from .models import ZkLoginProof, UserProfile

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('proof_id', 'user', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('proof_id', 'user__username', 'user__email')
    readonly_fields = ('proof_id', 'created_at')
    fieldsets = (
        ('Proof Information', {
            'fields': ('proof_id', 'user', 'jwt', 'max_epoch', 'proof')
        }),
        ('Binary Data', {
            'fields': ('randomness', 'salt', 'user_salt', 'extended_ephemeral_public_key', 'user_signature')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'sui_address', 'created_at')
    search_fields = ('user__username', 'user__email', 'sui_address')
    readonly_fields = ('created_at',)
