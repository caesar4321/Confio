from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from users.models import SoftDeleteModel
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver


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
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_verifications',
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
        null=True,
        blank=True,
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
        null=True,
        blank=True,
        help_text="Selfie holding the identification document"
    )

    # S3 direct-upload URL fields (optional for presigned upload flow)
    document_front_url = models.URLField(
        null=True,
        blank=True,
        help_text="S3 URL to front side of document (if uploaded directly)"
    )
    document_back_url = models.URLField(
        null=True,
        blank=True,
        help_text="S3 URL to back side of document (if uploaded directly)"
    )
    selfie_url = models.URLField(
        null=True,
        blank=True,
        help_text="S3 URL to selfie with document (if uploaded directly)"
    )

    # Optional payout ownership proof integrated into ID verification (screenshot/statement)
    payout_method_label = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Label/name of payout method being proven (e.g., Nequi, Banco de Venezuela)"
    )
    payout_proof_url = models.URLField(
        null=True,
        blank=True,
        help_text="S3 URL to payout ownership proof (integrated with ID verification)"
    )
    
    # Verification Details
    status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending',
        help_text="Current verification status"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_verifications_approved',
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
    
    # Risk Assessment
    risk_score = models.IntegerField(
        default=0,
        help_text="Risk score 0-100 based on various factors"
    )
    risk_factors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Risk factors identified during verification"
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
        self.rejected_reason = reason
        self.save()


@receiver(post_save, sender=IdentityVerification)
def ensure_personal_verified_on_save(sender, instance: 'IdentityVerification', created, **kwargs):
    """Ensure personal verified record exists whenever a verification is saved as verified.
    Covers approvals done via admin edit (not using approve_verification) or other flows.
    Also sync verified first/last name back to the user to match approve_verification behavior.
    """
    try:
        if instance.status != 'verified':
            return
        # Sync verified name with user profile (idempotent)
        try:
            user = instance.user
            if user.first_name != instance.verified_first_name or user.last_name != instance.verified_last_name:
                user.first_name = instance.verified_first_name
                user.last_name = instance.verified_last_name
                user.save(update_fields=['first_name', 'last_name'])
        except Exception:
            pass

        # If this saved record is already personal, nothing to do
        if (instance.risk_factors or {}).get('account_type') != 'business':
            return
        # If there's already a personal (non-business) verified record, nothing to do
        has_personal_verified = IdentityVerification.objects.filter(
            user=instance.user,
            status='verified'
        ).filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')).exists()
        if has_personal_verified:
            return

        # Create a personal-context verified record to back personal status
        # Do this after the outer transaction commits and idempotently to avoid duplicates
        from django.db import transaction
        def create_personal_clone():
            try:
                IdentityVerification.objects.get_or_create(
                    user=instance.user,
                    status='verified',
                    document_number=instance.document_number,
                    # Personal context explicitly stored as empty dict
                    risk_factors={},
                    defaults={
                        'verified_first_name': instance.verified_first_name,
                        'verified_last_name': instance.verified_last_name,
                        'verified_date_of_birth': instance.verified_date_of_birth,
                        'verified_nationality': instance.verified_nationality,
                        'verified_address': instance.verified_address,
                        'verified_city': instance.verified_city,
                        'verified_state': instance.verified_state,
                        'verified_country': instance.verified_country,
                        'verified_postal_code': instance.verified_postal_code,
                        'document_type': instance.document_type,
                        'document_issuing_country': instance.document_issuing_country,
                        'document_expiry_date': instance.document_expiry_date,
                        'document_front_url': instance.document_front_url,
                        'document_back_url': instance.document_back_url,
                        'selfie_url': instance.selfie_url,
                        'payout_method_label': instance.payout_method_label,
                        'payout_proof_url': instance.payout_proof_url,
                        'verified_by': instance.verified_by,
                        'verified_at': instance.verified_at or timezone.now(),
                    }
                )
            except Exception:
                # Never break save due to this helper
                pass
        try:
            transaction.on_commit(create_personal_clone)
        except Exception:
            # Fallback: attempt immediate creation if on_commit unavailable
            create_personal_clone()
    except Exception:
        # Never break save due to this helper
        pass


class SuspiciousActivity(SoftDeleteModel):
    """Track suspicious patterns across the platform"""
    
    ACTIVITY_TYPE_CHOICES = [
        # Achievement/Referral related
        ('rapid_referrals', 'Referidos Rápidos'),
        ('duplicate_device', 'Dispositivo Duplicado'),
        ('unusual_pattern', 'Patrón Inusual'),
        ('fake_viral', 'Viral Falso'),
        ('account_farming', 'Farming de Cuentas'),
        # Transaction related
        ('money_laundering', 'Lavado de Dinero'),
        ('high_volume', 'Volumen Alto Inusual'),
        ('rapid_trades', 'Intercambios Rápidos'),
        ('price_manipulation', 'Manipulación de Precios'),
        # Security related
        ('multiple_accounts', 'Múltiples Cuentas'),
        ('vpn_abuse', 'Abuso de VPN'),
        ('location_mismatch', 'Ubicación No Coincide'),
        ('device_fingerprint', 'Huella Digital Sospechosa'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('investigating', 'Investigando'),
        ('confirmed', 'Confirmado'),
        ('dismissed', 'Descartado'),
        ('banned', 'Usuario Baneado'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_suspicious_activities'
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ACTIVITY_TYPE_CHOICES
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Detection data
    detection_data = models.JSONField(
        help_text="Data that triggered the detection"
    )
    severity_score = models.PositiveIntegerField(
        default=1,
        help_text="Severity score 1-10"
    )
    
    # Investigation
    investigated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_investigated_activities'
    )
    investigation_notes = models.TextField(
        blank=True
    )
    action_taken = models.TextField(
        blank=True,
        help_text="What action was taken"
    )
    
    # Related entities
    related_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='related_suspicious_activities',
        help_text="Other users potentially involved"
    )
    related_ips = ArrayField(
        models.GenericIPAddressField(),
        blank=True,
        default=list,
        help_text="IP addresses involved"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Suspicious Activity"
        verbose_name_plural = "Suspicious Activities"
        indexes = [
            models.Index(fields=['user', 'activity_type', 'status']),
            models.Index(fields=['severity_score', 'status']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_activity_type_display()} ({self.status})"


class UserBan(SoftDeleteModel):
    """Track banned users and reasons"""
    
    BAN_TYPE_CHOICES = [
        ('temporary', 'Temporal'),
        ('permanent', 'Permanente'),
        ('trading', 'Solo Trading'),
        ('withdrawal', 'Solo Retiros'),
    ]
    
    REASON_CHOICES = [
        ('fraud', 'Fraude'),
        ('money_laundering', 'Lavado de Dinero'),
        ('terms_violation', 'Violación de Términos'),
        ('multiple_accounts', 'Múltiples Cuentas'),
        ('suspicious_activity', 'Actividad Sospechosa'),
        ('document_fraud', 'Fraude Documental'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bans'
    )
    ban_type = models.CharField(
        max_length=20,
        choices=BAN_TYPE_CHOICES
    )
    reason = models.CharField(
        max_length=30,
        choices=REASON_CHOICES
    )
    reason_details = models.TextField(
        help_text="Detailed explanation of the ban"
    )
    
    # Ban duration
    banned_at = models.DateTimeField(
        default=timezone.now
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the ban expires (null for permanent)"
    )
    
    # Admin who issued the ban
    banned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='bans_issued'
    )
    
    # Related suspicious activity
    suspicious_activity = models.ForeignKey(
        SuspiciousActivity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resulting_bans'
    )
    
    # Appeal process
    appeal_submitted = models.BooleanField(default=False)
    appeal_text = models.TextField(blank=True)
    appeal_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ban_appeals_reviewed'
    )
    appeal_decision = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-banned_at']
        verbose_name = "User Ban"
        verbose_name_plural = "User Bans"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_ban_type_display()} - {self.reason}"
    
    @property
    def is_active(self):
        """Check if ban is currently active"""
        if self.deleted_at:
            return False
        if self.expires_at:
            return timezone.now() < self.expires_at
        return True


class IPAddress(models.Model):
    """Track IP addresses for security and fraud detection"""
    
    ip_address = models.GenericIPAddressField(
        unique=True
    )
    country_code = models.CharField(
        max_length=2,
        blank=True,
        help_text="ISO country code"
    )
    country_name = models.CharField(
        max_length=100,
        blank=True
    )
    region = models.CharField(
        max_length=100,
        blank=True
    )
    city = models.CharField(
        max_length=100,
        blank=True
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    
    # Risk indicators
    is_vpn = models.BooleanField(
        default=False,
        help_text="Detected as VPN/Proxy"
    )
    is_tor = models.BooleanField(
        default=False,
        help_text="Detected as Tor exit node"
    )
    is_datacenter = models.BooleanField(
        default=False,
        help_text="Detected as datacenter IP"
    )
    risk_score = models.IntegerField(
        default=0,
        help_text="Risk score 0-100"
    )
    
    # Tracking
    first_seen = models.DateTimeField(
        default=timezone.now
    )
    last_seen = models.DateTimeField(
        default=timezone.now
    )
    total_users = models.IntegerField(
        default=0,
        help_text="Total unique users from this IP"
    )
    
    # Blocking
    is_blocked = models.BooleanField(
        default=False
    )
    blocked_reason = models.TextField(
        blank=True
    )
    blocked_at = models.DateTimeField(
        null=True,
        blank=True
    )
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ips_blocked'
    )
    
    class Meta:
        verbose_name = "IP Address"
        verbose_name_plural = "IP Addresses"
        indexes = [
            models.Index(fields=['country_code']),
            models.Index(fields=['is_vpn', 'is_tor', 'is_datacenter']),
            models.Index(fields=['risk_score']),
        ]
    
    def __str__(self):
        return f"{self.ip_address} ({self.country_code})"


class IPDeviceUser(models.Model):
    """Track associations between IPs, Devices, and Users for fraud detection"""
    
    ip_address = models.ForeignKey(
        IPAddress,
        on_delete=models.CASCADE,
        related_name='device_user_associations'
    )
    device_fingerprint = models.ForeignKey(
        'DeviceFingerprint',
        on_delete=models.CASCADE,
        related_name='ip_user_associations'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ip_device_associations'
    )
    
    # Activity tracking
    first_seen = models.DateTimeField(
        default=timezone.now,
        help_text="First time this IP-Device-User combination was seen"
    )
    last_seen = models.DateTimeField(
        default=timezone.now,
        help_text="Last activity from this combination"
    )
    total_sessions = models.IntegerField(
        default=1,
        help_text="Total sessions from this combination"
    )
    
    # Location info at time of association
    location_info = models.JSONField(
        default=dict,
        blank=True,
        help_text="Location data: city, region, coordinates, etc."
    )
    
    # Risk indicators
    is_suspicious = models.BooleanField(
        default=False,
        help_text="Flagged as suspicious combination"
    )
    risk_factors = models.JSONField(
        default=list,
        blank=True,
        help_text="List of risk factors: rapid_location_change, multiple_users_same_ip, etc."
    )
    
    # Authentication context
    auth_method = models.CharField(
        max_length=50,
        blank=True,
        help_text="How user authenticated: google, apple, etc."
    )
    
    class Meta:
        verbose_name = "IP-Device-User Association"
        verbose_name_plural = "IP-Device-User Associations"
        unique_together = ['ip_address', 'device_fingerprint', 'user']
        indexes = [
            models.Index(fields=['user', 'last_seen']),
            models.Index(fields=['device_fingerprint', 'last_seen']),
            models.Index(fields=['ip_address', 'last_seen']),
            models.Index(fields=['is_suspicious']),
            models.Index(fields=['first_seen', 'last_seen']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.device_fingerprint.fingerprint[:8]}... - {self.ip_address.ip_address}"
    
    def calculate_risk_factors(self):
        """Calculate and update risk factors for this association"""
        risk_factors = []
        
        # Check if this IP has multiple users
        ip_user_count = IPDeviceUser.objects.filter(
            ip_address=self.ip_address
        ).values('user').distinct().count()
        
        if ip_user_count > 5:  # More than 5 users on same IP
            risk_factors.append('high_user_count_on_ip')
        
        # Check if this device has multiple users
        device_user_count = self.device_fingerprint.users.count()
        if device_user_count > 1:
            risk_factors.append('multiple_users_same_device')
        
        # Check rapid location changes
        # (This would need to be implemented based on session history)
        
        # Check if IP is VPN/Tor/Datacenter
        if self.ip_address.is_vpn:
            risk_factors.append('vpn_detected')
        if self.ip_address.is_tor:
            risk_factors.append('tor_detected')
        if self.ip_address.is_datacenter:
            risk_factors.append('datacenter_ip')
        
        self.risk_factors = risk_factors
        self.is_suspicious = len(risk_factors) > 0
        self.save(update_fields=['risk_factors', 'is_suspicious'])
        
        return risk_factors


class UserSession(models.Model):
    """Track user sessions for security monitoring"""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_sessions'
    )
    
    # Session info
    session_key = models.CharField(
        max_length=255,
        unique=True,
        help_text="Django session key"
    )
    started_at = models.DateTimeField(
        default=timezone.now
    )
    last_activity = models.DateTimeField(
        default=timezone.now
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    # Device info
    device_fingerprint = models.CharField(
        max_length=255,
        help_text="Browser/device fingerprint"
    )
    user_agent = models.TextField()
    device_type = models.CharField(
        max_length=20,
        choices=[
            ('mobile', 'Mobile'),
            ('tablet', 'Tablet'),
            ('desktop', 'Desktop'),
            ('unknown', 'Unknown'),
        ],
        default='unknown'
    )
    os_name = models.CharField(
        max_length=50,
        blank=True
    )
    browser_name = models.CharField(
        max_length=50,
        blank=True
    )
    
    # Location info
    ip_address = models.ForeignKey(
        IPAddress,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sessions'
    )
    
    # Security flags
    is_suspicious = models.BooleanField(
        default=False,
        help_text="Flagged as suspicious session"
    )
    suspicious_reasons = models.JSONField(
        default=list,
        blank=True
    )
    
    class Meta:
        ordering = ['-started_at']
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"
        indexes = [
            models.Index(fields=['user', 'started_at']),
            models.Index(fields=['device_fingerprint']),
            models.Index(fields=['is_suspicious']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.started_at} - {self.device_type}"


class DeviceFingerprint(models.Model):
    """Track unique device fingerprints for fraud detection"""
    
    fingerprint = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique device fingerprint hash"
    )
    
    # Device details
    device_details = models.JSONField(
        default=dict,
        help_text="Detailed device information"
    )
    
    # User associations
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='UserDevice',
        related_name='device_fingerprints'
    )
    
    # Risk assessment
    risk_score = models.IntegerField(
        default=0,
        help_text="Risk score 0-100"
    )
    total_users = models.IntegerField(
        default=0,
        help_text="Total unique users on this device"
    )
    
    # Tracking
    first_seen = models.DateTimeField(
        default=timezone.now
    )
    last_seen = models.DateTimeField(
        default=timezone.now
    )
    
    # Blocking
    is_blocked = models.BooleanField(
        default=False
    )
    blocked_reason = models.TextField(
        blank=True
    )
    
    class Meta:
        verbose_name = "Device Fingerprint"
        verbose_name_plural = "Device Fingerprints"
        indexes = [
            models.Index(fields=['risk_score']),
            models.Index(fields=['total_users']),
        ]
    
    def __str__(self):
        return f"{self.fingerprint[:20]}... ({self.total_users} users)"


class UserDevice(models.Model):
    """Link users to their devices"""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    device = models.ForeignKey(
        DeviceFingerprint,
        on_delete=models.CASCADE
    )
    
    # Usage tracking
    first_used = models.DateTimeField(
        default=timezone.now
    )
    last_used = models.DateTimeField(
        default=timezone.now
    )
    total_sessions = models.IntegerField(
        default=1
    )
    
    # Trust level
    is_trusted = models.BooleanField(
        default=False,
        help_text="User has verified this device"
    )
    trusted_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    class Meta:
        unique_together = [['user', 'device']]
        verbose_name = "User Device"
        verbose_name_plural = "User Devices"
    
    def __str__(self):
        return f"{self.user.username} - Device {self.device.fingerprint[:20]}..."


class AMLCheck(SoftDeleteModel):
    """Anti-Money Laundering checks and monitoring"""
    
    CHECK_TYPE_CHOICES = [
        ('manual', 'Manual Review'),
        ('automated', 'Automated Check'),
        ('periodic', 'Periodic Review'),
        ('triggered', 'Triggered by Activity'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('cleared', 'Aprobado'),
        ('flagged', 'Marcado'),
        ('escalated', 'Escalado'),
        ('blocked', 'Bloqueado'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='aml_checks'
    )
    
    check_type = models.CharField(
        max_length=20,
        choices=CHECK_TYPE_CHOICES
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Check details
    risk_score = models.IntegerField(
        default=0,
        help_text="AML risk score 0-100"
    )
    risk_factors = models.JSONField(
        default=dict,
        help_text="Identified risk factors"
    )
    
    # Transaction analysis
    transaction_volume_30d = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total transaction volume in last 30 days (USD)"
    )
    transaction_count_30d = models.IntegerField(
        default=0,
        help_text="Number of transactions in last 30 days"
    )
    unusual_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text="Detected unusual transaction patterns"
    )
    
    # Review process
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='aml_checks_reviewed'
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    review_notes = models.TextField(
        blank=True
    )
    
    # Actions taken
    actions_required = models.JSONField(
        default=list,
        blank=True,
        help_text="Required actions based on check"
    )
    actions_taken = models.JSONField(
        default=list,
        blank=True,
        help_text="Actions taken after review"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "AML Check"
        verbose_name_plural = "AML Checks"
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['risk_score', 'status']),
        ]
    
    def __str__(self):
        return f"AML Check for {self.user.username} - {self.get_status_display()}"


class IntegrityVerdict(models.Model):
    """
    Play Integrity API verification results.
    Tracks every integrity check for each user to detect historical violations.
    
    Key feature: When claiming rewards, we check both current device AND
    historical records to prevent emulator->legit device abuse.
    """
    
    TRIGGER_ACTION_CHOICES = [
        ('signup', 'Signup'),
        ('reward_claim', 'Reward Claim'),
        ('transfer', 'Transfer/Withdrawal'),
        ('login', 'Login'),
        ('payroll', 'Payroll'),
        ('topup_sell', 'TopUp/Sell'),
        ('payment', 'Payment'),
    ]
    
    APP_RECOGNITION_CHOICES = [
        ('PLAY_RECOGNIZED', 'Play Recognized'),
        ('UNRECOGNIZED_VERSION', 'Unrecognized Version'),
        ('UNEVALUATED', 'Unevaluated'),
    ]
    
    APP_LICENSING_CHOICES = [
        ('LICENSED', 'Licensed'),
        ('UNLICENSED', 'Unlicensed'),
        ('UNEVALUATED', 'Unevaluated'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='integrity_verdicts',
        help_text="User being verified"
    )
    device_fingerprint = models.CharField(
        max_length=255,
        blank=True,
        help_text="Device fingerprint hash at time of check"
    )
    
    # Integrity Verdicts from Google
    app_recognition = models.CharField(
        max_length=50,
        choices=APP_RECOGNITION_CHOICES,
        default='UNEVALUATED',
        help_text="Whether app is recognized by Play Store"
    )
    device_integrity = models.JSONField(
        default=list,
        help_text="Device integrity labels: MEETS_DEVICE_INTEGRITY, MEETS_BASIC_INTEGRITY, etc."
    )
    app_licensing = models.CharField(
        max_length=50,
        choices=APP_LICENSING_CHOICES,
        default='UNEVALUATED',
        help_text="Whether app is licensed from Play Store"
    )
    
    # Computed flags for quick querying
    is_emulator = models.BooleanField(
        default=False,
        help_text="No device integrity = likely emulator"
    )
    is_rooted = models.BooleanField(
        default=False,
        help_text="Only MEETS_BASIC_INTEGRITY = likely rooted"
    )
    passed = models.BooleanField(
        default=False,
        help_text="Did this check pass our requirements?"
    )
    
    # Context
    trigger_action = models.CharField(
        max_length=20,
        choices=TRIGGER_ACTION_CHOICES,
        help_text="What action triggered this check"
    )
    raw_response = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw decoded response from Google (for debugging)"
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error message if verification failed"
    )
    
    # Metadata
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Integrity Verdict"
        verbose_name_plural = "Integrity Verdicts"
        indexes = [
            models.Index(fields=['user', 'passed']),
            models.Index(fields=['user', 'trigger_action', 'created_at']),
            models.Index(fields=['is_emulator']),
            models.Index(fields=['is_rooted']),
        ]
    
    def __str__(self):
        status = "✓" if self.passed else "✗"
        return f"{status} {self.user.username} - {self.trigger_action} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    @classmethod
    def has_historical_violation(cls, user) -> bool:
        """
        Check if user has ANY failed integrity check in their history.
        Used to block reward claims from users who previously used
        emulator/rooted devices.
        """
        return cls.objects.filter(
            user=user,
            passed=False
        ).exists()
    
    @classmethod
    def has_emulator_history(cls, user) -> bool:
        """Check if user ever used an emulator."""
        return cls.objects.filter(
            user=user,
            is_emulator=True
        ).exists()

