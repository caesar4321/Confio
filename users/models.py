from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.conf import settings
from .country_codes import COUNTRY_CODES
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
import logging
import uuid
from .phone_utils import normalize_phone

logger = logging.getLogger(__name__)

# Business category mapping utility
def get_business_category_display(category_id):
    """Get the display name for a business category ID"""
    BUSINESS_CATEGORIES = {
        'food': 'Comida y Bebidas',
        'retail': 'Comercio y Ventas',
        'services': 'Servicios Profesionales',
        'health': 'Belleza y Salud',
        'transport': 'Transporte y Delivery',
        'other': 'Otros Negocios',
    }
    return BUSINESS_CATEGORIES.get(category_id, category_id)

class SoftDeleteManager(models.Manager):
    """Manager that filters out soft-deleted objects by default"""
    
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)
    
    def with_deleted(self):
        """Return queryset including soft-deleted objects"""
        return super().get_queryset()
    
    def only_deleted(self):
        """Return queryset with only soft-deleted objects"""
        return super().get_queryset().filter(deleted_at__isnull=False)

class SoftDeleteModel(models.Model):
    """Base model with soft delete functionality"""
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="Soft delete timestamp")
    
    objects = SoftDeleteManager()
    all_objects = models.Manager()  # Access to all objects including deleted
    
    class Meta:
        abstract = True
    
    def soft_delete(self):
        """Soft delete the object"""
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])
    
    def restore(self):
        """Restore a soft-deleted object"""
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])
    
    def hard_delete(self):
        """Permanently delete the object"""
        super().delete()
    
    @property
    def is_deleted(self):
        """Check if object is soft-deleted"""
        return self.deleted_at is not None

class User(AbstractUser, SoftDeleteModel):
    firebase_uid = models.CharField(max_length=128, unique=True)
    # Unified activity timestamp for MAU/WAU/DAU (updated on any user activity)
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    phone_country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        choices=[(code[2], f"{code[0]} ({code[1]})") for code in COUNTRY_CODES],
        help_text="User's country ISO code for phone number"
    )
    phone_number = models.CharField(max_length=15, blank=True, null=True, help_text="User's phone number without country code")
    # Canonical normalized phone key: "callingcode:digits" (e.g., "1:9293993619")
    phone_key = models.CharField(max_length=32, blank=True, null=True, help_text="Canonical phone key for uniqueness across ISO variations")
    
    # Backup Tracking Fields (Added for KPI & Safety Monitoring)
    backup_provider = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        choices=[('google_drive', 'Google Drive'), ('icloud', 'iCloud')],
        help_text="Provider where the wallet backup was last verified"
    )
    backup_verified_at = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Timestamp of the last successful backup verification (Response 200 OK)"
    )
    backup_device_name = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Name of the device that performed the backup (e.g. iPhone 15)"
    )
    
    # OS Tracking for Dashboard Stats
    platform_os = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=[('ios', 'iOS'), ('android', 'Android'), ('web', 'Web')],
        help_text="Operating System of the user's primary device"
    )

    auth_token_version = models.IntegerField(default=1, help_text="Version number for JWT tokens. Incrementing this invalidates all existing tokens.")
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='custom_user_set',
        related_query_name='custom_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='custom_user_set',
        related_query_name='custom_user',
    )
    
    def __str__(self):
        return self.username or self.email or self.firebase_uid

    def save(self, *args, **kwargs):
        # Auto-maintain canonical phone key for uniqueness
        try:
            if self.phone_number:
                # Accept either ISO or calling code; we have ISO here
                # If admin passes a calling code into phone_country by mistake, still tolerant
                self.phone_key = normalize_phone(self.phone_number or '', self.phone_country or '')
            else:
                self.phone_key = None
        except Exception:
            pass
        super().save(*args, **kwargs)

    @property
    def phone_country_code(self):
        """Get the country code for the user's phone country"""
        if not self.phone_country:
            return None
        for country in COUNTRY_CODES:
            if country[2] == self.phone_country:
                return country[1]
        return None

    @property
    def phone_country_name(self):
        """Get the country name for the user's phone country"""
        if not self.phone_country:
            return None
        for country in COUNTRY_CODES:
            if country[2] == self.phone_country:
                return country[0]
        return None

    def increment_auth_token_version(self):
        """Increment the auth token version to invalidate all existing tokens"""
        self.auth_token_version += 1
        self.save(update_fields=['auth_token_version'])



    @property
    def verification_status(self):
        """Get the current verification status based on verification records
        Priority: verified > pending > rejected > unverified
        This avoids stale ordering issues when verified_at is null or when a
        later rejected record exists after a previously verified one.
        """
        from security.models import IdentityVerification
        # PERSONAL CONTEXT ONLY: exclude business-context verifications
        # Business verifications should not mark personal user as verified
        personal_verified = IdentityVerification.objects.filter(
            user=self,
            status='verified'
        ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        if personal_verified.exists():
            return 'verified'
        # Otherwise reflect active pending (personal) submissions if any
        personal_pending = IdentityVerification.objects.filter(
            user=self,
            status='pending'
        ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        if personal_pending.exists():
            return 'pending'
        # Otherwise if only rejected (personal) submissions exist
        personal_rejected = IdentityVerification.objects.filter(
            user=self,
            status='rejected'
        ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        if personal_rejected.exists():
            return 'rejected'
        return 'unverified'

    @property
    def is_identity_verified(self):
        """Check if user has any verified identity records (personal context only)
        Excludes business-context verifications so personal accounts are not
        marked verified when only a business account has been verified.
        """
        from security.models import IdentityVerification
        return IdentityVerification.objects.filter(
            user=self,
            status='verified'
        ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')).exists()

    @property
    def last_verified_date(self):
        """Get the date of the latest successful verification"""
        from security.models import IdentityVerification
        latest_verified = (
            IdentityVerification.objects
            .filter(user=self, status='verified')
            .exclude(risk_factors__account_type='business')
            .order_by('-verified_at', '-updated_at', '-created_at')
            .first()
        )
        if not latest_verified:
            return None
        # Prefer explicit verified_at when available; otherwise fall back to updated_at/created_at
        return (
            latest_verified.verified_at
            or latest_verified.updated_at
            or latest_verified.created_at
        )



    @property
    def latest_verification(self):
        """Get the most recently updated verification record for this user"""
        # PERSONAL CONTEXT ONLY by default to reflect user's own status
        from security.models import IdentityVerification
        return (
            IdentityVerification.objects
            .filter(user=self)
            .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
            .order_by('-updated_at', '-created_at')
            .first()
        )


    
    @property
    def is_phone_verified(self):
        """Check if user has a phone number stored"""
        return bool(self.phone_number)



class Business(SoftDeleteModel):
    """Business information for business accounts"""
    
    BUSINESS_CATEGORY_CHOICES = [
        ('food', 'Comida y Bebidas'),
        ('retail', 'Comercio y Ventas'),
        ('services', 'Servicios Profesionales'),
        ('health', 'Belleza y Salud'),
        ('transport', 'Transporte y Delivery'),
        ('other', 'Otros Negocios'),
    ]
    
    # Business information
    name = models.CharField(
        max_length=255,
        help_text="Business name"
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Business description"
    )
    category = models.CharField(
        max_length=20,
        choices=BUSINESS_CATEGORY_CHOICES,
        help_text="Business category"
    )
    business_registration_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Business registration number or tax ID"
    )
    address = models.TextField(
        blank=True,
        null=True,
        help_text="Business address"
    )

    class Meta:
        verbose_name_plural = "Businesses"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    @property
    def category_display_name(self):
        """Get the display name for the category"""
        return self.get_category_display()

    @classmethod
    def get_category_choices(cls):
        """Get the category choices as a list of tuples"""
        return cls.BUSINESS_CATEGORY_CHOICES

    @classmethod
    def get_category_by_id(cls, category_id):
        """Get category display name by ID"""
        for choice_id, display_name in cls.BUSINESS_CATEGORY_CHOICES:
            if choice_id == category_id:
                return display_name
        return None

class Account(SoftDeleteModel):
    ACCOUNT_TYPE_CHOICES = [
        ('personal', 'Personal'),
        ('business', 'Business'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="accounts",
    )

    # —————————————————————————————
    # multi-account system fields
    # —————————————————————————————
    account_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='personal',
        help_text="Type of account (personal or business)"
    )
    account_index = models.PositiveIntegerField(
        default=0,
        help_text="Index of the account within its type (0, 1, 2, etc.)"
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts",
        help_text="Associated business for business accounts"
    )

    # —————————————————————————————
    # persistent per‑user state
    # —————————————————————————————
    algorand_address = models.CharField(
        max_length=58,  # Algorand addresses are 58 characters
        blank=True, null=True,
        help_text="Algorand address for this account"
    )

    # —————————————————————————————
    # audit‑style timestamps
    # —————————————————————————————
    last_login_at = models.DateTimeField(null=True, blank=True)
    is_keyless_migrated = models.BooleanField(
        default=False,
        help_text="Whether this account has migrated to V2 keyless wallet (server-side tracking)"
    )

    class Meta:
        unique_together = ['user', 'account_type', 'account_index']
        ordering = ['user', 'account_type', 'account_index']
        
    def get_ordering_key(self):
        """Get a key for custom ordering: personal accounts first, then business accounts by index"""
        # Personal accounts get priority (0), business accounts get lower priority (1)
        type_priority = 0 if self.account_type == 'personal' else 1
        return (type_priority, self.account_index)

    def __str__(self):
        return f"{self.user.username} {self.account_type.capitalize()} Account {self.account_index}"

    @property
    def account_id(self):
        """Generate the account ID in the format used by the mobile app"""
        return f"{self.account_type}_{self.account_index}"

    @property
    def display_name(self):
        """Get the display name for this account"""
        if self.account_type == 'personal':
            # Always return a non-empty display name for personal accounts
            name = f"{self.user.first_name} {self.user.last_name}".strip()
            base_name = name if name else self.user.username or f"Personal {self.account_index}"
            return f"Personal - {base_name}"
        else:
            # For business accounts, get the business name
            business_name = self.business.name if self.business else f"Negocio {self.account_index}"
            return f"Negocio - {business_name}"

    @property
    def avatar_letter(self):
        """Get the avatar letter for this account"""
        if self.account_type == 'personal':
            # For personal accounts, use the first letter of the user's name
            name = f"{self.user.first_name} {self.user.last_name}".strip()
            if name:
                return name[0].upper()
            elif self.user.username:
                return self.user.username[0].upper()
            else:
                return 'U'
        else:
            # For business accounts, use the first letter of the business name
            if self.business and self.business.name:
                return self.business.name[0].upper()
            else:
                return 'N'  # Default for business accounts

    def get_business_info(self):
        """Get business information for this account if it's a business account"""
        if self.account_type == 'business':
            return self.business
        return None

# --- Signals to sync display name ---
@receiver(post_save, sender=User)
def sync_personal_account_display_name(sender, instance, **kwargs):
    # Update the display name for the user's personal account(s) when the user profile is updated
    personal_accounts = instance.accounts.filter(account_type='personal')
    for account in personal_accounts:
        # This will ensure display_name property always reflects the latest user info
        account.save(update_fields=["last_login_at"])  # Touch the account to trigger any listeners

@receiver(post_save, sender=Business)
def sync_business_account_display_name(sender, instance, **kwargs):
    # Update the display name for all accounts linked to this business when the business is updated
    for account in instance.accounts.all():
        account.save(update_fields=["last_login_at"])  # Touch the account to trigger any listeners


class Country(SoftDeleteModel):
    """Country configuration for bank requirements and payment methods"""
    
    code = models.CharField(
        max_length=3,
        unique=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g., VE, CO, AR)"
    )
    name = models.CharField(
        max_length=100,
        help_text="Country name"
    )
    flag_emoji = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Country flag emoji (e.g., 🇻🇪)"
    )
    currency_code = models.CharField(
        max_length=3,
        help_text="Currency code (e.g., VES, COP, ARS)"
    )
    currency_symbol = models.CharField(
        max_length=10,
        help_text="Currency symbol (e.g., Bs., $)"
    )
    
    # ID/Cedula requirements
    requires_identification = models.BooleanField(
        default=True,
        help_text="Whether bank transfers require recipient ID number"
    )
    identification_name = models.CharField(
        max_length=50,
        default="Cédula",
        help_text="Local name for ID document (e.g., Cédula, DNI, RUT)"
    )
    identification_format = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Expected format for ID (e.g., 'V-12345678', '12345678-9')"
    )
    
    # Banking details
    account_number_length = models.PositiveIntegerField(
        default=20,
        help_text="Typical account number length"
    )
    supports_phone_payments = models.BooleanField(
        default=False,
        help_text="Whether country supports phone-based payments"
    )
    
    # Operational settings
    is_active = models.BooleanField(
        default=True,
        help_text="Whether Confío operates in this country"
    )
    display_order = models.PositiveIntegerField(
        default=1000,
        help_text="Display order in lists (lower numbers first)"
    )
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = "Countries"
    
    def __str__(self):
        flag = f"{self.flag_emoji} " if self.flag_emoji else ""
        return f"{flag}{self.name} ({self.code})"


class Bank(SoftDeleteModel):
    """Bank information for different countries"""
    
    country = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name='banks',
        help_text="Country where this bank operates"
    )
    code = models.CharField(
        max_length=50,
        help_text="Bank code/identifier"
    )
    name = models.CharField(
        max_length=100,
        help_text="Bank name"
    )
    short_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Short/common name for the bank"
    )
    
    # Account type support
    supports_checking = models.BooleanField(
        default=True,
        help_text="Whether bank supports checking accounts"
    )
    supports_savings = models.BooleanField(
        default=True,
        help_text="Whether bank supports savings accounts"
    )
    supports_payroll = models.BooleanField(
        default=False,
        help_text="Whether bank supports payroll accounts"
    )
    
    # Operational settings
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this bank is currently supported"
    )
    display_order = models.PositiveIntegerField(
        default=1000,
        help_text="Display order in lists (lower numbers first)"
    )
    
    class Meta:
        ordering = ['country__display_order', 'display_order', 'name']
        unique_together = ['country', 'code']
    
    def __str__(self):
        return f"{self.name} ({self.country.code})"
    
    def get_account_type_choices(self):
        """Get available account types for this bank"""
        choices = []
        if self.supports_savings:
            choices.append(('ahorro', 'Cuenta de Ahorros'))
        if self.supports_checking:
            choices.append(('corriente', 'Cuenta Corriente'))
        if self.supports_payroll:
            choices.append(('nomina', 'Cuenta Nómina'))
        return choices


class BankInfo(SoftDeleteModel):
    """Payment method information for users to share payment details - supports banks and fintech"""
    
    ACCOUNT_TYPE_CHOICES = [
        ('ahorro', 'Cuenta de Ahorros'),
        ('corriente', 'Cuenta Corriente'),
        ('nomina', 'Cuenta Nómina'),
    ]
    
    # Link to account (supports multi-account system)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        help_text="Account that owns this payment method"
    )
    
    # Link to payment method type (single source of truth)
    payment_method = models.ForeignKey(
        'p2p_exchange.P2PPaymentMethod',
        on_delete=models.CASCADE,
        related_name='user_payment_accounts',
        null=True,
        blank=True,
        help_text="Type of payment method (bank, fintech, etc.)"
    )
    
    # DEPRECATED: Legacy bank-specific fields (kept for backward compatibility)
    country = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use payment_method.country_code instead"
    )
    bank = models.ForeignKey(
        Bank,
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        null=True,
        blank=True,
        help_text="DEPRECATED: Use payment_method.bank instead"
    )
    
    # Universal payment method details
    account_holder_name = models.CharField(
        max_length=200,
        help_text="Full name of the account/payment method holder"
    )
    
    # Flexible recipient information (depends on payment method type)
    account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Account number (for banks) or identifier (for some fintech)"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Phone number (for mobile wallets like Nequi, Yape, Pago Móvil)"
    )
    email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email address (for PayPal, Wise, etc.)"
    )
    username = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Username/handle (for some fintech platforms)"
    )
    
    # Bank-specific details (only used if payment_method is bank type)
    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Type of bank account (only for banks)"
    )
    
    # Identification details (conditional based on country requirements)
    identification_number = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="Identification number (required for some countries/banks)"
    )
    
    # Privacy and sharing settings
    is_default = models.BooleanField(
        default=False,
        help_text="Whether this is the default bank account for this account"
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this bank info can be shared with other users"
    )
    shared_with_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='shared_bank_info',
        help_text="Users who have access to this bank information"
    )
    
    # Verification status
    is_verified = models.BooleanField(
        default=False,
        help_text="Whether this bank account has been verified"
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the bank account was verified"
    )
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_bank_accounts',
        help_text="Admin user who verified this bank account"
    )

    
    class Meta:
        ordering = ['-is_default', '-created_at']
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"
        # Remove the old unique constraint since we now support multiple payment types
    
    def __str__(self):
        if self.payment_method.is_bank_based:
            # For banks, show bank name and masked account
            identifier = self.get_masked_account_number() if self.account_number else 'No Account'
            return f"{self.payment_method.display_name} - {identifier} ({self.account.display_name})"
        else:
            # For fintech, show the primary identifier
            identifier = self.get_primary_identifier()
            return f"{self.payment_method.display_name} - {identifier} ({self.account.display_name})"
    
    def clean(self):
        """Validate payment method based on requirements"""
        super().clean()
        
        # Legacy validation for bank-based payments
        if self.payment_method and self.payment_method.is_bank_based:
            # Validate that bank belongs to the selected country
            if self.bank and self.country and self.bank.country != self.country:
                raise ValidationError(
                    f"Selected bank '{self.bank.name}' does not operate in {self.country.name}"
                )
            
            # Validate identification number requirement
            if self.country and self.country.requires_identification:
                if not self.identification_number:
                    raise ValidationError(
                        f"{self.country.identification_name} is required for bank accounts in {self.country.name}"
                    )
        
        # Validate required fields based on payment method
        if self.payment_method:
            if self.payment_method.requires_phone and not self.phone_number:
                raise ValidationError(
                    f"Phone number is required for {self.payment_method.display_name}"
                )
            if self.payment_method.requires_email and not self.email:
                raise ValidationError(
                    f"Email is required for {self.payment_method.display_name}"
                )
            if self.payment_method.requires_account_number and not self.account_number:
                raise ValidationError(
                    f"Account number is required for {self.payment_method.display_name}"
                )
    
    def save(self, *args, **kwargs):
        # Auto-set country from bank if not provided
        if self.bank and not self.country:
            self.country = self.bank.country
        super().save(*args, **kwargs)
    
    def get_masked_account_number(self):
        """Get masked account number for security (show only last 4 digits)"""
        if not self.account_number or len(self.account_number) <= 4:
            return self.account_number or 'N/A'
        return '*' * (len(self.account_number) - 4) + self.account_number[-4:]
    
    def get_primary_identifier(self):
        """Get the primary identifier based on payment method requirements"""
        if not self.payment_method:
            return 'Unknown'
            
        # For banks, always use account number
        if self.payment_method.is_bank_based and self.account_number:
            return self.get_masked_account_number()
        
        # For fintech, use the appropriate identifier
        if self.payment_method.requires_phone and self.phone_number:
            return f"+{self.phone_number}"
        elif self.payment_method.requires_email and self.email:
            return self.email
        elif self.username:
            return f"@{self.username}"
        elif self.account_number:
            return self.get_masked_account_number()
        
        return 'No identifier'
    
    def get_recipient_info(self):
        """Get formatted recipient information for sharing"""
        info = {
            'payment_method': self.payment_method.display_name,
            'account_holder': self.account_holder_name,
        }
        
        if self.payment_method.requires_phone and self.phone_number:
            info['phone'] = self.phone_number
        if self.payment_method.requires_email and self.email:
            info['email'] = self.email
        if self.payment_method.requires_account_number and self.account_number:
            info['account_number'] = self.account_number
        if self.username:
            info['username'] = self.username
        if self.account_type:
            info['account_type'] = self.get_account_type_display()
        if self.identification_number:
            info['identification'] = self.identification_number
        
        return info
    
    def set_as_default(self):
        """Set this bank account as default and unset others"""
        # Remove default status from other bank accounts in the same account
        BankInfo.objects.filter(account=self.account, is_default=True).update(is_default=False)
        self.is_default = True
        self.save(update_fields=['is_default'])
    
    def share_with_user(self, user):
        """Share this bank info with a specific user"""
        self.shared_with_users.add(user)
    
    def unshare_with_user(self, user):
        """Stop sharing this bank info with a specific user"""
        self.shared_with_users.remove(user)
    
    def is_shared_with(self, user):
        """Check if this bank info is shared with a specific user"""
        return self.shared_with_users.filter(id=user.id).exists()
    
    @property
    def full_bank_name(self):
        """Get the full bank/payment method name"""
        if self.payment_method:
            return self.payment_method.display_name
        elif self.bank:
            return self.bank.name
        return "Payment Method"
    
    @property
    def summary_text(self):
        """Get a summary text for display in lists"""
        if self.payment_method:
            # Handle different payment method types
            if self.payment_method.provider_type == 'BANK' and self.account_number:
                return f"{self.payment_method.display_name} - {self.get_account_type_display()} - {self.get_masked_account_number()}"
            elif self.payment_method.requires_phone and self.phone_number:
                return f"{self.payment_method.display_name} - {self.phone_number}"
            elif self.payment_method.requires_email and self.email:
                return f"{self.payment_method.display_name} - {self.email}"
            elif self.username:
                return f"{self.payment_method.display_name} - @{self.username}"
            else:
                return f"{self.payment_method.display_name} - {self.account_holder_name}"
        elif self.bank:
            # Legacy support
            return f"{self.bank.name} - {self.get_account_type_display()} - {self.get_masked_account_number()}"
        return "Payment Method"
    
    @property
    def requires_identification(self):
        """Check if this payment method requires identification"""
        if self.payment_method and self.payment_method.bank:
            return self.payment_method.bank.country.requires_identification
        elif self.country:
            return self.country.requires_identification
        return False
    
    @property
    def identification_label(self):
        """Get the label for identification field"""
        if self.payment_method and self.payment_method.bank:
            return self.payment_method.bank.country.identification_name
        elif self.country:
            return self.country.identification_name
        return "ID"
    
    def get_payment_details(self):
        """Get formatted payment details for sharing"""
        details = {
            'account_holder_name': self.account_holder_name,
        }
        
        # Handle payment method details
        if self.payment_method:
            details['payment_method'] = self.payment_method.display_name
            details['provider_type'] = self.payment_method.provider_type
            
            # Add relevant fields based on payment method type
            if self.payment_method.provider_type == 'BANK':
                if self.payment_method.bank:
                    details['bank_name'] = self.payment_method.bank.name
                    details['country'] = self.payment_method.bank.country.name
                if self.account_number:
                    details['account_number'] = self.account_number
                if self.account_type:
                    details['account_type'] = self.get_account_type_display()
            
            if self.payment_method.requires_phone and self.phone_number:
                details['phone_number'] = self.phone_number
                
            if self.payment_method.requires_email and self.email:
                details['email'] = self.email
                
            if self.username:
                details['username'] = self.username
                
        # Legacy support for old bank-only system
        elif self.bank:
            details['bank_name'] = self.bank.name
            details['account_number'] = self.account_number
            details['account_type'] = self.get_account_type_display()
            if self.country:
                details['country'] = self.country.name
        
        # Add identification if required
        if self.requires_identification and self.identification_number:
            details['identification'] = {
                'label': self.identification_label,
                'number': self.identification_number
            }
        
        # Add phone if available
        if self.phone_number:
            details['phone_number'] = self.phone_number
            
        return details


# Signal to ensure only one default bank account per account
@receiver(post_save, sender=BankInfo)
def ensure_single_default_bank_account(sender, instance, **kwargs):
    """Ensure only one bank account is marked as default per account"""
    if instance.is_default:
        # Remove default status from other bank accounts in the same account
        BankInfo.objects.filter(
            account=instance.account,
            is_default=True
        ).exclude(id=instance.id).update(is_default=False)


# Achievement System Models have been moved to achievements/models.py

# Import wallet models
from .models_wallet import WalletPepper, WalletDerivationPepper

# Import analytics models to register them with Django
from .models_analytics import DailyMetrics, CountryMetrics  # noqa: F401
