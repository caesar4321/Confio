from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import User, Account, Business, IdentityVerification, Country, Bank, BankInfo
from .models_unified import UnifiedTransactionTable

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
    list_display = ('account', 'payment_method_display', 'account_holder_name', 'account_type', 'masked_account', 'verification_status', 'is_default', 'created_at')
    list_filter = ('account_type', 'is_verified', 'is_default', 'is_public', 'payment_method__country_code', 'created_at')
    search_fields = ('account_holder_name', 'account__user__username', 'account__user__email', 'account_number', 'phone_number', 'email', 'payment_method__display_name')
    readonly_fields = ('created_at', 'updated_at', 'masked_account', 'full_bank_name')
    
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
    
    def payment_method_display(self, obj):
        """Display payment method with country flag"""
        if obj.payment_method:
            country_flags = {
                'VE': '🇻🇪', 'CO': '🇨🇴', 'AR': '🇦🇷', 'PE': '🇵🇪', 'CL': '🇨🇱',
                'BR': '🇧🇷', 'MX': '🇲🇽', 'US': '🇺🇸', 'DO': '🇩🇴', 'PA': '🇵🇦',
                'EC': '🇪🇨', 'BO': '🇧🇴', 'UY': '🇺🇾', 'PY': '🇵🇾', 'GT': '🇬🇹',
                'HN': '🇭🇳', 'SV': '🇸🇻', 'NI': '🇳🇮', 'CR': '🇨🇷', 'CU': '🇨🇺',
                'JM': '🇯🇲', 'TT': '🇹🇹'
            }
            flag = country_flags.get(obj.payment_method.country_code, '🌐')
            return f"{flag} {obj.payment_method.display_name}"
        return obj.full_bank_name()
    payment_method_display.short_description = "Payment Method"
    
    def masked_account(self, obj):
        return obj.get_masked_account_number()
    masked_account.short_description = "Account Number"
    
    def verification_status(self, obj):
        if obj.is_verified:
            return format_html('<span style="color: green;">✓ Verified</span>')
        return format_html('<span style="color: orange;">Unverified</span>')
    verification_status.short_description = "Verification"
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related(
            'account__user', 'account__business', 'payment_method', 'bank__country', 'country'
        )

@admin.register(UnifiedTransactionTable)
class UnifiedTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction_hash_short', 'type_display', 'amount_display', 'token_type', 'status_display', 'sender_info', 'counterparty_info', 'created_at', 'transaction_date')
    list_filter = ('transaction_type', 'token_type', 'status', 'sender_type', 'counterparty_type', 'created_at')
    search_fields = ('transaction_hash', 'sender_display_name', 'counterparty_display_name', 'description', 'sender_address', 'counterparty_address', 'sender_phone', 'counterparty_phone')
    date_hierarchy = 'created_at'
    list_per_page = 50
    
    # Now this is a table with foreign keys, we can edit some fields
    readonly_fields = (
        'id', 'send_transaction', 'payment_transaction', 'conversion', 'p2p_trade',
        'created_at', 'updated_at', 'transaction_date', 'deleted_at',
        'source_transaction_link'
    )
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('id', 'transaction_type', 'status', 'transaction_hash', 'amount', 'token_type', 'source_transaction_link')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'transaction_date', 'updated_at', 'deleted_at')
        }),
        ('Sender Information', {
            'fields': ('sender_display_name', 'sender_type', 'sender_address', 'sender_phone', 'sender_user', 'sender_business')
        }),
        ('Counterparty Information', {
            'fields': ('counterparty_display_name', 'counterparty_type', 'counterparty_address', 'counterparty_phone', 'counterparty_user', 'counterparty_business')
        }),
        ('Additional Details', {
            'fields': ('description', 'invoice_id', 'payment_reference_id', 'error_message'),
            'classes': ('collapse',)
        }),
        ('Raw Addresses', {
            'fields': ('from_address', 'to_address'),
            'classes': ('collapse',)
        }),
        ('Source Transaction Links', {
            'fields': ('send_transaction', 'payment_transaction', 'conversion', 'p2p_trade'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False  # Unified transactions are created automatically via signals
    
    def has_change_permission(self, request, obj=None):
        return True  # Allow viewing details
    
    def has_delete_permission(self, request, obj=None):
        return False  # Don't allow manual deletion
    
    def transaction_hash_short(self, obj):
        if obj.transaction_hash:
            return format_html(
                '<span title="{}" style="font-family: monospace;">{}</span>',
                obj.transaction_hash,
                f"{obj.transaction_hash[:10]}..."
            )
        return format_html('<span style="color: orange;">Pending</span>')
    transaction_hash_short.short_description = "Hash"
    
    def type_display(self, obj):
        """Display transaction type with icon"""
        icons = {
            'send': '📤',
            'payment': '🛒',
            'conversion': '🔄',
            'exchange': '💱'
        }
        colors = {
            'send': '#3B82F6',
            'payment': '#8B5CF6',
            'conversion': '#34D399',
            'exchange': '#F59E0B'
        }
        icon = icons.get(obj.transaction_type, '📄')
        color = colors.get(obj.transaction_type, '#6B7280')
        return format_html(
            '<span style="color: {};">{} {}</span>',
            color,
            icon,
            obj.transaction_type.title()
        )
    type_display.short_description = "Type"
    
    def amount_display(self, obj):
        """Display amount with better formatting"""
        try:
            from decimal import Decimal
            amount = Decimal(obj.amount)
            formatted_amount = f"{amount:,.2f}"
            return format_html(
                '<span style="font-weight: bold; font-size: 1.1em;">{}</span> {}',
                formatted_amount,
                obj.token_type
            )
        except:
            return f"{obj.amount} {obj.token_type}"
    amount_display.short_description = "Amount"
    
    def sender_info(self, obj):
        """Display sender with type badge and phone"""
        if obj.sender_type == 'business':
            type_badge = format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">BUSINESS</span> '
            )
        else:
            type_badge = format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">PERSONAL</span> '
            )
        
        name_part = format_html('<strong>{}</strong>', obj.sender_display_name or 'Unknown')
        phone_part = format_html('<br><small>📱 {}</small>', obj.sender_phone) if obj.sender_phone else ''
        
        return format_html('{}{}{}', type_badge, name_part, phone_part)
    sender_info.short_description = "Sender"
    
    def counterparty_info(self, obj):
        """Display counterparty with type badge and phone"""
        # Special case for conversions - show SYSTEM badge
        if obj.transaction_type == 'conversion' and obj.counterparty_display_name == 'Confío System':
            type_badge = format_html(
                '<span style="background-color: #6B7280; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">SYSTEM</span> '
            )
        elif obj.counterparty_type == 'business':
            type_badge = format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">BUSINESS</span> '
            )
        else:
            type_badge = format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px;">PERSONAL</span> '
            )
        
        name_part = format_html('<strong>{}</strong>', obj.counterparty_display_name or 'Unknown')
        phone_part = format_html('<br><small>📱 {}</small>', obj.counterparty_phone) if obj.counterparty_phone else ''
        
        return format_html('{}{}{}', type_badge, name_part, phone_part)
    counterparty_info.short_description = "Counterparty"
    
    def status_display(self, obj):
        colors = {
            'CONFIRMED': 'green',
            'PENDING': 'orange',
            'FAILED': 'red',
            'SPONSORING': 'blue',
            'SIGNED': 'purple',
            'SUBMITTED': 'teal'
        }
        icons = {
            'CONFIRMED': '✅',
            'PENDING': '⏳',
            'FAILED': '❌',
            'SPONSORING': '💰',
            'SIGNED': '✍️',
            'SUBMITTED': '📤'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            colors.get(obj.status, 'black'),
            icons.get(obj.status, ''),
            obj.status
        )
    status_display.short_description = "Status"
    
    def source_transaction_link(self, obj):
        """Display link to source transaction"""
        if obj.send_transaction:
            url = reverse('admin:send_sendtransaction_change', args=[obj.send_transaction.id])
            return format_html('<a href="{}">Send Transaction #{}</a>', url, obj.send_transaction.id)
        elif obj.payment_transaction:
            url = reverse('admin:payments_paymenttransaction_change', args=[obj.payment_transaction.id])
            return format_html('<a href="{}">Payment Transaction #{}</a>', url, obj.payment_transaction.id)
        elif obj.conversion:
            url = reverse('admin:conversion_conversion_change', args=[obj.conversion.id])
            return format_html('<a href="{}">Conversion #{}</a>', url, obj.conversion.id)
        elif obj.p2p_trade:
            url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.p2p_trade.id])
            return format_html('<a href="{}">P2P Trade #{}</a>', url, obj.p2p_trade.id)
        return "No source"
    source_transaction_link.short_description = "Source"
    
    def transaction_date(self, obj):
        """Display the original transaction date"""
        if obj.transaction_date:
            return obj.transaction_date.strftime('%Y-%m-%d %H:%M:%S')
        return "-"
    transaction_date.short_description = "Original Date"
    transaction_date.admin_order_field = 'transaction_date'
    
    def get_queryset(self, request):
        """Optimize queries by using select_related"""
        return super().get_queryset(request).select_related(
            'sender_user', 'sender_business',
            'counterparty_user', 'counterparty_business',
            'send_transaction', 'payment_transaction', 
            'conversion', 'p2p_trade'
        )