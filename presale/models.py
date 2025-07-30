from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal

User = get_user_model()


class PresaleSettings(models.Model):
    """Global presale settings - singleton model"""
    is_presale_active = models.BooleanField(
        default=False,
        help_text="Master switch to enable/disable all presale features in the app"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Presale Settings"
        verbose_name_plural = "Presale Settings"
    
    def __str__(self):
        return f"Presale Settings (Active: {self.is_presale_active})"
    
    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.__class__.objects.exclude(id=self.id).delete()
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance"""
        settings, created = cls.objects.get_or_create(id=1)
        return settings


class PresalePhase(models.Model):
    """Represents different phases of the presale"""
    PHASE_STATUS_CHOICES = [
        ('coming_soon', 'Coming Soon'),
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('paused', 'Paused'),
    ]
    
    phase_number = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField()
    price_per_token = models.DecimalField(
        max_digits=10, 
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    goal_amount = models.DecimalField(
        max_digits=15, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    min_purchase = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('10.00'),
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    max_purchase = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('1000.00'),
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    max_per_user = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum total purchase per user for this phase"
    )
    status = models.CharField(
        max_length=20, 
        choices=PHASE_STATUS_CHOICES,
        default='upcoming'
    )
    target_audience = models.CharField(
        max_length=100,
        default='Comunidad',
        help_text="Target audience for this phase"
    )
    location_emoji = models.CharField(
        max_length=50,
        default='🌎',
        help_text="Emoji and location text"
    )
    vision_points = models.JSONField(
        default=list,
        help_text="List of vision points for this phase"
    )
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['phase_number']
        
    def __str__(self):
        return f"Phase {self.phase_number}: {self.name}"
    
    @property
    def total_raised(self):
        """Calculate total raised in this phase"""
        from django.db.models import Sum
        result = self.purchases.filter(
            status='completed'
        ).aggregate(
            total=Sum('cusd_amount')
        )
        return result['total'] or Decimal('0')
    
    @property
    def total_participants(self):
        """Count unique participants in this phase"""
        return self.purchases.filter(
            status='completed'
        ).values('user').distinct().count()
    
    @property
    def tokens_sold(self):
        """Calculate total tokens sold in this phase"""
        from django.db.models import Sum
        result = self.purchases.filter(
            status='completed'
        ).aggregate(
            total=Sum('confio_amount')
        )
        return result['total'] or Decimal('0')
    
    @property
    def progress_percentage(self):
        """Calculate progress towards goal"""
        if self.goal_amount > 0:
            return min((self.total_raised / self.goal_amount) * 100, 100)
        return 0


class PresalePurchase(models.Model):
    """Records individual presale purchases"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    
    user = models.ForeignKey(
        User, 
        on_delete=models.PROTECT,
        related_name='presale_purchases'
    )
    phase = models.ForeignKey(
        PresalePhase,
        on_delete=models.PROTECT,
        related_name='purchases'
    )
    cusd_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    confio_amount = models.DecimalField(
        max_digits=15, 
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))]
    )
    price_per_token = models.DecimalField(
        max_digits=10, 
        decimal_places=4,
        help_text="Price at time of purchase"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    transaction_hash = models.CharField(
        max_length=256,
        null=True,
        blank=True,
        help_text="Blockchain transaction hash"
    )
    from_address = models.CharField(
        max_length=256,
        null=True,
        blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'phase']),
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
        ]
        
    def __str__(self):
        return f"{self.user.username} - {self.cusd_amount} cUSD for {self.confio_amount} CONFIO"
    
    def complete_purchase(self, transaction_hash):
        """Mark purchase as completed"""
        self.status = 'completed'
        self.transaction_hash = transaction_hash
        self.completed_at = timezone.now()
        self.save()


class PresaleStats(models.Model):
    """Aggregate stats for presale (updated periodically)"""
    phase = models.OneToOneField(
        PresalePhase,
        on_delete=models.CASCADE,
        related_name='stats'
    )
    total_raised = models.DecimalField(
        max_digits=15, 
        decimal_places=2,
        default=Decimal('0')
    )
    total_participants = models.IntegerField(default=0)
    total_tokens_sold = models.DecimalField(
        max_digits=20, 
        decimal_places=6,
        default=Decimal('0')
    )
    average_purchase = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('0')
    )
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Presale stats"
        
    def __str__(self):
        return f"Stats for {self.phase}"
    
    def update_stats(self):
        """Recalculate all stats"""
        from django.db.models import Sum, Avg, Count
        
        completed_purchases = self.phase.purchases.filter(status='completed')
        
        aggregates = completed_purchases.aggregate(
            total_cusd=Sum('cusd_amount'),
            total_confio=Sum('confio_amount'),
            avg_purchase=Avg('cusd_amount'),
            participant_count=Count('user', distinct=True)
        )
        
        self.total_raised = aggregates['total_cusd'] or Decimal('0')
        self.total_tokens_sold = aggregates['total_confio'] or Decimal('0')
        self.average_purchase = aggregates['avg_purchase'] or Decimal('0')
        self.total_participants = aggregates['participant_count'] or 0
        
        self.save()


class UserPresaleLimit(models.Model):
    """Track user's total purchases per phase for limit enforcement"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    phase = models.ForeignKey(PresalePhase, on_delete=models.CASCADE)
    total_purchased = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('0')
    )
    last_purchase_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['user', 'phase']
        
    def __str__(self):
        return f"{self.user.username} - Phase {self.phase.phase_number}: {self.total_purchased} cUSD"