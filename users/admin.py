from django.contrib import admin
from .models import User, Account, Business

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