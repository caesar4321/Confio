from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone
from .models import User, Account, Business, IdentityVerification, Country, Bank, BankInfo, ConfioRewardBalance, ConfioRewardTransaction, AchievementType, UserAchievement, InfluencerReferral, TikTokViralShare, InfluencerAmbassador, AmbassadorActivity, SuspiciousActivity
from .models_unified import UnifiedTransactionTable
from .models_employee import BusinessEmployee, EmployeeInvitation

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'firebase_uid', 'phone_display', 'verification_status_display', 'accounts_count', 'employment_status', 'is_staff', 'created_at')
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
    
    def employment_status(self, obj):
        active_employments = obj.employment_records.filter(is_active=True, deleted_at__isnull=True).select_related('business')
        if active_employments.exists():
            businesses = []
            for emp in active_employments[:3]:  # Show max 3
                role_icon = {'owner': '🏢', 'admin': '👑', 'manager': '👔', 'cashier': '💰'}.get(emp.role, '👤')
                businesses.append(f"{role_icon} {emp.business.name}")
            
            if active_employments.count() > 3:
                businesses.append(f"...+{active_employments.count() - 3} more")
            
            url = reverse('admin:users_businessemployee_changelist') + f'?user__id__exact={obj.id}'
            return format_html('<a href="{}">{}</a>', url, '<br>'.join(businesses))
        return "-"
    employment_status.short_description = "Employed At"

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
    list_display = ('name', 'category_display_name', 'owner_display', 'accounts_count', 'employees_count', 'business_registration_number', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('name', 'category', 'description', 'business_registration_number')
    readonly_fields = ('created_at', 'updated_at', 'owner_display')
    
    def owner_display(self, obj):
        from .models_employee import BusinessEmployee
        owner = BusinessEmployee.objects.filter(
            business=obj,
            role='owner',
            deleted_at__isnull=True
        ).select_related('user').first()
        
        if owner:
            user = owner.user
            name = user.get_full_name() or user.username
            url = reverse('admin:users_user_change', args=[user.id])
            return format_html('<a href="{}">🏢 {}</a>', url, name)
        return format_html('<span style="color: orange;">No owner</span>')
    owner_display.short_description = "Owner"
    
    def accounts_count(self, obj):
        count = obj.accounts.count()
        if count > 0:
            url = reverse('admin:users_account_changelist') + f'?business__id__exact={obj.id}'
            return format_html('<a href="{}">{} accounts</a>', url, count)
        return "0 accounts"
    accounts_count.short_description = "Accounts"
    
    def employees_count(self, obj):
        active_count = obj.employees.filter(is_active=True, deleted_at__isnull=True).count()
        total_count = obj.employees.filter(deleted_at__isnull=True).count()
        if total_count > 0:
            url = reverse('admin:users_businessemployee_changelist') + f'?business__id__exact={obj.id}'
            if active_count < total_count:
                return format_html('<a href="{}">{}/{} employees</a>', url, active_count, total_count)
            else:
                return format_html('<a href="{}">{} employees</a>', url, active_count)
        return "0 employees"
    employees_count.short_description = "Employees"

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

@admin.register(BusinessEmployee)
class BusinessEmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_name', 'business', 'role_display', 'status_display', 'hired_at', 'hired_by_name', 'shift_info')
    list_filter = ('role', 'is_active', 'business', 'hired_at')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name', 'business__name')
    readonly_fields = ('hired_at', 'deactivated_at', 'created_at', 'updated_at', 'deleted_at', 'permissions_display')
    
    fieldsets = (
        ('Employee Information', {
            'fields': ('business', 'user', 'role', 'is_active')
        }),
        ('Permissions', {
            'fields': ('permissions', 'permissions_display'),
            'description': 'Custom permissions override role defaults. Leave empty to use default role permissions. Owners have all permissions by default.'
        }),
        ('Shift Settings', {
            'fields': ('shift_start_time', 'shift_end_time', 'daily_transaction_limit'),
            'classes': ('collapse',)
        }),
        ('Employment History', {
            'fields': ('hired_by', 'hired_at', 'deactivated_by', 'deactivated_at', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def employee_name(self, obj):
        if obj.user.first_name or obj.user.last_name:
            full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
            return format_html('<strong>{}</strong><br><small>{}</small>', full_name, obj.user.username)
        return obj.user.username
    employee_name.short_description = "Employee"
    
    def role_display(self, obj):
        role_colors = {
            'owner': '#F59E0B',
            'admin': '#8B5CF6',
            'manager': '#3B82F6',
            'cashier': '#10B981'
        }
        role_icons = {
            'owner': '🏢',
            'admin': '👑',
            'manager': '👔',
            'cashier': '💰'
        }
        return format_html(
            '<span style="color: {};">{} {}</span>',
            role_colors.get(obj.role, '#6B7280'),
            role_icons.get(obj.role, '👤'),
            obj.get_role_display()
        )
    role_display.short_description = "Role"
    
    def status_display(self, obj):
        if obj.is_active:
            if obj.is_within_shift():
                return format_html('<span style="color: green;">✅ Active (In Shift)</span>')
            return format_html('<span style="color: green;">✅ Active</span>')
        return format_html('<span style="color: red;">❌ Inactive</span>')
    status_display.short_description = "Status"
    
    def hired_by_name(self, obj):
        if obj.hired_by:
            return obj.hired_by.get_full_name() or obj.hired_by.username
        return "-"
    hired_by_name.short_description = "Hired By"
    
    def shift_info(self, obj):
        if obj.shift_start_time and obj.shift_end_time:
            return f"{obj.shift_start_time} - {obj.shift_end_time}"
        return "No shift set"
    shift_info.short_description = "Shift"
    
    def permissions_display(self, obj):
        permissions = obj.get_effective_permissions()
        if not permissions:
            return "Using role defaults"
        
        html = '<table style="width: 100%; font-size: 12px;">'
        for key, value in permissions.items():
            icon = '✅' if value else '❌'
            html += f'<tr><td>{key.replace("_", " ").title()}:</td><td>{icon}</td></tr>'
        html += '</table>'
        return format_html(html)
    permissions_display.short_description = "Effective Permissions"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('business', 'user', 'hired_by', 'deactivated_by')

@admin.register(EmployeeInvitation)
class EmployeeInvitationAdmin(admin.ModelAdmin):
    list_display = ('invitation_code', 'business', 'employee_info', 'role_display', 'status_display', 'created_at', 'expires_at_display', 'invited_by_name')
    list_filter = ('status', 'role', 'business', 'created_at', 'expires_at')
    search_fields = ('invitation_code', 'employee_phone', 'employee_name', 'business__name', 'invited_by__username')
    readonly_fields = ('invitation_code', 'created_at', 'updated_at', 'accepted_at', 'deleted_at')
    
    fieldsets = (
        ('Invitation Details', {
            'fields': ('business', 'invitation_code', 'status')
        }),
        ('Employee Information', {
            'fields': ('employee_phone', 'employee_phone_country', 'employee_name', 'role', 'permissions')
        }),
        ('Message', {
            'fields': ('message',),
            'classes': ('wide',)
        }),
        ('Invitation History', {
            'fields': ('invited_by', 'created_at', 'expires_at', 'accepted_by', 'accepted_at')
        }),
        ('Timestamps', {
            'fields': ('updated_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def employee_info(self, obj):
        country_flags = {
            'VE': '🇻🇪', 'CO': '🇨🇴', 'AR': '🇦🇷', 'PE': '🇵🇪', 'CL': '🇨🇱',
            'BR': '🇧🇷', 'MX': '🇲🇽', 'US': '🇺🇸', 'DO': '🇩🇴', 'PA': '🇵🇦'
        }
        flag = country_flags.get(obj.employee_phone_country, '🌐')
        name = obj.employee_name or "No name"
        return format_html(
            '<strong>{}</strong><br>{} {}',
            name,
            flag,
            obj.employee_phone
        )
    employee_info.short_description = "Employee"
    
    def role_display(self, obj):
        role_colors = {
            'owner': '#F59E0B',
            'admin': '#8B5CF6',
            'manager': '#3B82F6',
            'cashier': '#10B981'
        }
        role_icons = {
            'owner': '🏢',
            'admin': '👑',
            'manager': '👔',
            'cashier': '💰'
        }
        return format_html(
            '<span style="color: {};">{} {}</span>',
            role_colors.get(obj.role, '#6B7280'),
            role_icons.get(obj.role, '👤'),
            obj.get_role_display()
        )
    role_display.short_description = "Role"
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#F59E0B',
            'accepted': '#10B981',
            'expired': '#6B7280',
            'cancelled': '#EF4444'
        }
        status_icons = {
            'pending': '⏳',
            'accepted': '✅',
            'expired': '⏰',
            'cancelled': '❌'
        }
        
        # Check if expired
        if obj.status == 'pending' and obj.is_expired:
            status = 'expired'
            display_status = 'Expired'
        else:
            status = obj.status
            display_status = obj.get_status_display()
        
        return format_html(
            '<span style="color: {};">{} {}</span>',
            status_colors.get(status, '#6B7280'),
            status_icons.get(status, '❓'),
            display_status
        )
    status_display.short_description = "Status"
    
    def expires_at_display(self, obj):
        if obj.is_expired:
            return format_html('<span style="color: red;">Expired</span>')
        elif obj.status == 'accepted':
            return format_html('<span style="color: green;">Accepted</span>')
        elif obj.status == 'cancelled':
            return format_html('<span style="color: gray;">Cancelled</span>')
        else:
            from django.utils import timezone
            time_left = obj.expires_at - timezone.now()
            days = time_left.days
            if days > 1:
                return f"In {days} days"
            elif days == 1:
                return "Tomorrow"
            elif days == 0:
                hours = time_left.seconds // 3600
                if hours > 0:
                    return f"In {hours} hours"
                else:
                    return format_html('<span style="color: orange;">Soon</span>')
            else:
                return format_html('<span style="color: red;">Expired</span>')
    expires_at_display.short_description = "Expires"
    
    def invited_by_name(self, obj):
        if obj.invited_by:
            return obj.invited_by.get_full_name() or obj.invited_by.username
        return "-"
    invited_by_name.short_description = "Invited By"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('business', 'invited_by', 'accepted_by')


@admin.register(ConfioRewardBalance)
class ConfioRewardBalanceAdmin(admin.ModelAdmin):
    """Admin for CONFIO reward balances"""
    list_display = ('user', 'total_locked_display', 'total_earned_display', 'sources_breakdown', 'lock_status', 'last_reward_at')
    list_filter = ('migration_status', 'lock_until', 'created_at')
    search_fields = ('user__username', 'user__email', 'user__phone_number')
    readonly_fields = (
        'user', 'total_earned', 'total_locked', 'total_unlocked',
        'achievement_rewards', 'referral_rewards', 'viral_rewards',
        'presale_purchase', 'other_rewards', 'last_reward_at',
        'daily_reward_count', 'daily_reward_amount', 'created_at', 'updated_at'
    )
    
    def total_locked_display(self, obj):
        return format_html(
            '<strong style="color: #8b5cf6;">{} CONFIO</strong>',
            obj.total_locked
        )
    total_locked_display.short_description = "Locked Balance"
    
    def total_earned_display(self, obj):
        return format_html(
            '{} CONFIO<br><small style="color: #6B7280;">${}</small>',
            obj.total_earned,
            obj.total_earned / 4  # 4 CONFIO = $1
        )
    total_earned_display.short_description = "Total Earned"
    
    def sources_breakdown(self, obj):
        sources = []
        if obj.achievement_rewards > 0:
            sources.append(f"🏆 {obj.achievement_rewards}")
        if obj.referral_rewards > 0:
            sources.append(f"🤝 {obj.referral_rewards}")
        if obj.viral_rewards > 0:
            sources.append(f"🚀 {obj.viral_rewards}")
        if obj.presale_purchase > 0:
            sources.append(f"💰 {obj.presale_purchase}")
        if obj.other_rewards > 0:
            sources.append(f"🎁 {obj.other_rewards}")
        
        return format_html('<br>'.join(sources)) if sources else "No rewards yet"
    sources_breakdown.short_description = "Sources"
    
    def lock_status(self, obj):
        if not obj.lock_until:
            return format_html('<span style="color: green;">✅ Unlocked</span>')
        
        from django.utils import timezone
        if obj.lock_until > timezone.now():
            days_left = (obj.lock_until - timezone.now()).days
            return format_html(
                '<span style="color: orange;">🔒 {} days</span>',
                days_left
            )
        else:
            return format_html('<span style="color: green;">🔓 Ready to unlock</span>')
    lock_status.short_description = "Lock Status"


@admin.register(ConfioRewardTransaction)
class ConfioRewardTransactionAdmin(admin.ModelAdmin):
    """Admin for CONFIO reward transactions (pre-blockchain accounting)"""
    list_display = ('user', 'transaction_type_display', 'amount_display', 'source', 'description', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'source', 'description')
    readonly_fields = ('user', 'transaction_type', 'amount', 'balance_after', 'source', 'description', 'achievement', 'referral', 'metadata', 'created_at')
    date_hierarchy = 'created_at'
    
    def transaction_type_display(self, obj):
        type_icons = {
            'reward': '🎁',
            'presale': '💰',
            'unlock': '🔓',
            'migration': '🚀',
            'adjustment': '⚡'
        }
        
        type_colors = {
            'reward': '#10b981',
            'presale': '#8b5cf6',
            'unlock': '#3b82f6',
            'migration': '#f59e0b',
            'adjustment': '#6b7280'
        }
        
        return format_html(
            '<span style="color: {};">{} {}</span>',
            type_colors.get(obj.transaction_type, '#6b7280'),
            type_icons.get(obj.transaction_type, '❓'),
            obj.get_transaction_type_display()
        )
    transaction_type_display.short_description = "Type"
    
    def amount_display(self, obj):
        return format_html(
            '<strong>{} CONFIO</strong><br><small style="color: #6B7280;">${}</small>',
            obj.amount,
            obj.amount / 4  # 4 CONFIO = $1
        )
    amount_display.short_description = "Amount"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'achievement', 'referral')


@admin.register(AchievementType)
class AchievementTypeAdmin(admin.ModelAdmin):
    """Admin for achievement types"""
    list_display = ('name', 'slug', 'category_display', 'confio_reward_display', 'is_active', 'created_at')
    list_filter = ('category', 'is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('category', 'display_order', 'name')
    
    def get_queryset(self, request):
        # Ensure we're not filtering out soft-deleted items
        return super().get_queryset(request).filter(deleted_at__isnull=True)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'icon_emoji', 'color')
        }),
        ('Classification', {
            'fields': ('category', 'display_order')
        }),
        ('Rewards', {
            'fields': ('confio_reward', 'is_repeatable', 'requires_manual_review')
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )
    
    def category_display(self, obj):
        categories = {
            'onboarding': '👋 Bienvenida',
            'trading': '💱 Intercambios',
            'payments': '💸 Pagos',
            'social': '👥 Comunidad',
            'verification': '✅ Verificación',
            'ambassador': '👑 Embajador',
            # Also support old category names
            'bienvenida': '👋 Bienvenida',
            'verificacion': '✅ Verificación',
            'viral': '🚀 Viral',
            'embajador': '👑 Embajador'
        }
        return categories.get(obj.category, obj.category)
    category_display.short_description = "Category"
    
    def confio_reward_display(self, obj):
        return format_html(
            '<strong>{} CONFIO</strong><br><small style="color: #6B7280;">${}</small>',
            obj.confio_reward,
            obj.confio_reward / 4  # 4 CONFIO = $1
        )
    confio_reward_display.short_description = "Reward"


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    """Admin for user achievements"""
    list_display = ('user', 'achievement_type', 'status_display', 'earned_at', 'claimed_at', 'can_claim')
    list_filter = ('status', 'earned_at', 'claimed_at', 'achievement_type__category')
    search_fields = ('user__username', 'user__email', 'achievement_type__name')
    readonly_fields = ('earned_at', 'claimed_at', 'created_at', 'updated_at')
    raw_id_fields = ('user', 'achievement_type')
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#9CA3AF',
            'earned': '#F59E0B',
            'claimed': '#10B981',
            'expired': '#EF4444'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"
    
    def can_claim(self, obj):
        if obj.can_claim_reward:
            return format_html('<span style="color: #10B981;">✅ Yes</span>')
        return format_html('<span style="color: #9CA3AF;">❌ No</span>')
    can_claim.short_description = "Can Claim?"
    
    actions = ['mark_as_earned', 'mark_as_claimed']
    
    def mark_as_earned(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status='pending').update(
            status='earned',
            earned_at=timezone.now()
        )
        self.message_user(request, f"{updated} achievements marked as earned.")
    mark_as_earned.short_description = "Mark selected as earned"
    
    def mark_as_claimed(self, request, queryset):
        from django.utils import timezone
        count = 0
        for achievement in queryset.filter(status='earned'):
            if achievement.claim_reward():
                count += 1
        self.message_user(request, f"{count} achievements claimed with rewards distributed.")
    mark_as_claimed.short_description = "Claim rewards for selected"


@admin.register(InfluencerReferral)
class InfluencerReferralAdmin(admin.ModelAdmin):
    """Admin for influencer referrals"""
    list_display = ('tiktok_username', 'referred_user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('referred_user__username', 'referred_user__email', 'tiktok_username')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('referred_user', 'influencer_user')
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#9CA3AF',
            'active': '#10B981',
            'converted': '#8B5CF6',
            'ambassador': '#F59E0B'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"


@admin.register(TikTokViralShare)
class TikTokViralShareAdmin(admin.ModelAdmin):
    """Admin for TikTok viral shares"""
    list_display = ('user', 'tiktok_username', 'share_type', 'status_display', 'created_at')
    list_filter = ('status', 'share_type', 'created_at')
    search_fields = ('user__username', 'tiktok_username', 'tiktok_url')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user', 'achievement')
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#9CA3AF',
            'submitted': '#3B82F6',
            'verified': '#10B981',
            'rewarded': '#8B5CF6',
            'rejected': '#EF4444'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"
    
    def view_count_display(self, obj):
        # View count would be tracked in metadata or separate model
        return format_html('<span style="color: #6B7280;">-</span>')
    view_count_display.short_description = "Views"
    
    actions = ['verify_shares', 'update_view_counts']
    
    def verify_shares(self, request, queryset):
        updated = queryset.filter(status='submitted').update(status='verified')
        self.message_user(request, f"{updated} shares verified.")
    verify_shares.short_description = "Verify selected shares"
    
    def update_view_counts(self, request, queryset):
        # In production, this would trigger async task to fetch view counts
        self.message_user(request, "View count update task queued.")
    update_view_counts.short_description = "Update view counts"


@admin.register(InfluencerAmbassador)
class InfluencerAmbassadorAdmin(admin.ModelAdmin):
    """Admin for influencer ambassadors"""
    list_display = ('user', 'tier_display', 'status_display', 'total_referrals', 'total_viral_views_display', 
                    'confio_earned_display', 'performance_score_display', 'last_activity_at')
    list_filter = ('tier', 'status', 'dedicated_support', 'tier_achieved_at')
    search_fields = ('user__username', 'user__email', 'custom_referral_code')
    readonly_fields = ('created_at', 'updated_at', 'tier_achieved_at', 'last_activity_at', 
                       'next_tier_progress_display', 'benefits_display')
    raw_id_fields = ('user',)
    
    fieldsets = (
        ('Ambassador Information', {
            'fields': ('user', 'tier', 'status', 'custom_referral_code')
        }),
        ('Performance Metrics', {
            'fields': ('total_referrals', 'active_referrals', 'total_viral_views', 
                       'monthly_viral_views', 'referral_transaction_volume', 'confio_earned')
        }),
        ('Tier Progression', {
            'fields': ('tier_achieved_at', 'next_tier_progress_display', 'performance_score')
        }),
        ('Benefits & Support', {
            'fields': ('benefits_display', 'dedicated_support', 'ambassador_notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_activity_at'),
            'classes': ('collapse',)
        }),
    )
    
    def tier_display(self, obj):
        tier_colors = {
            'bronze': '#CD7F32',
            'silver': '#C0C0C0',
            'gold': '#FFD700',
            'diamond': '#B9F2FF'
        }
        tier_icons = {
            'bronze': '🥉',
            'silver': '🥈',
            'gold': '🥇',
            'diamond': '💎'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            tier_colors.get(obj.tier, '#000'),
            tier_icons.get(obj.tier, ''),
            obj.get_tier_display()
        )
    tier_display.short_description = "Tier"
    
    def status_display(self, obj):
        status_colors = {
            'active': '#10B981',
            'paused': '#F59E0B',
            'revoked': '#EF4444'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"
    
    def total_viral_views_display(self, obj):
        if obj.total_viral_views >= 1000000:
            return format_html('<strong>{:.1f}M</strong>', obj.total_viral_views / 1000000)
        elif obj.total_viral_views >= 1000:
            return format_html('<strong>{:.1f}K</strong>', obj.total_viral_views / 1000)
        return format_html('<strong>{}</strong>', obj.total_viral_views)
    total_viral_views_display.short_description = "Total Views"
    
    def confio_earned_display(self, obj):
        return format_html('<strong>{:,.0f} $CONFIO</strong>', obj.confio_earned)
    confio_earned_display.short_description = "CONFIO Earned"
    
    def performance_score_display(self, obj):
        color = '#10B981' if obj.performance_score >= 80 else '#F59E0B' if obj.performance_score >= 50 else '#EF4444'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            color,
            obj.performance_score
        )
    performance_score_display.short_description = "Performance"
    
    def next_tier_progress_display(self, obj):
        progress = obj.calculate_tier_progress()
        return format_html(
            '<div style="width: 200px; background-color: #E5E7EB; border-radius: 4px; height: 20px;">'
            '<div style="width: {}%; background-color: #8B5CF6; height: 100%; border-radius: 4px; text-align: center; color: white; line-height: 20px;">'
            '{}%</div></div>',
            progress, progress
        )
    next_tier_progress_display.short_description = "Progress to Next Tier"
    
    def benefits_display(self, obj):
        if not obj.benefits:
            return "-"
        benefits_html = "<ul style='margin: 0; padding-left: 20px;'>"
        for key, value in obj.benefits.items():
            benefits_html += f"<li><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
        benefits_html += "</ul>"
        return format_html(benefits_html)
    benefits_display.short_description = "Current Benefits"
    
    actions = ['update_tier', 'calculate_monthly_bonus', 'pause_ambassadors', 'activate_ambassadors']
    
    def update_tier(self, request, queryset):
        for ambassador in queryset:
            ambassador.next_tier_progress = ambassador.calculate_tier_progress()
            ambassador.save()
        self.message_user(request, f"Updated tier progress for {queryset.count()} ambassadors.")
    update_tier.short_description = "Update tier progress"
    
    def calculate_monthly_bonus(self, request, queryset):
        total_bonus = 0
        for ambassador in queryset.filter(status='active'):
            bonus = ambassador.benefits.get('monthly_bonus', 0)
            if bonus > 0:
                total_bonus += bonus
                # In production, this would create ConfioRewardTransaction
        self.message_user(request, f"Monthly bonus calculated: {total_bonus} $CONFIO for {queryset.count()} ambassadors.")
    calculate_monthly_bonus.short_description = "Calculate monthly bonus"
    
    def pause_ambassadors(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f"{updated} ambassadors paused.")
    pause_ambassadors.short_description = "Pause selected ambassadors"
    
    def activate_ambassadors(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} ambassadors activated.")
    activate_ambassadors.short_description = "Activate selected ambassadors"


@admin.register(AmbassadorActivity)
class AmbassadorActivityAdmin(admin.ModelAdmin):
    """Admin for ambassador activities"""
    list_display = ('ambassador', 'activity_type_display', 'description', 'confio_rewarded_display', 'created_at')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('ambassador__user__username', 'description')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('ambassador',)
    date_hierarchy = 'created_at'
    
    def activity_type_display(self, obj):
        type_colors = {
            'referral': '#3B82F6',
            'viral_milestone': '#8B5CF6',
            'tier_upgrade': '#10B981',
            'monthly_bonus': '#F59E0B',
            'special_achievement': '#EC4899'
        }
        type_icons = {
            'referral': '👥',
            'viral_milestone': '🚀',
            'tier_upgrade': '⬆️',
            'monthly_bonus': '💰',
            'special_achievement': '🏆'
        }
        return format_html(
            '<span style="color: {};">{} {}</span>',
            type_colors.get(obj.activity_type, '#000'),
            type_icons.get(obj.activity_type, ''),
            obj.get_activity_type_display()
        )
    activity_type_display.short_description = "Activity Type"
    
    def confio_rewarded_display(self, obj):
        if obj.confio_rewarded > 0:
            return format_html('<strong style="color: #10B981;">+{:,.0f} $CONFIO</strong>', obj.confio_rewarded)
        return "-"
    confio_rewarded_display.short_description = "Reward"


@admin.register(SuspiciousActivity)
class SuspiciousActivityAdmin(admin.ModelAdmin):
    """Admin for suspicious activity logs"""
    list_display = ('user', 'action', 'flags_display', 'ip_address', 'reviewed_display', 
                    'action_taken_display', 'created_at')
    list_filter = ('reviewed', 'action_taken', 'action', 'created_at')
    search_fields = ('user__username', 'user__email', 'ip_address', 'device_fingerprint')
    readonly_fields = ('created_at', 'updated_at', 'user', 'action', 'flags', 'metadata', 
                       'ip_address', 'device_fingerprint')
    raw_id_fields = ('user', 'reviewed_by')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Activity Details', {
            'fields': ('user', 'action', 'flags', 'metadata', 'ip_address', 'device_fingerprint')
        }),
        ('Review Status', {
            'fields': ('reviewed', 'reviewed_by', 'reviewed_at', 'action_taken', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def flags_display(self, obj):
        if not obj.flags:
            return "-"
        flags_html = []
        flag_colors = {
            'multiple_accounts_per_device': '#EF4444',
            'rapid_referral_submission': '#F59E0B',
            'similar_usernames_detected': '#8B5CF6',
            'high_transaction_velocity': '#EF4444',
        }
        for flag in obj.flags:
            color = flag_colors.get(flag, '#6B7280')
            flags_html.append(f'<span style="color: {color}; font-weight: bold;">{flag}</span>')
        return format_html('<br>'.join(flags_html))
    flags_display.short_description = "Flags"
    
    def reviewed_display(self, obj):
        if obj.reviewed:
            return format_html(
                '<span style="color: #10B981;">✓ Reviewed by {}</span>',
                obj.reviewed_by.username if obj.reviewed_by else 'Unknown'
            )
        return format_html('<span style="color: #F59E0B;">⏳ Pending</span>')
    reviewed_display.short_description = "Review Status"
    
    def action_taken_display(self, obj):
        action_colors = {
            'none': '#6B7280',
            'warning': '#F59E0B',
            'suspended': '#EF4444',
            'banned': '#991B1B',
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            action_colors.get(obj.action_taken, '#000'),
            obj.get_action_taken_display()
        )
    action_taken_display.short_description = "Action Taken"
    
    actions = ['mark_as_reviewed', 'issue_warning', 'suspend_accounts', 'ban_accounts']
    
    def mark_as_reviewed(self, request, queryset):
        updated = queryset.filter(reviewed=False).update(
            reviewed=True,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            action_taken='none'
        )
        self.message_user(request, f"{updated} activities marked as reviewed.")
    mark_as_reviewed.short_description = "Mark as reviewed (no action)"
    
    def issue_warning(self, request, queryset):
        for activity in queryset.filter(reviewed=False):
            activity.reviewed = True
            activity.reviewed_by = request.user
            activity.reviewed_at = timezone.now()
            activity.action_taken = 'warning'
            activity.save()
            # In production, send warning email to user
        self.message_user(request, f"Warnings issued for {queryset.count()} activities.")
    issue_warning.short_description = "Issue warning to users"
    
    def suspend_accounts(self, request, queryset):
        users_to_suspend = set()
        for activity in queryset:
            users_to_suspend.add(activity.user)
            activity.reviewed = True
            activity.reviewed_by = request.user
            activity.reviewed_at = timezone.now()
            activity.action_taken = 'suspended'
            activity.save()
        
        # In production, implement actual suspension logic
        self.message_user(request, f"{len(users_to_suspend)} accounts marked for suspension.")
    suspend_accounts.short_description = "Suspend user accounts"
    
    def ban_accounts(self, request, queryset):
        users_to_ban = set()
        for activity in queryset:
            users_to_ban.add(activity.user)
            activity.reviewed = True
            activity.reviewed_by = request.user
            activity.reviewed_at = timezone.now()
            activity.action_taken = 'banned'
            activity.save()
        
        # In production, implement actual ban logic
        self.message_user(request, f"{len(users_to_ban)} accounts marked for ban.")
    ban_accounts.short_description = "Ban user accounts"
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('user', 'reviewed_by')