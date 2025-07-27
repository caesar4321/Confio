from django.db import models
from django.conf import settings


class UnifiedUSDCTransaction(models.Model):
    """Unified view model for USDC transactions (deposits, withdrawals, and conversions)"""
    
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('conversion', 'Conversion'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    # Transaction identification
    transaction_id = models.CharField(max_length=36, primary_key=True, help_text='UUID of the source transaction')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    
    # Actor information (unified from all transaction types)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text='User associated with the transaction'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text='Business associated with the transaction'
    )
    actor_type = models.CharField(max_length=10, choices=[('user', 'Personal'), ('business', 'Business')])
    actor_display_name = models.CharField(max_length=255, blank=True)
    actor_address = models.CharField(max_length=66, blank=True)
    
    # Transaction details
    amount = models.DecimalField(max_digits=19, decimal_places=6, help_text='Primary amount (USDC for deposits/withdrawals, source amount for conversions)')
    currency = models.CharField(max_length=10, default='USDC', help_text='Primary currency')
    
    # Secondary amount for conversions
    secondary_amount = models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True, help_text='Converted amount for conversions')
    secondary_currency = models.CharField(max_length=10, blank=True, help_text='Converted currency for conversions')
    
    # Exchange rate for conversions
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    # Fees
    network_fee = models.DecimalField(max_digits=19, decimal_places=6, default=0)
    service_fee = models.DecimalField(max_digits=19, decimal_places=6, default=0)
    
    # Address information
    source_address = models.CharField(max_length=66, blank=True, help_text='Source address (for deposits and conversions)')
    destination_address = models.CharField(max_length=66, blank=True, help_text='Destination address (for withdrawals and conversions)')
    
    # Transaction tracking
    transaction_hash = models.CharField(max_length=66, blank=True, null=True)
    block_number = models.BigIntegerField(blank=True, null=True)
    network = models.CharField(max_length=20, default='SUI')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    completed_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        managed = False  # This is a view, not a table
        db_table = 'unified_usdc_transactions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.actor_display_name} - {self.get_transaction_type_display()} {self.amount} {self.currency} - {self.status}"
    
    @property
    def is_completed(self):
        return self.status == 'COMPLETED'
    
    @property
    def is_failed(self):
        return self.status == 'FAILED'
    
    @property
    def formatted_title(self):
        """Get formatted title for UI display"""
        if self.transaction_type == 'deposit':
            return f"Depósito USDC"
        elif self.transaction_type == 'withdrawal':
            return f"Retiro USDC"
        elif self.transaction_type == 'conversion':
            if self.secondary_currency:
                return f"{self.currency} → {self.secondary_currency}"
            else:
                return "Conversión"
        return self.get_transaction_type_display()
    
    @property
    def icon_name(self):
        """Get icon name for UI display"""
        if self.transaction_type == 'deposit':
            return 'arrow-down-circle'
        elif self.transaction_type == 'withdrawal':
            return 'arrow-up-circle'
        elif self.transaction_type == 'conversion':
            return 'refresh-cw'
        return 'circle'
    
    @property
    def icon_color(self):
        """Get icon color for UI display"""
        if self.transaction_type == 'deposit':
            return '#34D399'  # Green
        elif self.transaction_type == 'withdrawal':
            return '#EF4444'  # Red
        elif self.transaction_type == 'conversion':
            return '#3B82F6'  # Blue
        return '#6B7280'  # Gray