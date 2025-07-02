from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from .country_codes import COUNTRY_CODES
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.exceptions import ValidationError
import logging
import uuid

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
    phone_country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        choices=[(code[2], f"{code[0]} ({code[1]})") for code in COUNTRY_CODES],
        help_text="User's country ISO code for phone number"
    )
    phone_number = models.CharField(max_length=15, blank=True, null=True, help_text="User's phone number without country code")
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
        """Get the current verification status based on verification records"""
        latest_verification = self.latest_verification
        if latest_verification and latest_verification.status == 'verified':
            return 'verified'
        elif latest_verification and latest_verification.status == 'rejected':
            return 'rejected'
        elif latest_verification and latest_verification.status == 'pending':
            return 'pending'
        return 'unverified'

    @property
    def is_identity_verified(self):
        """Check if user has any verified identity records"""
        return self.verifications.filter(status='verified').exists()

    @property
    def last_verified_date(self):
        """Get the date of the latest verification"""
        latest_verification = self.latest_verification
        if latest_verification and latest_verification.status == 'verified':
            return latest_verification.verified_at
        return None



    @property
    def latest_verification(self):
        """Get the latest verification record for this user"""
        return self.verifications.order_by('-verified_at').first()

    @property
    def is_verified(self):
        """Check if user has any verified identity records"""
        return self.verifications.filter(status='verified').exists()


class IdentityVerification(SoftDeleteModel):
    """Model for storing KYC/AML verification documents and information"""
    
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('verified', 'Verificado'),
        ('rejected', 'Rechazado'),
        ('expired', 'Expirado'),
    ]
    
    DOCUMENT_TYPE_CHOICES = [
        ('national_id', 'Cédula de Identidad'),
        ('passport', 'Pasaporte'),
        ('drivers_license', 'Licencia de Conducir'),
        ('foreign_id', 'Documento de Identidad Extranjero'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='verifications',
        help_text="User being verified"
    )
    
    # Personal Information
    verified_first_name = models.CharField(
        max_length=100,
        help_text="First name as verified from documents"
    )
    verified_last_name = models.CharField(
        max_length=100,
        help_text="Last name as verified from documents"
    )
    verified_date_of_birth = models.DateField(
        help_text="Date of birth as verified from documents"
    )
    verified_nationality = models.CharField(
        max_length=3,
        help_text="Nationality ISO code (e.g., VEN, ARG, COL)"
    )
    
    # Address Information
    verified_address = models.TextField(
        help_text="Full address as verified from documents"
    )
    verified_city = models.CharField(
        max_length=100,
        help_text="City as verified from documents"
    )
    verified_state = models.CharField(
        max_length=100,
        help_text="State/Province as verified from documents"
    )
    verified_country = models.CharField(
        max_length=3,
        help_text="Country ISO code as verified from documents"
    )
    verified_postal_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Postal code as verified from documents"
    )
    
    # Document Information
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        help_text="Type of identification document"
    )
    document_number = models.CharField(
        max_length=50,
        help_text="Document number/ID"
    )
    document_issuing_country = models.CharField(
        max_length=3,
        help_text="Country that issued the document"
    )
    document_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Document expiry date if applicable"
    )
    
    # Document Files
    document_front_image = models.FileField(
        upload_to='verification_documents/',
        help_text="Front side of identification document"
    )
    document_back_image = models.FileField(
        upload_to='verification_documents/',
        null=True,
        blank=True,
        help_text="Back side of identification document"
    )
    selfie_with_document = models.FileField(
        upload_to='verification_documents/',
        help_text="Selfie holding the identification document"
    )
    
    # Verification Details
    status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending',
        help_text="Current verification status"
    )
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verifications_approved',
        help_text="Admin user who approved the verification"
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date and time when verification was approved"
    )
    rejected_reason = models.TextField(
        blank=True,
        null=True,
        help_text="Reason for rejection if verification was rejected"
    )
    

    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Identity Verification"
        verbose_name_plural = "Identity Verifications"
    
    def __str__(self):
        return f"Verification for {self.user.username} - {self.get_status_display()}"
    
    def approve_verification(self, approved_by):
        """Approve the verification and sync verified name with user profile"""
        self.status = 'verified'
        self.verified_by = approved_by
        self.verified_at = timezone.now()
        self.save()
        
        # Sync verified name with user profile
        self.user.first_name = self.verified_first_name
        self.user.last_name = self.verified_last_name
        self.user.save(update_fields=['first_name', 'last_name'])
    
    def reject_verification(self, rejected_by, reason):
        """Reject the verification"""
        self.status = 'rejected'
        self.verified_by = rejected_by
        self.verified_at = timezone.now()
        self.rejected_reason = reason
        self.save()
    
    def is_expired(self):
        """Check if the verification has expired (e.g., document expired)"""
        if self.document_expiry_date and self.document_expiry_date < timezone.now().date():
            return True
        return False
    
    @property
    def full_name(self):
        """Get the full verified name"""
        return f"{self.verified_first_name} {self.verified_last_name}"
    
    @property
    def full_address(self):
        """Get the full verified address"""
        address_parts = [
            self.verified_address,
            self.verified_city,
            self.verified_state,
            self.verified_postal_code,
            self.verified_country
        ]
        return ", ".join(filter(None, address_parts))

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
    sui_address = models.CharField(
        max_length=66,
        blank=True, null=True,
        help_text="Last‑computed Sui address for this account"
    )

    # —————————————————————————————
    # audit‑style timestamps
    # —————————————————————————————
    last_login_at = models.DateTimeField(null=True, blank=True)

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