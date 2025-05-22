from django.contrib import admin
from .models import UserProfile, ZkLoginProof

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'sui_address', 'created_at')
    search_fields = ('user__username', 'user__email', 'sui_address')
    readonly_fields = ('created_at',)

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('id',)  # Minimal display for debugging
    # search_fields and readonly_fields can be added back after debugging
