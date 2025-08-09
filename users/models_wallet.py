"""
Wallet-related models for secure key derivation
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta


class WalletPepper(models.Model):
    """
    Server-side pepper for additional entropy in wallet key derivation.
    Each account gets its own pepper for security isolation.
    """
    account_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text='Unique key per account: user_{id}_{type}_{index} or user_{id}_business_{businessId}_{index}'
    )
    
    pepper = models.CharField(
        max_length=64,  # 32 bytes as hex = 64 chars
        help_text='Random pepper for additional entropy'
    )
    
    version = models.IntegerField(
        default=1,
        help_text='Pepper version for rotation support'
    )
    
    # Grace period fields for rotation
    previous_pepper = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text='Previous pepper kept during grace period'
    )
    
    previous_version = models.IntegerField(
        blank=True,
        null=True,
        help_text='Previous version number'
    )
    
    grace_period_until = models.DateTimeField(
        blank=True,
        null=True,
        help_text='When the grace period for using previous pepper ends'
    )
    
    rotated_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text='When the pepper was last rotated'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_wallet_pepper'  # Use existing table name
        verbose_name = 'Account Wallet Pepper'
        verbose_name_plural = 'Account Wallet Peppers'
        ordering = ['-created_at']
    
    def __str__(self):
        return f'Pepper for {self.account_key} (v{self.version})'
    
    def is_in_grace_period(self):
        """Check if we're still in grace period for previous pepper"""
        if not self.grace_period_until:
            return False
        return timezone.now() < self.grace_period_until
    
    def rotate_pepper(self, new_pepper):
        """Rotate to a new pepper with grace period"""
        self.previous_pepper = self.pepper
        self.previous_version = self.version
        self.grace_period_until = timezone.now() + timedelta(days=7)
        self.pepper = new_pepper
        self.version += 1
        self.rotated_at = timezone.now()
        self.save()