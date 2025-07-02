from django.contrib import admin
from .models import User, Account, Business, IdentityVerification

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'firebase_uid', 'phone_country', 'phone_number', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'firebase_uid', 'phone_country', 'phone_number')

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'account_type', 'account_index', 'account_id', 'business', 'sui_address', 'created_at')
    list_filter = ('account_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'account_id', 'business__name')
    readonly_fields = ('account_id',)

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_display_name', 'business_registration_number', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('name', 'category', 'description', 'business_registration_number')

@admin.register(IdentityVerification)
class IdentityVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'document_type', 'document_number', 'status', 'created_at', 'verified_at')
    list_filter = ('status', 'document_type', 'verified_country', 'created_at', 'verified_at')
    search_fields = ('user__username', 'user__email', 'verified_first_name', 'verified_last_name', 'document_number')
    readonly_fields = ('full_name', 'full_address', 'created_at', 'updated_at')
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'status')
        }),
        ('Personal Information', {
            'fields': ('verified_first_name', 'verified_last_name', 'verified_date_of_birth', 'verified_nationality')
        }),
        ('Address Information', {
            'fields': ('verified_address', 'verified_city', 'verified_state', 'verified_country', 'verified_postal_code')
        }),
        ('Document Information', {
            'fields': ('document_type', 'document_number', 'document_issuing_country', 'document_expiry_date')
        }),
        ('Document Files', {
            'fields': ('document_front_image', 'document_back_image', 'selfie_with_document')
        }),
        ('Verification Details', {
            'fields': ('verified_by', 'verified_at', 'rejected_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'verified_by')