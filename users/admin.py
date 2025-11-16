from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.contrib import messages
from django.db import transaction
import secrets
from .models import User, Account, Business, Country, Bank, BankInfo, WalletPepper, WalletDerivationPepper
from .models_unified import UnifiedTransactionTable
from .models_employee import BusinessEmployee, EmployeeInvitation

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'firebase_uid', 'phone_display', 'phone_key', 'verification_status_display', 'accounts_count', 'employment_status', 'soft_delete_status', 'is_staff', 'created_at')
    list_filter = ('is_staff', 'is_superuser', 'phone_country', 'created_at', 'deleted_at')
    search_fields = ('username', 'email', 'firebase_uid', 'first_name', 'last_name')
    readonly_fields = ('firebase_uid', 'auth_token_version', 'created_at', 'updated_at')
    actions = ('soft_delete_selected',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('username', 'email', 'first_name', 'last_name', 'firebase_uid')
        }),
        ('Contact Information', {
            'fields': ('phone_country', 'phone_number', 'phone_key')
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

    def soft_delete_status(self, obj):
        if obj.deleted_at:
            return format_html('<span style="color: red;">Deleted<br><small>{}</small></span>', timezone.localtime(obj.deleted_at).strftime('%Y-%m-%d %H:%M'))
        return format_html('<span style="color: green;">Active</span>')
    soft_delete_status.short_description = "Status"
    soft_delete_status.admin_order_field = 'deleted_at'

    def get_queryset(self, request):
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Prevent irreversible hard deletes from the admin list view
        actions.pop('delete_selected', None)
        return actions

    def soft_delete_selected(self, request, queryset):
        """Soft delete the selected users instead of hard deleting"""
        deleted = 0
        for user in queryset:
            if not user.deleted_at:
                user.soft_delete()
                deleted += 1
        if deleted:
            self.message_user(request, f"Soft-deleted {deleted} user(s).", level=messages.SUCCESS)
        else:
            self.message_user(request, "No users were soft-deleted (they may already be deleted).", level=messages.INFO)
    soft_delete_selected.short_description = "Soft delete selected users"

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'user', 'account_type', 'account_index', 'algorand_address_short', 'bank_accounts_count', 'created_at')
    list_filter = ('account_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'business__name', 'algorand_address')
    readonly_fields = ('account_id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Account Information', {
            'fields': ('user', 'account_type', 'account_index', 'account_id', 'business')
        }),
        ('Blockchain', {
            'fields': ('algorand_address',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_login_at'),
            'classes': ('collapse',)
        }),
    )
    
    def algorand_address_short(self, obj):
        if obj.algorand_address:
            return f"{obj.algorand_address[:10]}...{obj.algorand_address[-6:]}"
        return "No address"
    algorand_address_short.short_description = "Sui Address"
    
    def bank_accounts_count(self, obj):
        count = obj.bank_accounts.count()
        if count > 0:
            url = reverse('admin:users_bankinfo_changelist') + f'?account__id__exact={obj.id}'
            return format_html('<a href="{}">{} payment methods</a>', url, count)
        return "0 payment methods"
    bank_accounts_count.short_description = "Payment Methods"

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_display_name', 'owner_display', 'business_verification_badge', 'accounts_count', 'employees_count', 'business_registration_number', 'created_at')
    list_filter = ('category', 'created_at', 'business_verified_filter')
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

    def business_verification_badge(self, obj):
        # Business verified if any IdentityVerification exists with business context and status verified
        try:
            from security.models import IdentityVerification
            is_verified = IdentityVerification.objects.filter(
                status='verified',
                risk_factors__account_type='business',
                risk_factors__business_id=str(obj.id)
            ).exists()
        except Exception:
            is_verified = False
        color = '#28A745' if is_verified else '#6B7280'
        label = 'Verified' if is_verified else 'Unverified'
        return format_html('<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 12px;">{}</span>', color, label)
    business_verification_badge.short_description = 'Verification'

    # Custom filter for verification status
    def business_verified_filter(self, request, queryset):
        return queryset
    business_verified_filter.title = 'Verification'
    business_verified_filter.parameter_name = 'verification'

    def get_list_filter(self, request):
        from django.contrib.admin import SimpleListFilter
        class VerifiedFilter(SimpleListFilter):
            title = 'Verification'
            parameter_name = 'verified'

            def lookups(self, request, model_admin):
                return (
                    ('yes', 'Verified'),
                    ('no', 'Unverified'),
                )

            def queryset(self, request, queryset):
                from security.models import IdentityVerification
                val = self.value()
                if val == 'yes':
                    ids = IdentityVerification.objects.filter(
                        status='verified',
                        risk_factors__account_type='business'
                    ).values_list('risk_factors__business_id', flat=True)
                    return queryset.filter(id__in=[int(i) for i in ids if i])
                if val == 'no':
                    ids = IdentityVerification.objects.filter(
                        status='verified',
                        risk_factors__account_type='business'
                    ).values_list('risk_factors__business_id', flat=True)
                    return queryset.exclude(id__in=[int(i) for i in ids if i])
                return queryset

        # Merge existing filters with our custom filter
        base_filters = list(super().get_list_filter(request))
        base_filters.append(VerifiedFilter)
        return base_filters


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



# Achievement admin classes have been moved to achievements/admin.py


class WalletPepperAdmin(admin.ModelAdmin):
    """Admin interface for WalletPepper model with account-based pepper management"""
    
    list_display = ('account_key_display', 'account_type', 'version', 'status_display', 'grace_status', 'created_at', 'rotated_at')
    list_filter = ('version', 'created_at', 'rotated_at', 'grace_period_until')
    search_fields = ('account_key',)
    # Include custom display methods in readonly_fields so they can be used in fieldsets
    readonly_fields = ('account_key', 'version', 'previous_version', 
                      'created_at', 'updated_at', 'rotated_at', 'grace_period_until',
                      'pepper_display', 'previous_pepper_display', 'user_link')
    ordering = ('-updated_at',)
    
    fieldsets = (
        ('Account Information', {
            'fields': ('account_key', 'user_link'),
            'description': 'Account-based pepper for secure wallet key derivation'
        }),
        ('Current Pepper', {
            'fields': ('pepper_display', 'version'),
            'description': 'Current active pepper for this account'
        }),
        ('Rotation Information', {
            'fields': ('previous_pepper_display', 'previous_version', 'grace_period_until', 'rotated_at'),
            'classes': ('collapse',),
            'description': 'Information about pepper rotation and grace period'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['rotate_pepper', 'extend_grace_period', 'clear_grace_period']
    
    def account_type(self, obj):
        """Display the account type (Personal/Business/Legacy)"""
        if obj.account_key and obj.account_key.startswith('user_'):
            parts = obj.account_key.split('_')
            if len(parts) >= 3:
                account_type = parts[2]
                if account_type == 'business':
                    return format_html('<span style="color: #1976d2; font-weight: bold;">👔 Business</span>')
                elif account_type == 'personal':
                    return format_html('<span style="color: #7b1fa2; font-weight: bold;">👤 Personal</span>')
        return format_html('<span style="color: #666;">📦 Legacy</span>')
    account_type.short_description = "Type"
    account_type.admin_order_field = 'account_key'
    
    def account_key_display(self, obj):
        """Display account key with type information"""
        if obj.account_key:
            # Parse the account key to extract meaningful info
            if obj.account_key.startswith('user_'):
                parts = obj.account_key.split('_')
                if len(parts) >= 3:
                    user_id = parts[1]
                    account_type = parts[2]
                    
                    # Handle business accounts
                    if account_type == 'business' and len(parts) >= 4:
                        business_id = parts[3]
                        account_index = parts[4] if len(parts) > 4 else '0'
                        return format_html(
                            '<span style="font-family: monospace; background: #e3f2fd; padding: 2px 4px; border-radius: 3px;">'
                            '👔 Business #{} (User #{}, Index {})</span>',
                            business_id, user_id, account_index
                        )
                    # Handle personal accounts
                    else:
                        account_index = parts[3] if len(parts) > 3 else '0'
                        return format_html(
                            '<span style="font-family: monospace; background: #f3e5f5; padding: 2px 4px; border-radius: 3px;">'
                            '👤 Personal (User #{}, Index {})</span>',
                            user_id, account_index
                        )
            
            # Fallback for old Firebase UIDs or unknown formats
            if len(obj.account_key) > 20:
                return format_html(
                    '<span style="font-family: monospace; color: #666;">📦 Legacy: {}...{}</span>',
                    obj.account_key[:6], obj.account_key[-4:]
                )
            return obj.account_key
        return "-"
    account_key_display.short_description = "Account"
    
    def pepper_display(self, obj):
        """Display pepper status without revealing the actual value"""
        if obj.pepper:
            return format_html(
                '<span style="font-family: monospace; background: #f0f0f0; padding: 2px 4px; border-radius: 3px;">'
                '●●●●●●●● (Hidden for security)</span>'
            )
        return "-"
    pepper_display.short_description = "Pepper"
    
    def previous_pepper_display(self, obj):
        """Display previous pepper status without revealing the actual value"""
        if obj.previous_pepper:
            return format_html(
                '<span style="font-family: monospace; background: #fff3cd; padding: 2px 4px; border-radius: 3px;">'
                '●●●●●●●● (Hidden for security)</span>'
            )
        return "-"
    previous_pepper_display.short_description = "Previous Pepper"
    
    def status_display(self, obj):
        """Display pepper status with visual indicators"""
        if obj.rotated_at:
            time_since = timezone.now() - obj.rotated_at
            if time_since.days == 0:
                color = '#28a745'  # Green for recently rotated
                status = 'Recently Rotated'
            elif time_since.days < 30:
                color = '#17a2b8'  # Blue for rotated this month
                status = f'Rotated {time_since.days}d ago'
            else:
                color = '#6c757d'  # Gray for older
                status = f'Rotated {time_since.days}d ago'
        else:
            color = '#6c757d'
            status = 'Never Rotated'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">⚡ {}</span>',
            color, status
        )
    status_display.short_description = "Status"
    
    def grace_status(self, obj):
        """Display grace period status"""
        if obj.is_in_grace_period():
            remaining = obj.grace_period_until - timezone.now()
            days = remaining.days
            hours = remaining.seconds // 3600
            
            if days > 3:
                color = '#28a745'  # Green
            elif days > 1:
                color = '#ffc107'  # Yellow
            else:
                color = '#dc3545'  # Red
            
            return format_html(
                '<span style="color: {};">⏰ {}d {}h remaining</span>',
                color, days, hours
            )
        elif obj.grace_period_until and obj.grace_period_until < timezone.now():
            return format_html('<span style="color: #6c757d;">✓ Expired</span>')
        return format_html('<span style="color: #6c757d;">-</span>')
    grace_status.short_description = "Grace Period"
    
    def user_link(self, obj):
        """Link to the associated user and account"""
        try:
            # Extract user ID from account_key (format: user_{id}_{type}_{index})
            if obj.account_key and obj.account_key.startswith('user_'):
                parts = obj.account_key.split('_')
                if len(parts) >= 2:
                    user_id = parts[1]
                    user = User.objects.get(id=user_id)
                    
                    # Build the display with account context
                    links = []
                    
                    # User link
                    user_url = reverse('admin:users_user_change', args=[user.id])
                    links.append(format_html('<a href="{}">👤 {}</a>', user_url, user.email or user.username))
                    
                    # Account type and business link if applicable
                    if len(parts) >= 3:
                        account_type = parts[2]
                        if account_type == 'business' and len(parts) >= 4:
                            business_id = parts[3]
                            try:
                                business = Business.objects.get(id=business_id)
                                business_url = reverse('admin:users_business_change', args=[business.id])
                                links.append(format_html('<a href="{}">🏢 {}</a>', business_url, business.name))
                            except Business.DoesNotExist:
                                links.append(format_html('<span style="color: #666;">🏢 Business #{}</span>', business_id))
                    
                    return format_html(' | '.join(links))
            else:
                # Legacy Firebase UID - try to find user
                user = User.objects.get(firebase_uid=obj.account_key)
                url = reverse('admin:users_user_change', args=[user.id])
                return format_html('<a href="{}">📦 Legacy User: {}</a>', url, user.email or user.username)
        except User.DoesNotExist:
            return format_html('<span style="color: #dc3545;">User not found</span>')
    user_link.short_description = "Associated User & Account"
    
    @admin.action(description='Rotate selected peppers')
    def rotate_pepper(self, request, queryset):
        """Admin action to rotate peppers"""
        rotated_count = 0
        
        with transaction.atomic():
            for pepper_obj in queryset.select_for_update():
                old_version = pepper_obj.version
                old_pepper = pepper_obj.pepper
                
                # Rotate pepper
                pepper_obj.previous_pepper = old_pepper
                pepper_obj.previous_version = old_version
                pepper_obj.grace_period_until = timezone.now() + timezone.timedelta(days=7)
                pepper_obj.version += 1
                pepper_obj.pepper = secrets.token_hex(32)
                pepper_obj.rotated_at = timezone.now()
                pepper_obj.save()
                
                rotated_count += 1
        
        self.message_user(
            request,
            f"Successfully rotated {rotated_count} pepper(s). Grace period set to 7 days.",
            messages.SUCCESS
        )
    
    @admin.action(description='Extend grace period by 7 days')
    def extend_grace_period(self, request, queryset):
        """Extend grace period for selected peppers"""
        extended_count = 0
        
        for pepper_obj in queryset:
            if pepper_obj.previous_pepper:
                if pepper_obj.grace_period_until:
                    pepper_obj.grace_period_until += timezone.timedelta(days=7)
                else:
                    pepper_obj.grace_period_until = timezone.now() + timezone.timedelta(days=7)
                pepper_obj.save()
                extended_count += 1
        
        self.message_user(
            request,
            f"Extended grace period for {extended_count} pepper(s).",
            messages.SUCCESS
        )
    
    @admin.action(description='Clear grace period (end immediately)')
    def clear_grace_period(self, request, queryset):
        """Clear grace period for selected peppers"""
        cleared_count = 0
        
        for pepper_obj in queryset:
            if pepper_obj.grace_period_until:
                pepper_obj.grace_period_until = None
                pepper_obj.previous_pepper = None
                pepper_obj.previous_version = None
                pepper_obj.save()
                cleared_count += 1
        
        self.message_user(
            request,
            f"Cleared grace period for {cleared_count} pepper(s).",
            messages.WARNING
        )
    
    def has_add_permission(self, request):
        """Prevent manual creation of peppers (should be created via API)"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of peppers (for audit trail)"""
        return request.user.is_superuser
    
    def get_readonly_fields(self, request, obj=None):
        """Make all fields readonly to prevent accidental modification"""
        if not request.user.is_superuser:
            return list(set([field.name for field in self.model._meta.fields]))
        return self.readonly_fields


@admin.register(WalletDerivationPepper)
class WalletDerivationPepperAdmin(admin.ModelAdmin):
    """
    Admin for non-rotating derivation pepper (fixed pepper used for address derivation).
    Mirrors WalletPepperAdmin presentation but without rotation/grace controls.
    """

    list_display = ('account_key_display', 'account_type', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('account_key',)
    readonly_fields = ('account_key', 'pepper_display', 'created_at', 'updated_at', 'user_link')
    ordering = ('-updated_at',)

    fieldsets = (
        ('Account Information', {
            'fields': ('account_key', 'user_link'),
            'description': 'Fixed derivation pepper per account (non-rotating)'
        }),
        ('Derivation Pepper', {
            'fields': ('pepper_display',),
            'description': 'Hidden for security; changing this would change addresses'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # Reuse helpers from WalletPepperAdmin for consistent UI
    def account_type(self, obj):
        if obj.account_key and obj.account_key.startswith('user_'):
            parts = obj.account_key.split('_')
            if len(parts) >= 3:
                account_type = parts[2]
                if account_type == 'business':
                    return format_html('<span style="color: #1976d2; font-weight: bold;">👔 Business</span>')
                elif account_type == 'personal':
                    return format_html('<span style="color: #7b1fa2; font-weight: bold;">👤 Personal</span>')
        return format_html('<span style="color: #666;">📦 Legacy</span>')
    account_type.short_description = "Type"
    account_type.admin_order_field = 'account_key'

    def account_key_display(self, obj):
        if obj.account_key:
            if obj.account_key.startswith('user_'):
                parts = obj.account_key.split('_')
                if len(parts) >= 3:
                    user_id = parts[1]
                    account_type = parts[2]
                    if account_type == 'business' and len(parts) >= 4:
                        business_id = parts[3]
                        account_index = parts[4] if len(parts) > 4 else '0'
                        return format_html(
                            '<span style="font-family: monospace; background: #e3f2fd; padding: 2px 4px; border-radius: 3px;">'
                            '👔 Business #{} (User #{}, Index {})</span>',
                            business_id, user_id, account_index
                        )
                    else:
                        account_index = parts[3] if len(parts) > 3 else '0'
                        return format_html(
                            '<span style="font-family: monospace; background: #f3e5f5; padding: 2px 4px; border-radius: 3px;">'
                            '👤 Personal (User #{}, Index {})</span>',
                            user_id, account_index
                        )
            if len(obj.account_key) > 20:
                return format_html(
                    '<span style="font-family: monospace; color: #666;">📦 Legacy: {}...{}</span>',
                    obj.account_key[:6], obj.account_key[-4:]
                )
            return obj.account_key
        return '-'
    account_key_display.short_description = "Account"

    def pepper_display(self, obj):
        if obj.pepper:
            return format_html(
                '<span style="font-family: monospace; background: #f0f0f0; padding: 2px 4px; border-radius: 3px;">'
                '●●●●●●●● (Hidden for security)</span>'
            )
        return '-'
    pepper_display.short_description = "Pepper"

    def user_link(self, obj):
        try:
            if obj.account_key and obj.account_key.startswith('user_'):
                parts = obj.account_key.split('_')
                if len(parts) >= 2:
                    user_id = parts[1]
                    user = User.objects.get(id=user_id)
                    links = []
                    user_url = reverse('admin:users_user_change', args=[user.id])
                    links.append(format_html('<a href="{}">👤 {}</a>', user_url, user.email or user.username))
                    if len(parts) >= 3:
                        account_type = parts[2]
                        if account_type == 'business' and len(parts) >= 4:
                            business_id = parts[3]
                            try:
                                business = Business.objects.get(id=business_id)
                                business_url = reverse('admin:users_business_change', args=[business.id])
                                links.append(format_html('<a href="{}">🏢 {}</a>', business_url, business.name))
                            except Business.DoesNotExist:
                                links.append(format_html('<span style="color: #666;">🏢 Business #{}</span>', business_id))
                    return format_html(' | '.join(links))
            else:
                user = User.objects.get(firebase_uid=obj.account_key)
                url = reverse('admin:users_user_change', args=[user.id])
                return format_html('<a href="{}">📦 Legacy User: {}</a>', url, user.email or user.username)
        except User.DoesNotExist:
            return format_html('<span style="color: #dc3545;">User not found</span>')
    user_link.short_description = "Associated User & Account"


# Ensure WalletPepper Admin is registered
admin.site.register(WalletPepper, WalletPepperAdmin)
