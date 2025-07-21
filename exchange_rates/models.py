from django.db import models
from django.utils import timezone


class ExchangeRate(models.Model):
    """
    Model to store exchange rates from various sources
    Primarily focused on VES/USD rates for Venezuelan market
    """
    
    RATE_TYPE_CHOICES = [
        ('official', 'Official Rate'),
        ('parallel', 'Parallel Market Rate'),
        ('black_market', 'Black Market Rate'),
        ('average', 'Average Rate'),
    ]
    
    SOURCE_CHOICES = [
        ('yadio', 'Yadio.io'),
        ('exchangerate_api', 'ExchangeRate-API'),
        ('currencylayer', 'CurrencyLayer'),
        ('bluelytics', 'Bluelytics (Argentina)'),
        ('dolarapi', 'DolarAPI (Argentina)'),
        ('bcv', 'Banco Central de Venezuela'),
        ('manual', 'Manual Entry'),
    ]
    
    # Currency pair
    source_currency = models.CharField(max_length=3, default='VES', help_text='Source currency (e.g., VES)')
    target_currency = models.CharField(max_length=3, default='USD', help_text='Target currency (e.g., USD)')
    
    # Rate information
    rate = models.DecimalField(max_digits=15, decimal_places=6, help_text='How many source_currency per 1 target_currency')
    rate_type = models.CharField(max_length=20, choices=RATE_TYPE_CHOICES, default='parallel')
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    
    # Metadata
    fetched_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, help_text='Whether this rate is currently valid')
    
    # Additional data from API response
    raw_data = models.JSONField(null=True, blank=True, help_text='Raw API response for debugging')
    
    class Meta:
        ordering = ['-fetched_at']
        indexes = [
            models.Index(fields=['source_currency', 'target_currency', 'rate_type']),
            models.Index(fields=['fetched_at']),
            models.Index(fields=['is_active', 'rate_type']),
        ]
        unique_together = ['source_currency', 'target_currency', 'rate_type', 'source', 'fetched_at']
    
    def __str__(self):
        return f"1 {self.target_currency} = {self.rate} {self.source_currency} ({self.rate_type}, {self.source})"
    
    @classmethod
    def get_latest_rate(cls, source_currency='VES', target_currency='USD', rate_type='parallel'):
        """
        Get the most recent exchange rate for a currency pair
        """
        try:
            return cls.objects.filter(
                source_currency=source_currency,
                target_currency=target_currency,
                rate_type=rate_type,
                is_active=True
            ).first()
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def get_rate_value(cls, source_currency='VES', target_currency='USD', rate_type='parallel'):
        """
        Get just the rate value (Decimal) for a currency pair
        Returns None if no rate found
        """
        rate_obj = cls.get_latest_rate(source_currency, target_currency, rate_type)
        return rate_obj.rate if rate_obj else None


class RateFetchLog(models.Model):
    """
    Log of rate fetching attempts for monitoring and debugging
    """
    
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),
    ]
    
    source = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    rates_fetched = models.IntegerField(default=0, help_text='Number of rates successfully fetched')
    error_message = models.TextField(null=True, blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True, help_text='API response time in milliseconds')
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.source} - {self.status} ({self.rates_fetched} rates) at {self.created_at}"