from django.contrib import admin
from .models import UserProfile, ZkLoginProof

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'google_sub', 'apple_sub', 'sui_address', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'google_sub', 'apple_sub', 'sui_address')

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('profile', 'proof_id', 'max_epoch', 'created_at')
    list_filter = ('max_epoch', 'created_at')
    search_fields = ('profile__user__username', 'proof_id')
