from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone
from decimal import Decimal


class Conversion(models.Model):
    """Model to track USDC <-> cUSD conversions"""
    
    CONVERSION_TYPES = [
        ('usdc_to_cusd', 'USDC to cUSD'),
        ('cusd_to_usdc', 'cUSD to USDC'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PENDING_SIG', 'Pending Signature'),
        ('SUBMITTED', 'Submitted'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    # Unique identifier
    conversion_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Direct User/Business actor pattern
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_conversions',
        null=True,
        blank=True,
        help_text='User who initiated the conversion (if personal account)'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='business_conversions',
        null=True,
        blank=True,
        help_text='Business that initiated the conversion (if business account)'
    )
    
    ACTOR_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
    ]
    
    actor_type = models.CharField(
        max_length=10,
        choices=ACTOR_TYPE_CHOICES,
        help_text='Type of actor (user or business)'
    )
    actor_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name of the actor at conversion time'
    )
    actor_address = models.CharField(
        max_length=66,
        blank=True,
        help_text='Blockchain address of the actor'
    )
    
    # Conversion details
    conversion_type = models.CharField(max_length=20, choices=CONVERSION_TYPES)
    from_amount = models.DecimalField(max_digits=19, decimal_places=6)  # Amount being converted from
    to_amount = models.DecimalField(max_digits=19, decimal_places=6)  # Amount received after conversion
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal('1.000000'))  # Exchange rate used
    fee_amount = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'))  # Fee charged (if any)
    
    # Transaction hashes for blockchain tracking
    from_transaction_hash = models.CharField(max_length=66, blank=True, null=True)  # Transaction hash for source token
    to_transaction_hash = models.CharField(max_length=66, blank=True, null=True)  # Transaction hash for destination token
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'conversions'
        indexes = [
            models.Index(fields=['actor_user', 'status'], name='conv_actor_user_status_idx'),
            models.Index(fields=['actor_business', 'status'], name='conv_actor_bus_status_idx'),
            models.Index(fields=['actor_type', 'status'], name='conv_actor_type_status_idx'),
            models.Index(fields=['conversion_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        actor_name = self.actor_display_name or "Unknown"
        return f"{actor_name} - {self.get_conversion_type_display()} - {self.from_amount} to {self.to_amount} - {self.status}"
    
    def clean(self):
        """Validate that either actor_user or actor_business is set, but not both"""
        from django.core.exceptions import ValidationError
        
        if self.actor_type == 'user' and not self.actor_user:
            raise ValidationError("actor_user must be set when actor_type is 'user'")
        elif self.actor_type == 'business' and not self.actor_business:
            raise ValidationError("actor_business must be set when actor_type is 'business'")
        
        if self.actor_user and self.actor_business:
            raise ValidationError("Only one of actor_user or actor_business should be set")
    
    @property
    def is_completed(self):
        return self.status == 'COMPLETED'
    
    @property
    def is_failed(self):
        return self.status == 'FAILED'
    
    def mark_completed(self, to_transaction_hash=None):
        """Mark the conversion as completed"""
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        if to_transaction_hash:
            self.to_transaction_hash = to_transaction_hash
        self.save()
    
    def mark_failed(self, error_message):
        """Mark the conversion as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.save()
