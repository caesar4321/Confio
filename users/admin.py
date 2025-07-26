from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import User, Account, Business, IdentityVerification, Country, Bank, BankInfo
from .models_views import UnifiedTransaction

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'firebase_uid', 'phone_display', 'verification_status_display', 'accounts_count', 'is_staff', 'created_at')
    list_filter = ('is_staff', 'is_superuser', 'phone_country', 'created_at')
    search_fields = ('username', 'email', 'firebase_uid', 'first_name', 'last_name')
    readonly_fields = ('firebase_uid', 'auth_token_version', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('username', 'email', 'first_name', 'last_name', 'firebase_uid')
        }),
        ('Contact Information', {
            'fields': ('phone_country', 'phone_number')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Security', {
            'fields': ('auth_token_version',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )
    
    def phone_display(self, obj):
        if obj.phone_country and obj.phone_number:
            return f"{obj.phone_country_code} {obj.phone_number}"
        return "No phone"
    phone_display.short_description = "Phone"
    
    def verification_status_display(self, obj):
        status = obj.verification_status
        colors = {
            'verified': 'green',
            'pending': 'orange', 
            'rejected': 'red',
            'unverified': 'gray'
        }
        return format_html(
            '<span style="color: {};">{}</span>',
            colors.get(status, 'black'),
            status.title()
        )
    verification_status_display.short_description = "Verification"
    
    def accounts_count(self, obj):
        count = obj.accounts.count()
        url = reverse('admin:users_account_changelist') + f'?user__id__exact={obj.id}'
        return format_html('<a href="{}">{} accounts</a>', url, count)
    accounts_count.short_description = "Accounts"

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'user', 'account_type', 'account_index', 'sui_address_short', 'bank_accounts_count', 'created_at')
    list_filter = ('account_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'business__name', 'sui_address')
    readonly_fields = ('account_id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Account Information', {
            'fields': ('user', 'account_type', 'account_index', 'account_id', 'business')
        }),
        ('Blockchain', {
            'fields': ('sui_address',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_login_at'),
            'classes': ('collapse',)
        }),
    )
    
    def sui_address_short(self, obj):
        if obj.sui_address:
            return f"{obj.sui_address[:10]}...{obj.sui_address[-6:]}"
        return "No address"
    sui_address_short.short_description = "Sui Address"
    
    def bank_accounts_count(self, obj):
        count = obj.bank_accounts.count()
        if count > 0:
            url = reverse('admin:users_bankinfo_changelist') + f'?account__id__exact={obj.id}'
            return format_html('<a href="{}">{} payment methods</a>', url, count)
        return "0 payment methods"
    bank_accounts_count.short_description = "Payment Methods"

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_display_name', 'accounts_count', 'business_registration_number', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('name', 'category', 'description', 'business_registration_number')
    readonly_fields = ('created_at', 'updated_at')
    
    def accounts_count(self, obj):
        count = obj.accounts.count()
        if count > 0:
            url = reverse('admin:users_account_changelist') + f'?business__id__exact={obj.id}'
            return format_html('<a href="{}">{} accounts</a>', url, count)
        return "0 accounts"
    accounts_count.short_description = "Accounts"

@admin.register(IdentityVerification)
class IdentityVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'document_type', 'document_number', 'status_display', 'created_at', 'verified_at')
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
    
    def status_display(self, obj):
        colors = {
            'verified': 'green',
            'pending': 'orange',
            'rejected': 'red',
            'expired': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'verified_by')

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'flag_emoji', 'currency_code', 'currency_symbol', 'banks_count', 'is_active', 'display_order')
    list_filter = ('is_active', 'requires_identification', 'supports_phone_payments')
    search_fields = ('name', 'code', 'currency_code')
    ordering = ('display_order', 'name')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'flag_emoji', 'display_order', 'is_active')
        }),
        ('Currency', {
            'fields': ('currency_code', 'currency_symbol')
        }),
        ('Requirements', {
            'fields': ('requires_identification', 'identification_name', 'identification_format', 'account_number_length')
        }),
        ('Features', {
            'fields': ('supports_phone_payments',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def banks_count(self, obj):
        count = obj.banks.count()
        if count > 0:
            url = reverse('admin:users_bank_changelist') + f'?country__id__exact={obj.id}'
            return format_html('<a href="{}">{} banks</a>', url, count)
        return "0 banks"
    banks_count.short_description = "Banks"

@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'code', 'account_types_display', 'bank_accounts_count', 'is_active', 'display_order')
    list_filter = ('country', 'is_active', 'supports_checking', 'supports_savings', 'supports_payroll')
    search_fields = ('name', 'code', 'short_name', 'country__name')
    ordering = ('country__display_order', 'display_order', 'name')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('country', 'name', 'code', 'short_name', 'display_order', 'is_active')
        }),
        ('Account Type Support', {
            'fields': ('supports_checking', 'supports_savings', 'supports_payroll')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def account_types_display(self, obj):
        types = []
        if obj.supports_savings:
            types.append('Savings')
        if obj.supports_checking:
            types.append('Checking')
        if obj.supports_payroll:
            types.append('Payroll')
        return ', '.join(types) if types else 'None'
    account_types_display.short_description = "Account Types"
    
    def bank_accounts_count(self, obj):
        count = obj.bank_accounts.count()
        if count > 0:
            url = reverse('admin:users_bankinfo_changelist') + f'?bank__id__exact={obj.id}'
            return format_html('<a href="{}">{} accounts</a>', url, count)
        return "0 accounts"
    bank_accounts_count.short_description = "User Accounts"

@admin.register(BankInfo)
class BankInfoAdmin(admin.ModelAdmin):
    list_display = ('account', 'full_bank_name', 'account_holder_name', 'account_type', 'masked_account', 'verification_status', 'is_default', 'created_at')
    list_filter = ('account_type', 'is_verified', 'is_default', 'is_public', 'created_at')
    search_fields = ('account_holder_name', 'account__user__username', 'account__user__email', 'account_number', 'phone_number', 'email')
    readonly_fields = ('created_at', 'updated_at', 'masked_account')
    
    fieldsets = (
        ('Account Information', {
            'fields': ('account', 'payment_method', 'account_holder_name')
        }),
        ('Legacy Bank Information', {
            'fields': ('bank', 'country', 'account_type'),
            'classes': ('collapse',),
            'description': 'Legacy fields - use payment_method instead'
        }),
        ('Payment Details', {
            'fields': ('account_number', 'phone_number', 'email', 'username', 'identification_number')
        }),
        ('Settings', {
            'fields': ('is_default', 'is_public')
        }),
        ('Verification', {
            'fields': ('is_verified', 'verified_at', 'verified_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def masked_account(self, obj):
        return obj.get_masked_account_number()
    masked_account.short_description = "Account Number"
    
    def verification_status(self, obj):
        if obj.is_verified:
            return format_html('<span style="color: green;">✓ Verified</span>')
        return format_html('<span style="color: orange;">Unverified</span>')
    verification_status.short_description = "Verification"

@admin.register(UnifiedTransaction)
class UnifiedTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_hash_short', 'transaction_type', 'amount_display', 'token_type', 'status_display', 'sender_display_name', 'counterparty_display_name', 'created_at')
    list_filter = ('transaction_type', 'token_type', 'status', 'sender_type', 'counterparty_type', 'created_at')
    search_fields = ('transaction_hash', 'sender_display_name', 'counterparty_display_name', 'description', 'sender_address', 'counterparty_address')
    # This is a view, so everything should be read-only
    readonly_fields = (
        'transaction_type', 'created_at', 'updated_at', 'deleted_at', 'amount', 'token_type', 
        'status', 'transaction_hash', 'error_message', 'sender_user', 'sender_business',
        'sender_type', 'sender_display_name', 'sender_phone', 'sender_address',
        'counterparty_user', 'counterparty_business', 'counterparty_type',
        'counterparty_display_name', 'counterparty_phone', 'counterparty_address',
        'description', 'invoice_id', 'payment_transaction_id', 'from_address', 'to_address'
    )
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('transaction_type', 'status', 'transaction_hash', 'amount', 'token_type', 'created_at')
        }),
        ('Sender Information', {
            'fields': ('sender_display_name', 'sender_type', 'sender_address', 'sender_phone')
        }),
        ('Counterparty Information', {
            'fields': ('counterparty_display_name', 'counterparty_type', 'counterparty_address', 'counterparty_phone')
        }),
        ('Additional Details', {
            'fields': ('description', 'invoice_id', 'payment_transaction_id', 'error_message'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False  # Can't add to views
    
    def has_change_permission(self, request, obj=None):
        return False  # Can't modify views
    
    def has_delete_permission(self, request, obj=None):
        return False  # Can't delete from views
    
    def transaction_hash_short(self, obj):
        if obj.transaction_hash:
            return f"{obj.transaction_hash[:10]}..."
        return "Pending"
    transaction_hash_short.short_description = "Hash"
    
    def amount_display(self, obj):
        return f"{obj.amount} {obj.token_type}"
    amount_display.short_description = "Amount"
    
    def status_display(self, obj):
        colors = {
            'CONFIRMED': 'green',
            'PENDING': 'orange',
            'FAILED': 'red',
            'SPONSORING': 'blue',
            'SIGNED': 'purple',
            'SUBMITTED': 'teal'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.status
        )
    status_display.short_description = "Status"