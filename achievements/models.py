from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from decimal import Decimal
import json
import logging

from users.models import SoftDeleteModel

logger = logging.getLogger(__name__)


class AchievementType(SoftDeleteModel):
    """Defines types of achievements that users can earn"""
    
    CATEGORY_CHOICES = [
        ('onboarding', 'Bienvenida'),
        ('trading', 'Intercambios'),
        ('payments', 'Pagos y Transacciones'),
        ('social', 'Comunidad'),
        ('verification', 'Verificación'),
        ('ambassador', 'Embajador'),
    ]
    
    # Basic achievement info
    slug = models.CharField(
        max_length=50,
        unique=True,
        blank=True,  # Allow blank for auto-generation
        help_text="Unique identifier for this achievement type (auto-generated from name if blank)"
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name for this achievement"
    )
    description = models.TextField(
        help_text="Description of what this achievement represents"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        help_text="Category this achievement belongs to"
    )
    
    # Visual elements
    icon_emoji = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Emoji icon for this achievement (e.g., 🏆, 🎉, 🔥)"
    )
    color = models.CharField(
        max_length=7,
        default='#FFD700',
        help_text="Hex color code for achievement badge"
    )
    
    # Requirements and rewards
    confio_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO tokens awarded for this achievement"
    )
    is_repeatable = models.BooleanField(
        default=False,
        help_text="Whether users can earn this achievement multiple times"
    )
    requires_manual_review = models.BooleanField(
        default=False,
        help_text="Whether this achievement requires manual admin approval"
    )
    
    # Activation and ordering
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this achievement is currently available to earn"
    )
    display_order = models.PositiveIntegerField(
        default=1000,
        help_text="Display order in achievement lists (lower numbers first)"
    )
    
    class Meta:
        ordering = ['category', 'display_order', 'name']
        verbose_name = "Achievement Type"
        verbose_name_plural = "Achievement Types"
    
    def __str__(self):
        emoji = f"{self.icon_emoji} " if self.icon_emoji else ""
        return f"{emoji}{self.name}"
    
    @property
    def reward_display(self):
        """Get formatted reward display"""
        if self.confio_reward > 0:
            return f"+{self.confio_reward} CONFIO"
        return "Sin recompensa"
    
    def save(self, *args, **kwargs):
        """Auto-generate slug from name if not provided"""
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            
            # Ensure unique slug
            while AchievementType.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            self.slug = slug
        
        super().save(*args, **kwargs)


class UserAchievement(SoftDeleteModel):
    """Tracks which achievements users have earned"""
    
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('earned', 'Ganado'),
        ('claimed', 'Reclamado'),
        ('expired', 'Expirado'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='achievements'
    )
    achievement_type = models.ForeignKey(
        AchievementType,
        on_delete=models.CASCADE,
        related_name='user_achievements'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Progress tracking
    progress_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON data tracking progress towards this achievement"
    )
    earned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the achievement was earned"
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the reward was claimed"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the achievement expires (if applicable)"
    )
    
    # Value tracking for variable rewards
    earned_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual value earned (for variable rewards)"
    )
    
    class Meta:
        unique_together = [('user', 'achievement_type', 'deleted_at')]
        ordering = ['-earned_at', '-created_at']
        verbose_name = "User Achievement"
        verbose_name_plural = "User Achievements"
    
    def __str__(self):
        status = dict(self.STATUS_CHOICES).get(self.status, self.status)
        return f"{self.user.username} - {self.achievement_type.name} ({status})"
    
    def claim_reward(self):
        """Claim the reward for this achievement"""
        if self.status != 'earned':
            raise ValidationError("Solo se pueden reclamar logros ganados")
        
        if self.claimed_at:
            raise ValidationError("Este logro ya fue reclamado")
        
        # Update status
        self.status = 'claimed'
        self.claimed_at = timezone.now()
        
        # Award CONFIO
        reward_amount = self.earned_value or self.achievement_type.confio_reward
        if reward_amount > 0:
            # Create reward transaction
            balance, created = ConfioRewardBalance.objects.get_or_create(
                user=self.user,
                defaults={'total_earned': 0, 'total_locked': 0}
            )
            
            # Update balance
            balance.total_earned = F('total_earned') + reward_amount
            balance.total_locked = F('total_locked') + reward_amount
            balance.save()
            
            # Create transaction record
            ConfioRewardTransaction.objects.create(
                user=self.user,
                transaction_type='earned',
                amount=reward_amount,
                balance_after=balance.total_locked + reward_amount,
                reference_type='achievement',
                reference_id=str(self.id),
                description=f"Recompensa por {self.achievement_type.name}"
            )
        
        self.save()
        return reward_amount


class InfluencerReferral(SoftDeleteModel):
    """Tracks TikTok influencer referrals"""
    
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('active', 'Activo'),
        ('converted', 'Convertido'),
        ('failed', 'Fallido'),
    ]
    
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='influencer_referral'
    )
    referrer_identifier = models.CharField(
        max_length=100,
        db_index=True,
        help_text="TikTok username, phone, or code of referrer"
    )
    influencer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referred_users',
        help_text="User account of the influencer (if they have one)"
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Transaction tracking
    first_transaction_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When referred user completed first transaction"
    )
    total_transaction_volume = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total volume of transactions by referred user"
    )
    
    # Reward tracking
    referrer_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO awarded to referrer"
    )
    referee_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO awarded to referred user"
    )
    reward_claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When rewards were claimed"
    )
    
    # Additional data
    attribution_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional attribution data (source, campaign, etc.)"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Influencer Referral"
        verbose_name_plural = "Influencer Referrals"
        indexes = [
            models.Index(fields=['referrer_identifier', 'status']),
            models.Index(fields=['referred_user', 'status']),
        ]
    
    def __str__(self):
        return f"{self.referred_user.username} referred by {self.referrer_identifier}"
    
    @classmethod
    def get_influencer_stats(cls, referrer_identifier):
        """Get statistics for an influencer"""
        referrals = cls.objects.filter(
            referrer_identifier__iexact=referrer_identifier,
            deleted_at__isnull=True
        )
        
        return {
            'total_referrals': referrals.count(),
            'active_referrals': referrals.filter(status='active').count(),
            'converted_referrals': referrals.filter(status='converted').count(),
            'total_volume': referrals.aggregate(
                total=Sum('total_transaction_volume')
            )['total'] or Decimal('0'),
            'total_confio_earned': referrals.aggregate(
                total=Sum('referrer_confio_awarded')
            )['total'] or Decimal('0'),
        }
    
    @classmethod
    def check_ambassador_eligibility(cls, referrer_identifier):
        """Check if an influencer is eligible for ambassador status"""
        stats = cls.get_influencer_stats(referrer_identifier)
        
        # Requirements: 50+ referrals, 20+ active
        return (
            stats['total_referrals'] >= 50 and
            stats['active_referrals'] >= 20
        )


class TikTokViralShare(SoftDeleteModel):
    """Tracks TikTok videos shared for viral achievements"""
    
    STATUS_CHOICES = [
        ('pending_verification', 'Pendiente de Verificación'),
        ('verified', 'Verificado'),
        ('rejected', 'Rechazado'),
        ('rewarded', 'Recompensado'),
    ]
    
    SHARE_TYPE_CHOICES = [
        ('achievement', 'Logro'),
        ('tutorial', 'Tutorial'),
        ('testimonial', 'Testimonio'),
        ('creative', 'Creativo'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tiktok_shares'
    )
    achievement = models.ForeignKey(
        UserAchievement,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tiktok_shares',
        help_text="Achievement being shared (if applicable)"
    )
    
    # TikTok data
    tiktok_url = models.URLField(
        help_text="URL of the TikTok video"
    )
    tiktok_username = models.CharField(
        max_length=100,
        help_text="TikTok username of the sharer"
    )
    hashtags_used = models.JSONField(
        default=list,
        help_text="Hashtags used in the video"
    )
    share_type = models.CharField(
        max_length=20,
        choices=SHARE_TYPE_CHOICES,
        default='achievement'
    )
    
    # Verification status
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='pending_verification'
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_shares',
        help_text="Admin who verified this share"
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True
    )
    verification_notes = models.TextField(
        blank=True,
        help_text="Notes from verification process"
    )
    
    # Performance metrics
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of views on TikTok"
    )
    like_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of likes on TikTok"
    )
    share_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of shares on TikTok"
    )
    
    # Reward calculation
    base_confio_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Base CONFIO reward for this share"
    )
    view_bonus_confio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Additional CONFIO based on view count"
    )
    total_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO awarded for this share"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "TikTok Viral Share"
        verbose_name_plural = "TikTok Viral Shares"
    
    def __str__(self):
        return f"{self.user.username} - {self.share_type} ({self.status})"
    
    @property
    def has_required_hashtags(self):
        """Check if video has required hashtags"""
        required = ['#Confio', '#RetoConfio', '#LogroConfio']
        return all(tag in self.hashtags_used for tag in required)
    
    @property
    def performance_tier(self):
        """Get performance tier based on views"""
        if self.view_count >= 1000000:
            return 'viral'
        elif self.view_count >= 100000:
            return 'hot'
        elif self.view_count >= 10000:
            return 'trending'
        elif self.view_count >= 1000:
            return 'growing'
        return 'new'
    
    def calculate_rewards(self):
        """Calculate rewards based on performance"""
        # Base reward
        base = Decimal('4.0')  # 4 CONFIO base
        
        # View-based multipliers
        if self.view_count >= 1000000:
            multiplier = Decimal('62.5')  # 250 CONFIO total
        elif self.view_count >= 100000:
            multiplier = Decimal('20.0')  # 80 CONFIO total
        elif self.view_count >= 10000:
            multiplier = Decimal('5.0')   # 20 CONFIO total
        elif self.view_count >= 1000:
            multiplier = Decimal('1.0')   # 4 CONFIO total
        else:
            multiplier = Decimal('0.25')  # 1 CONFIO for trying
        
        self.base_confio_reward = base
        self.view_bonus_confio = base * (multiplier - 1) if multiplier > 1 else 0
        self.total_confio_awarded = base * multiplier
        
        return self.total_confio_awarded


class ConfioRewardBalance(SoftDeleteModel):
    """Tracks user's CONFIO reward balance"""
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='confio_balance'
    )
    
    # Balance tracking
    total_earned = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO ever earned"
    )
    total_locked = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Currently locked CONFIO"
    )
    total_unlocked = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Unlocked CONFIO (available for use)"
    )
    total_spent = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO spent or transferred"
    )
    
    # Unlock tracking
    next_unlock_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Next scheduled unlock date"
    )
    next_unlock_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount to unlock on next date"
    )
    
    class Meta:
        verbose_name = "CONFIO Balance"
        verbose_name_plural = "CONFIO Balances"
    
    def __str__(self):
        return f"{self.user.username}: {self.total_locked} locked / {self.total_unlocked} available"
    
    @property
    def available_balance(self):
        """Get current available balance"""
        return self.total_unlocked - self.total_spent


class ConfioRewardTransaction(SoftDeleteModel):
    """Individual CONFIO reward transactions"""
    
    TRANSACTION_TYPE_CHOICES = [
        ('earned', 'Ganado'),
        ('unlocked', 'Desbloqueado'),
        ('spent', 'Gastado'),
        ('transferred', 'Transferido'),
        ('adjusted', 'Ajustado'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='confio_transactions'
    )
    
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPE_CHOICES
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount of CONFIO in this transaction"
    )
    balance_after = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        help_text="Balance after this transaction"
    )
    
    # Reference to source
    reference_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="Type of reference (achievement, referral, viral, etc.)"
    )
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="ID of the referenced object"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Description of this transaction"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "CONFIO Transaction"
        verbose_name_plural = "CONFIO Transactions"
    
    def __str__(self):
        return f"{self.user.username} - {self.transaction_type}: {self.amount} CONFIO"


class InfluencerAmbassador(SoftDeleteModel):
    """Tracks top influencers who become brand ambassadors"""
    
    TIER_CHOICES = [
        ('bronze', 'Bronce'),
        ('silver', 'Plata'),
        ('gold', 'Oro'),
        ('diamond', 'Diamante'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Activo'),
        ('paused', 'Pausado'),
        ('terminated', 'Terminado'),
    ]
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ambassador_profile'
    )
    referrer_identifier = models.CharField(
        max_length=100,
        unique=True,
        help_text="Primary identifier used for referrals"
    )
    
    # Ambassador status
    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default='bronze'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    
    # Performance metrics
    total_referrals = models.PositiveIntegerField(
        default=0,
        help_text="Total number of referrals"
    )
    active_referrals = models.PositiveIntegerField(
        default=0,
        help_text="Number of active referred users"
    )
    total_viral_views = models.PositiveBigIntegerField(
        default=0,
        help_text="Total views across all viral content"
    )
    monthly_viral_views = models.PositiveBigIntegerField(
        default=0,
        help_text="Views in current month"
    )
    referral_transaction_volume = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total transaction volume from referrals"
    )
    confio_earned = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO earned as ambassador"
    )
    
    # Tier progression
    tier_achieved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When current tier was achieved"
    )
    tier_progress = models.JSONField(
        default=dict,
        help_text="Progress towards next tier"
    )
    
    # Special perks
    custom_referral_code = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="Custom referral code (gold+ tier)"
    )
    referral_bonus_multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1.0,
        help_text="Multiplier for referral rewards"
    )
    viral_bonus_multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1.0,
        help_text="Multiplier for viral content rewards"
    )
    
    # Management
    assigned_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_ambassadors',
        help_text="Confío team member managing this ambassador"
    )
    performance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Overall performance score (0-100)"
    )
    last_activity_at = models.DateTimeField(
        default=timezone.now,
        help_text="Last referral or viral activity"
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this ambassador"
    )
    
    # Perk flags
    has_early_access = models.BooleanField(
        default=False,
        help_text="Access to beta features"
    )
    has_exclusive_events = models.BooleanField(
        default=False,
        help_text="Invited to exclusive events"
    )
    has_monthly_bonus = models.BooleanField(
        default=False,
        help_text="Eligible for monthly performance bonus"
    )
    dedicatedSupport = models.BooleanField(
        default=False,
        help_text="Has dedicated support contact"
    )
    
    class Meta:
        ordering = ['-performance_score', '-total_referrals']
        verbose_name = "Influencer Ambassador"
        verbose_name_plural = "Influencer Ambassadors"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_tier_display()} Ambassador"
    
    @property
    def tier_display(self):
        """Get tier with emoji"""
        tier_emojis = {
            'bronze': '🥉',
            'silver': '🥈',
            'gold': '🥇',
            'diamond': '💎',
        }
        return f"{tier_emojis.get(self.tier, '')} {self.get_tier_display()}"
    
    @property
    def status_display(self):
        """Get status with color indicator"""
        status_colors = {
            'active': '🟢',
            'paused': '🟡',
            'terminated': '🔴',
        }
        return f"{status_colors.get(self.status, '')} {self.get_status_display()}"
    
    def calculate_performance_score(self):
        """Calculate performance score based on various metrics"""
        # Base scores
        referral_score = min(self.active_referrals / 100 * 30, 30)  # Max 30 points
        volume_score = min(float(self.referral_transaction_volume) / 10000 * 20, 20)  # Max 20 points
        viral_score = min(self.monthly_viral_views / 100000 * 20, 20)  # Max 20 points
        consistency_score = 30  # Based on regular activity
        
        # Check last activity
        days_inactive = (timezone.now() - self.last_activity_at).days
        if days_inactive > 30:
            consistency_score = max(0, consistency_score - days_inactive + 30)
        
        self.performance_score = referral_score + volume_score + viral_score + consistency_score
        return self.performance_score
    
    def check_tier_upgrade(self):
        """Check if eligible for tier upgrade"""
        tier_requirements = {
            'bronze': {'referrals': 0, 'active': 0, 'volume': 0},
            'silver': {'referrals': 50, 'active': 20, 'volume': 1000},
            'gold': {'referrals': 200, 'active': 100, 'volume': 10000},
            'diamond': {'referrals': 1000, 'active': 500, 'volume': 100000},
        }
        
        current_tier_index = [t[0] for t in self.TIER_CHOICES].index(self.tier)
        
        for i in range(current_tier_index + 1, len(self.TIER_CHOICES)):
            next_tier = self.TIER_CHOICES[i][0]
            requirements = tier_requirements[next_tier]
            
            if (self.total_referrals >= requirements['referrals'] and
                self.active_referrals >= requirements['active'] and
                self.referral_transaction_volume >= requirements['volume']):
                
                self.tier = next_tier
                self.tier_achieved_at = timezone.now()
                self.update_tier_perks()
                return True
        
        return False
    
    def update_tier_perks(self):
        """Update perks based on current tier"""
        tier_perks = {
            'bronze': {
                'referral_bonus': 1.0,
                'viral_bonus': 1.0,
                'early_access': False,
                'exclusive_events': False,
                'monthly_bonus': False,
                'dedicated_support': False,
            },
            'silver': {
                'referral_bonus': 1.25,
                'viral_bonus': 1.25,
                'early_access': True,
                'exclusive_events': False,
                'monthly_bonus': False,
                'dedicated_support': False,
            },
            'gold': {
                'referral_bonus': 1.5,
                'viral_bonus': 1.5,
                'early_access': True,
                'exclusive_events': True,
                'monthly_bonus': True,
                'dedicated_support': False,
            },
            'diamond': {
                'referral_bonus': 2.0,
                'viral_bonus': 2.0,
                'early_access': True,
                'exclusive_events': True,
                'monthly_bonus': True,
                'dedicated_support': True,
            },
        }
        
        perks = tier_perks.get(self.tier, tier_perks['bronze'])
        
        self.referral_bonus_multiplier = perks['referral_bonus']
        self.viral_bonus_multiplier = perks['viral_bonus']
        self.has_early_access = perks['early_access']
        self.has_exclusive_events = perks['exclusive_events']
        self.has_monthly_bonus = perks['monthly_bonus']
        self.dedicatedSupport = perks['dedicated_support']
    
    @property
    def benefits(self):
        """Get current tier benefits as a dictionary"""
        return {
            'referralBonus': f"{int((self.referral_bonus_multiplier - 1) * 100)}%" if self.referral_bonus_multiplier > 1 else None,
            'viralRate': f"{int((self.viral_bonus_multiplier - 1) * 100)}%" if self.viral_bonus_multiplier > 1 else None,
            'customCode': bool(self.custom_referral_code),
            'dedicatedSupport': self.dedicatedSupport,
            'monthlyBonus': self.has_monthly_bonus,
            'exclusiveEvents': self.has_exclusive_events,
            'earlyFeatures': self.has_early_access,
        }


class AmbassadorActivity(SoftDeleteModel):
    """Log of ambassador activities and milestones"""
    
    ACTIVITY_TYPE_CHOICES = [
        ('referral', 'Nueva Referencia'),
        ('viral_content', 'Contenido Viral'),
        ('tier_upgrade', 'Mejora de Nivel'),
        ('milestone', 'Hito Alcanzado'),
        ('bonus_earned', 'Bono Ganado'),
    ]
    
    ambassador = models.ForeignKey(
        InfluencerAmbassador,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    activity_type = models.CharField(
        max_length=20,
        choices=ACTIVITY_TYPE_CHOICES
    )
    description = models.TextField()
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional activity data"
    )
    confio_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO earned from this activity"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Ambassador Activity"
        verbose_name_plural = "Ambassador Activities"
    
    def __str__(self):
        return f"{self.ambassador.user.username} - {self.get_activity_type_display()}"


class SuspiciousActivity(SoftDeleteModel):
    """Track suspicious patterns in achievement/referral system"""
    
    ACTIVITY_TYPE_CHOICES = [
        ('rapid_referrals', 'Referidos Rápidos'),
        ('duplicate_device', 'Dispositivo Duplicado'),
        ('unusual_pattern', 'Patrón Inusual'),
        ('fake_viral', 'Viral Falso'),
        ('account_farming', 'Farming de Cuentas'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('investigating', 'Investigando'),
        ('confirmed', 'Confirmado'),
        ('dismissed', 'Descartado'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='achievement_suspicious_activities'  # Changed to avoid conflict
    )
    activity_type = models.CharField(
        max_length=20,
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
        related_name='investigated_achievement_activities'  # Changed to avoid conflict
    )
    investigation_notes = models.TextField(
        blank=True
    )
    action_taken = models.TextField(
        blank=True,
        help_text="What action was taken"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Suspicious Activity"
        verbose_name_plural = "Suspicious Activities"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_activity_type_display()} ({self.status})"


class PioneroBetaTracker(models.Model):
    """
    Singleton model to track Pionero Beta achievement distribution
    Ensures accurate counting of the first 10,000 users
    """
    count = models.IntegerField(default=0)
    last_user_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Pionero Beta Tracker"
        verbose_name_plural = "Pionero Beta Tracker"
    
    def save(self, *args, **kwargs):
        """Ensure only one instance exists"""
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def increment_and_check(cls):
        """
        Atomically increment counter and check if under 10,000
        Returns (success, current_count)
        """
        from django.db import transaction
        
        with transaction.atomic():
            tracker, created = cls.objects.select_for_update().get_or_create(pk=1)
            if tracker.count >= 10000:
                return False, tracker.count
            
            tracker.count += 1
            tracker.save()
            return True, tracker.count
    
    @classmethod
    def get_count(cls):
        """Get current count"""
        tracker, created = cls.objects.get_or_create(pk=1)
        return tracker.count
    
    def get_remaining_slots(self):
        """Get remaining slots available"""
        return max(0, 10000 - self.count)
    
    def __str__(self):
        return f"Pionero Beta: {self.count}/10,000 usuarios"