import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


def generate_public_id():
    return uuid.uuid4().hex


class HumanitarianCampaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('closed', 'Closed'),
    ]

    public_id = models.CharField(max_length=32, unique=True, default=generate_public_id, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=160)
    country_code = models.CharField(max_length=3, default='VEN')
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    goal_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_donated = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_released = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    donation_count = models.PositiveIntegerField(default=0)
    release_count = models.PositiveIntegerField(default=0)
    algorand_app_id = models.PositiveBigIntegerField(null=True, blank=True)
    vault_address = models.CharField(max_length=66, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def get_active_venezuela(cls):
        return cls.objects.filter(slug='venezuela-2026-earthquake', status__iexact='active').first()


class HumanitarianVolunteerApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]

    public_id = models.CharField(max_length=32, unique=True, default=generate_public_id, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='humanitarian_applications')
    campaign = models.ForeignKey(HumanitarianCampaign, on_delete=models.PROTECT, related_name='volunteer_applications')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    service_area = models.CharField(max_length=160, blank=True)
    local_phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_humanitarian_applications',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'campaign')]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user} - {self.campaign} ({self.status})'

    @property
    def has_verified_venezuelan_kyc(self):
        return self.user.security_verifications.filter(
            Q(verified_country__iexact='VEN')
            | Q(verified_nationality__iexact='VEN')
            | Q(document_issuing_country__iexact='VEN'),
            status='verified',
            deleted_at__isnull=True,
        ).exists()

    def approve(self, admin_user):
        self.status = 'approved'
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])


class HumanitarianDonation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('failed', 'Failed'),
    ]

    public_id = models.CharField(max_length=32, unique=True, default=generate_public_id, editable=False)
    campaign = models.ForeignKey(HumanitarianCampaign, on_delete=models.PROTECT, related_name='donations')
    donor_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    donor_display_name = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    from_address = models.CharField(max_length=66, blank=True, default='')
    transaction_hash = models.CharField(max_length=128, blank=True, default='', db_index=True)
    donated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-donated_at']
        indexes = [
            models.Index(fields=['campaign', 'status', '-donated_at']),
            models.Index(fields=['transaction_hash']),
        ]

    def __str__(self):
        return f'{self.amount} cUSD - {self.campaign}'


class HumanitarianRelease(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('confirmed', 'Confirmed'),
        ('failed', 'Failed'),
        ('proof_pending', 'Proof pending'),
        ('proof_published', 'Proof published'),
        ('cancelled', 'Cancelled'),
    ]

    public_id = models.CharField(max_length=32, unique=True, default=generate_public_id, editable=False)
    campaign = models.ForeignKey(HumanitarianCampaign, on_delete=models.PROTECT, related_name='releases')
    volunteer_application = models.ForeignKey(
        HumanitarianVolunteerApplication,
        on_delete=models.PROTECT,
        related_name='releases',
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    purpose = models.CharField(max_length=240)
    recipient_address = models.CharField(max_length=66)
    transaction_hash = models.CharField(max_length=128, blank=True, default='', db_index=True)
    admin_note = models.TextField(blank=True)
    public_note = models.TextField(blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='humanitarian_releases_sent',
    )
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status', '-created_at']),
            models.Index(fields=['recipient_address']),
            models.Index(fields=['transaction_hash']),
        ]

    def __str__(self):
        return f'{self.amount} cUSD to {self.volunteer_application.user}'

    @property
    def proof_url(self):
        first = self.proof_links.filter(is_public=True).order_by('position', 'created_at').first()
        return first.url if first else ''


class HumanitarianProofLink(models.Model):
    release = models.ForeignKey(HumanitarianRelease, on_delete=models.CASCADE, related_name='proof_links')
    url = models.URLField(max_length=600)
    title = models.CharField(max_length=180, blank=True)
    platform = models.CharField(max_length=40, blank=True, help_text='TikTok, Instagram, YouTube, X, etc.')
    is_public = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'created_at']
        indexes = [
            models.Index(fields=['release', 'is_public', 'position']),
        ]

    def __str__(self):
        return self.title or self.url
