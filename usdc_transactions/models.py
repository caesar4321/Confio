from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone
from decimal import Decimal


class USDCDeposit(models.Model):
    """Model to track USDC deposits from external wallets to Confío"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    # Unique identifier
    deposit_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Direct User/Business actor pattern
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_usdc_deposits',
        null=True,
        blank=True,
        help_text='User who made the deposit (if personal account)'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='business_usdc_deposits',
        null=True,
        blank=True,
        help_text='Business that made the deposit (if business account)'
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
        help_text='Display name of the actor at deposit time'
    )
    actor_address = models.CharField(
        max_length=66,
        blank=True,
        help_text='Confío wallet address receiving the deposit'
    )
    
    # Deposit details
    amount = models.DecimalField(max_digits=19, decimal_places=6, help_text='Amount of USDC deposited')
    source_address = models.CharField(max_length=66, help_text='External wallet address that sent the USDC')
    network = models.CharField(max_length=20, default='ALGORAND', help_text='Blockchain network used')
    
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
        db_table = 'usdc_deposits'
        verbose_name = 'USDC Deposit'
        verbose_name_plural = 'USDC Deposits'
        indexes = [
            models.Index(fields=['actor_user', 'status'], name='usdc_dep_actor_user_status_idx'),
            models.Index(fields=['actor_business', 'status'], name='usdc_dep_actor_bus_status_idx'),
            models.Index(fields=['actor_type', 'status'], name='usdc_dep_actor_type_status_idx'),
            models.Index(fields=['deposit_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        actor_name = self.actor_display_name or "Unknown"
        return f"{actor_name} - Deposit {self.amount} USDC - {self.status}"
    
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
    
    def mark_completed(self):
        """Mark the deposit as completed"""
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()
    
    def mark_failed(self, error_message):
        """Mark the deposit as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.save()


class USDCWithdrawal(models.Model):
    """Model to track USDC withdrawals from Confío to external wallets"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    # Unique identifier
    withdrawal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Direct User/Business actor pattern
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_usdc_withdrawals',
        null=True,
        blank=True,
        help_text='User who made the withdrawal (if personal account)'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='business_usdc_withdrawals',
        null=True,
        blank=True,
        help_text='Business that made the withdrawal (if business account)'
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
        help_text='Display name of the actor at withdrawal time'
    )
    actor_address = models.CharField(
        max_length=66,
        blank=True,
        help_text='Confío wallet address making the withdrawal'
    )
    
    # Withdrawal details
    amount = models.DecimalField(max_digits=19, decimal_places=6, help_text='Amount of USDC withdrawn')
    destination_address = models.CharField(max_length=66, help_text='External wallet address receiving the USDC')
    network = models.CharField(max_length=20, default='ALGORAND', help_text='Blockchain network used')
    
    # Fee information
    service_fee = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal('0'), help_text='Confío service fee')
    
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
        db_table = 'usdc_withdrawals'
        verbose_name = 'USDC Withdrawal'
        verbose_name_plural = 'USDC Withdrawals'
        indexes = [
            models.Index(fields=['actor_user', 'status'], name='usdc_w_actor_user_status_idx'),
            models.Index(fields=['actor_business', 'status'], name='usdc_w_actor_bus_status_idx'),
            models.Index(fields=['actor_type', 'status'], name='usdc_w_actor_type_status_idx'),
            models.Index(fields=['withdrawal_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        actor_name = self.actor_display_name or "Unknown"
        return f"{actor_name} - Withdrawal {self.amount} USDC - {self.status}"
    
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
    
    def mark_completed(self):
        """Mark the withdrawal as completed"""
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()
    
    def mark_failed(self, error_message):
        """Mark the withdrawal as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.save()


# Import new table models
from .models_unified import UnifiedUSDCTransactionTable

