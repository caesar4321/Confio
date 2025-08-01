"""
Consolidated models for the achievements app
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from decimal import Decimal
from users.models import SoftDeleteModel


class AchievementType(SoftDeleteModel):
    """Types of achievements that users can earn"""
    
    CATEGORY_CHOICES = [
        ('onboarding', 'Onboarding'),
        ('trading', 'Trading'),
        ('payments', 'Payments'),
        ('social', 'Social'),
        ('verification', 'Verification'),
        ('ambassador', 'Ambassador'),
    ]
    
    slug = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique identifier for this achievement type"
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name for this achievement"
    )
    description = models.TextField(
        help_text="Description of what the user needs to do"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        help_text="Category this achievement belongs to"
    )
    icon_emoji = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Emoji icon for this achievement"
    )
    color = models.CharField(
        max_length=20,
        default='#FFD700',
        help_text="Color for this achievement (hex code)"
    )
    confio_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount of CONFIO tokens to reward"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order to display this achievement"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this achievement is currently active"
    )
    is_repeatable = models.BooleanField(
        default=False,
        help_text="Whether users can earn this achievement multiple times"
    )
    requires_manual_review = models.BooleanField(
        default=False,
        help_text="Whether this achievement requires manual admin review"
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
    
    # Fraud prevention fields
    device_fingerprint_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Hash of device fingerprint when achievement was earned"
    )
    claim_ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address when achievement was earned"
    )
    security_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional security metadata for fraud detection"
    )
    
    class Meta:
        unique_together = [('user', 'achievement_type', 'deleted_at')]
        ordering = ['-earned_at', '-created_at']
        verbose_name = "User Achievement"
        verbose_name_plural = "User Achievements"
    
    def __str__(self):
        status = dict(self.STATUS_CHOICES).get(self.status, self.status)
        return f"{self.user.username} - {self.achievement_type.name} ({status})"
    
    @property
    def can_claim_reward(self):
        """Check if the reward for this achievement can be claimed"""
        return (
            self.status == 'earned' and 
            self.claimed_at is None and
            self.achievement_type.confio_reward > 0
        )
    
    @property
    def reward_amount(self):
        """Get the reward amount for this achievement"""
        return self.earned_value or self.achievement_type.confio_reward
    
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
            
            # Calculate new balance for transaction record
            new_total_locked = balance.total_locked + reward_amount
            
            # Update balance and tracking
            balance.total_earned = F('total_earned') + reward_amount
            balance.total_locked = F('total_locked') + reward_amount
            balance.last_reward_at = timezone.now()
            balance.daily_reward_count = F('daily_reward_count') + 1
            balance.daily_reward_amount = F('daily_reward_amount') + reward_amount
            balance.save()
            
            # Create transaction record
            ConfioRewardTransaction.objects.create(
                user=self.user,
                transaction_type='earned',
                amount=reward_amount,
                balance_after=new_total_locked,
                reference_type='achievement',
                reference_id=str(self.id),
                description=f"Recompensa por {self.achievement_type.name}"
            )
        
        self.save()
        return reward_amount


class InfluencerReferral(SoftDeleteModel):
    """Tracks referrals made by influencers"""
    
    STATUS_CHOICES = [
        ('active', 'Activo'),
        ('converted', 'Convertido'),
        ('inactive', 'Inactivo'),
    ]
    
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referrals_as_referred'
    )
    referrer_identifier = models.CharField(
        max_length=50,
        help_text="Identifier of the referrer (@username, code, etc.)"
    )
    influencer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals_as_influencer',
        help_text="Actual user who made the referral (if registered)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    first_transaction_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the referred user made their first transaction"
    )
    total_transaction_volume = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total volume of transactions by this user"
    )
    referrer_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO awarded to the referrer"
    )
    referee_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO awarded to the referred user"
    )
    reward_claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the referral reward was claimed"
    )
    attribution_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional attribution data"
    )
    
    class Meta:
        unique_together = [('referred_user', 'deleted_at')]
        ordering = ['-created_at']
        verbose_name = "Influencer Referral"
        verbose_name_plural = "Influencer Referrals"
    
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
            'is_ambassador_eligible': cls.check_ambassador_eligibility(referrer_identifier)
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
        max_length=50,
        help_text="TikTok username of the creator"
    )
    hashtags_used = models.JSONField(
        default=list,
        help_text="List of hashtags used in the video"
    )
    share_type = models.CharField(
        max_length=20,
        choices=SHARE_TYPE_CHOICES,
        default='achievement'
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='pending_verification'
    )
    
    # Performance metrics
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of views on the TikTok video"
    )
    like_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of likes on the TikTok video"
    )
    share_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of shares of the TikTok video"
    )
    
    # Rewards
    base_confio_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10,
        help_text="Base CONFIO reward for sharing"
    )
    view_bonus_confio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Bonus CONFIO based on view performance"
    )
    total_confio_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO awarded for this share"
    )
    
    # Admin fields
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_tiktok_shares'
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True
    )
    verification_notes = models.TextField(
        blank=True,
        help_text="Admin notes about verification"
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
    
    def calculate_bonus_confio(self):
        """Calculate bonus CONFIO based on performance"""
        base = self.base_confio_reward
        
        # View-based multiplier
        if self.view_count >= 1000000:
            multiplier = 10.0  # 10x for viral (1M+ views)
        elif self.view_count >= 100000:
            multiplier = 5.0   # 5x for hot (100K+ views)
        elif self.view_count >= 10000:
            multiplier = 2.0   # 2x for trending (10K+ views)
        elif self.view_count >= 1000:
            multiplier = 1.5   # 1.5x for growing (1K+ views)
        else:
            multiplier = 1.0   # Base reward
        
        self.view_bonus_confio = base * (multiplier - 1)
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
    
    # Rate limiting and tracking
    last_reward_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time user received a reward"
    )
    daily_reward_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of rewards claimed today"
    )
    daily_reward_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO claimed today"
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
        help_text="User's total balance after this transaction"
    )
    
    # Reference to what caused this transaction
    reference_type = models.CharField(
        max_length=50,
        help_text="Type of action that caused this transaction"
    )
    reference_id = models.CharField(
        max_length=50,
        help_text="ID of the record that caused this transaction"
    )
    description = models.TextField(
        help_text="Human-readable description of this transaction"
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
        help_text="Total number of referrals made"
    )
    active_referrals = models.PositiveIntegerField(
        default=0,
        help_text="Number of currently active referrals"
    )
    total_viral_views = models.PositiveBigIntegerField(
        default=0,
        help_text="Total views across all viral content"
    )
    monthly_viral_views = models.PositiveIntegerField(
        default=0,
        help_text="Viral views in the current month"
    )
    referral_transaction_volume = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total transaction volume from referrals"
    )
    confio_earned = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        help_text="Total CONFIO earned as ambassador"
    )
    
    # Benefits and bonuses
    referral_bonus_multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1.0,
        help_text="Multiplier for referral rewards (e.g., 1.5 = 50% bonus)"
    )
    viral_bonus_multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1.0,
        help_text="Multiplier for viral content rewards"
    )
    custom_referral_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        help_text="Custom referral code for this ambassador"
    )
    
    # Tier progression
    tier_achieved_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        help_text="When the current tier was achieved"
    )
    performance_score = models.PositiveIntegerField(
        default=0,
        help_text="Overall performance score (0-100)"
    )
    
    # Benefits flags
    has_early_access = models.BooleanField(
        default=False,
        help_text="Has early access to new features"
    )
    has_exclusive_events = models.BooleanField(
        default=False,
        help_text="Has access to exclusive events"
    )
    has_monthly_bonus = models.BooleanField(
        default=False,
        help_text="Receives monthly performance bonus"
    )
    dedicatedSupport = models.BooleanField(
        default=False,
        help_text="Has access to dedicated support"
    )
    
    # Activity tracking
    last_activity_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time ambassador was active"
    )
    
    class Meta:
        ordering = ['-confio_earned', '-total_referrals']
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
        """Calculate overall performance score (0-100)"""
        score = 0
        
        # Referral component (40%)
        if self.total_referrals >= 1000:
            score += 40
        elif self.total_referrals >= 500:
            score += 30
        elif self.total_referrals >= 100:
            score += 20
        elif self.total_referrals >= 50:
            score += 10
        
        # Viral component (40%)
        if self.total_viral_views >= 10000000:  # 10M+
            score += 40
        elif self.total_viral_views >= 5000000:  # 5M+
            score += 30
        elif self.total_viral_views >= 1000000:  # 1M+
            score += 20
        elif self.total_viral_views >= 100000:  # 100K+
            score += 10
        
        # Volume component (20%)
        volume_usd = float(self.referral_transaction_volume)
        if volume_usd >= 1000000:  # $1M+
            score += 20
        elif volume_usd >= 500000:  # $500K+
            score += 15
        elif volume_usd >= 100000:  # $100K+
            score += 10
        elif volume_usd >= 50000:   # $50K+
            score += 5
        
        self.performance_score = min(score, 100)
        return self.performance_score
    
    def calculate_tier_progress(self):
        """Calculate progress towards next tier (0-100)"""
        current_tier_index = [choice[0] for choice in self.TIER_CHOICES].index(self.tier)
        
        if current_tier_index == len(self.TIER_CHOICES) - 1:
            return 100  # Already at highest tier
        
        # Simplified tier progression based on performance score
        if self.performance_score >= 90:
            return 100
        elif self.performance_score >= 75:
            return 80
        elif self.performance_score >= 50:
            return 60
        elif self.performance_score >= 25:
            return 40
        else:
            return 20
    
    def update_tier_benefits(self):
        """Update benefits based on current tier"""
        tier_benefits = {
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
            }
        }
        
        perks = tier_benefits.get(self.tier, tier_benefits['bronze'])
        
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
    """Track ambassador activity and performance"""
    
    ACTIVITY_TYPE_CHOICES = [
        ('referral', 'Referido'),
        ('viral_content', 'Contenido Viral'),
        ('community_engagement', 'Participación Comunitaria'),
        ('event_participation', 'Participación en Eventos'),
        ('milestone_achieved', 'Hito Alcanzado'),
    ]
    
    ambassador = models.ForeignKey(
        InfluencerAmbassador,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ACTIVITY_TYPE_CHOICES
    )
    description = models.TextField()
    points_earned = models.PositiveIntegerField(
        default=0,
        help_text="Points earned for this activity"
    )
    confio_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="CONFIO earned for this activity"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional activity metadata"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Ambassador Activity"
        verbose_name_plural = "Ambassador Activities"
    
    def __str__(self):
        return f"{self.ambassador.user.username} - {self.get_activity_type_display()}"


class ConfioGrowthMetric(models.Model):
    """Stores growth metrics for the CONFIO token info screen"""
    
    METRIC_TYPE_CHOICES = [
        ('active_users', 'Usuarios Activos'),
        ('protected_savings', 'Ahorros Protegidos'),
        ('daily_transactions', 'Transacciones Diarias'),
        ('monthly_volume', 'Volumen Mensual'),
        ('venezuelan_states', 'Estados de Venezuela'),
    ]
    
    metric_type = models.CharField(
        max_length=30,
        choices=METRIC_TYPE_CHOICES,
        unique=True,
        help_text="Type of metric being tracked"
    )
    display_name = models.CharField(
        max_length=100,
        help_text="Display name for this metric"
    )
    current_value = models.CharField(
        max_length=50,
        help_text="Current value (e.g., '8K+', '$1.2M cUSD')"
    )
    growth_percentage = models.CharField(
        max_length=20,
        help_text="Growth percentage (e.g., '+25%')"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order to display this metric"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether to show this metric in the app"
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        help_text="When this metric was last updated"
    )
    
    class Meta:
        ordering = ['display_order', 'metric_type']
        verbose_name = "CONFIO Growth Metric"
        verbose_name_plural = "CONFIO Growth Metrics"
    
    def __str__(self):
        return f"{self.display_name}: {self.current_value} ({self.growth_percentage})"


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
    def get_instance(cls):
        """Get the singleton instance"""
        instance, created = cls.objects.get_or_create(pk=1)
        return instance
    
    @classmethod
    def increment_and_check(cls):
        """Atomically increment counter and check if award is allowed"""
        from django.db import transaction
        
        with transaction.atomic():
            tracker, created = cls.objects.select_for_update().get_or_create(pk=1)
            
            if tracker.count >= 10000:
                return False, tracker.count
            
            tracker.count += 1
            tracker.save(update_fields=['count', 'updated_at'])
            
            return True, tracker.count
    
    @property
    def remaining_spots(self):
        """Get remaining spots for Pionero Beta"""
        return max(0, 10000 - self.count)
    
    def get_remaining_slots(self):
        """Get remaining slots for Pionero Beta (alias for remaining_spots)"""
        return self.remaining_spots
    
    def __str__(self):
        return f"Pionero Beta: {self.count}/10,000 usuarios"