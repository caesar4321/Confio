from django.contrib import admin
from .models import UserProfile, ZkLoginProof

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'sui_address', 'created_at')
    search_fields = ('user__username', 'user__email', 'sui_address')
    readonly_fields = ('created_at',)

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('proof_id', 'profile', 'max_epoch', 'created_at')
    search_fields = ('proof_id', 'profile__user__username')
    readonly_fields = ('created_at',)
