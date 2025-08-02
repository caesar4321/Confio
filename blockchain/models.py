from django.db import models
from users.models import Account


class RawBlockchainEvent(models.Model):
    """Stores raw blockchain events for audit trail"""
    tx_hash = models.CharField(max_length=66, unique=True, db_index=True)
    sender = models.CharField(max_length=66, db_index=True)
    module = models.CharField(max_length=66, db_index=True)
    function = models.CharField(max_length=100)
    raw_data = models.JSONField()
    block_time = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['sender', 'block_time']),
            models.Index(fields=['module', 'function']),
            models.Index(fields=['processed', 'created_at']),
        ]
        ordering = ['-block_time']
    
    def __str__(self):
        return f"{self.tx_hash[:8]}... ({self.module}::{self.function})"


class Balance(models.Model):
    """Cached token balances for accounts"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='balances')
    token = models.CharField(max_length=20, choices=[
        ('CUSD', 'cUSD'),
        ('CONFIO', 'CONFIO'),
        ('SUI', 'SUI'),
        ('USDC', 'USDC'),
    ])
    amount = models.DecimalField(max_digits=36, decimal_places=18)
    pending_amount = models.DecimalField(max_digits=36, decimal_places=18, default=0)  # For in-flight transactions
    last_synced = models.DateTimeField(auto_now=True)
    is_stale = models.BooleanField(default=False, help_text="True if balance needs refresh")
    last_blockchain_check = models.DateTimeField(null=True, blank=True)
    sync_attempts = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['account', 'token']
        indexes = [
            models.Index(fields=['account', 'token']),
            models.Index(fields=['is_stale', 'last_synced']),
        ]
    
    def __str__(self):
        return f"{self.account} - {self.amount} {self.token}"
    
    @property
    def available_amount(self):
        """Amount available for spending (total - pending)"""
        return self.amount - self.pending_amount
    
    def mark_stale(self):
        """Mark balance as needing refresh"""
        self.is_stale = True
        self.save(update_fields=['is_stale'])


class TransactionProcessingLog(models.Model):
    """Log of transaction processing for debugging"""
    raw_event = models.ForeignKey(RawBlockchainEvent, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])
    error_message = models.TextField(blank=True, null=True)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]
