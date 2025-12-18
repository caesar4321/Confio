# Django models for unified USDC transaction table
from django.db import models
from django.conf import settings


class UnifiedUSDCTransactionTable(models.Model):
    """
    Actual table for unified USDC transactions.
    Maintains foreign keys to source tables for data integrity.
    """
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('conversion', 'Conversion'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PENDING_SIG', 'Pending Signature'),
        ('SUBMITTED', 'Submitted'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    # Primary key
    id = models.BigAutoField(primary_key=True)
    
    # Transaction identification
    transaction_id = models.UUIDField(unique=True, help_text='UUID of the source transaction')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, db_index=True)
    
    # Foreign keys to source tables (only one will be set)
    usdc_deposit = models.OneToOneField(
        'usdc_transactions.USDCDeposit',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    usdc_withdrawal = models.OneToOneField(
        'usdc_transactions.USDCWithdrawal',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    conversion = models.OneToOneField(
        'conversion.Conversion',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_usdc_transaction'
    )
    
    # Actor information (unified from all transaction types)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='unified_usdc_table_transactions',
        help_text='User associated with the transaction'
    )
    actor_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='unified_usdc_table_transactions',
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
    network = models.CharField(max_length=20, default='ALGORAND')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    error_message = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(help_text='When the transaction was created')
    transaction_date = models.DateTimeField()  # Original transaction date from source
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        db_table = 'unified_usdc_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
            models.Index(fields=['actor_user', '-created_at']),
            models.Index(fields=['actor_business', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.actor_display_name} - {self.get_transaction_type_display()} {self.amount} {self.currency} - {self.status}"

    @property
    def internal_id(self):
        """Return standardized internal_id from linked source models"""
        if self.transaction_type == 'deposit' and self.usdc_deposit:
            return self.usdc_deposit.internal_id
        if self.transaction_type == 'withdrawal' and self.usdc_withdrawal:
            return self.usdc_withdrawal.internal_id
        if self.transaction_type == 'conversion' and self.conversion:
            return self.conversion.internal_id
        return None
    
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
            # Prefer actual conversion direction from related Conversion row if present
            try:
                conv = getattr(self, 'conversion', None)
                if conv and getattr(conv, 'conversion_type', None):
                    if conv.conversion_type == 'usdc_to_cusd':
                        return "USDC → cUSD"
                    elif conv.conversion_type == 'cusd_to_usdc':
                        return "cUSD → USDC"
            except Exception:
                pass
            # Fallback to inferring from stored currencies
            if self.secondary_currency:
                return f"{self.currency} → {self.secondary_currency}"
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

    @property
    def signed_amount(self) -> str:
        """Primary amount with sign for UI (+/- USDC)."""
        try:
            if self.transaction_type == 'deposit':
                return f"+{self.amount}"
            if self.transaction_type == 'withdrawal':
                return f"-{self.amount}"
            if self.transaction_type == 'conversion':
                conv = getattr(self, 'conversion', None)
                if conv and getattr(conv, 'conversion_type', None):
                    # Primary is always USDC; sign depends on direction
                    if conv.conversion_type == 'usdc_to_cusd':
                        return f"-{self.amount}"  # USDC out
                    elif conv.conversion_type == 'cusd_to_usdc':
                        return f"+{self.amount}"  # USDC in
                # Fallback: assume USDC out if secondary currency present is cUSD
                if (self.secondary_currency or '').upper() == 'CUSD':
                    return f"-{self.amount}"
        except Exception:
            pass
        return str(self.amount)

    @property
    def signed_secondary_amount(self) -> str:
        """Secondary amount (for conversions) with sign for UI (+/- cUSD). Empty for non-conversions."""
        try:
            if self.transaction_type != 'conversion' or not self.secondary_amount:
                return ''
            conv = getattr(self, 'conversion', None)
            if conv and getattr(conv, 'conversion_type', None):
                if conv.conversion_type == 'usdc_to_cusd':
                    return f"+{self.secondary_amount}"  # cUSD in
                elif conv.conversion_type == 'cusd_to_usdc':
                    return f"-{self.secondary_amount}"  # cUSD out
            # Fallback by currencies
            if (self.secondary_currency or '').upper() == 'CUSD':
                # If secondary is cUSD and primary is USDC, default to +cUSD
                return f"+{self.secondary_amount}"
        except Exception:
            pass
        return str(self.secondary_amount or '')
