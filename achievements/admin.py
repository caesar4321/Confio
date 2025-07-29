from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Sum, Q

from .models import (
    AchievementType, UserAchievement, InfluencerReferral, 
    TikTokViralShare, ConfioRewardBalance, ConfioRewardTransaction,
    InfluencerAmbassador, AmbassadorActivity, SuspiciousActivity,
    PioneroBetaTracker
)


@admin.register(AchievementType)
class AchievementTypeAdmin(admin.ModelAdmin):
    """Admin for achievement types"""
    list_display = ('emoji_name', 'slug', 'category_display', 'confio_reward_display', 'users_earned', 'is_active', 'display_order')
    list_filter = ('category', 'is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('slug', 'created_at', 'updated_at', 'users_earned', 'total_earned_display', 'total_claimed_display')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'category', 'icon_emoji', 'color')
        }),
        ('Rewards & Requirements', {
            'fields': ('confio_reward', 'is_repeatable', 'requires_manual_review')
        }),
        ('Status & Display', {
            'fields': ('is_active', 'display_order')
        }),
        ('Statistics', {
            'fields': ('users_earned', 'total_earned_display', 'total_claimed_display'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def emoji_name(self, obj):
        emoji = obj.icon_emoji or '🏆'
        # Special emoji for Pionero Beta
        if obj.slug == 'pionero_beta':
            return format_html('{} <b>{}</b>', emoji, obj.name)
        return format_html('{} {}', emoji, obj.name)
    emoji_name.short_description = 'Achievement'
    emoji_name.admin_order_field = 'name'
    
    def users_earned(self, obj):
        count = obj.user_achievements.filter(status__in=['earned', 'claimed']).count()
        
        # Special handling for Pionero Beta
        if obj.slug == 'pionero_beta':
            tracker = PioneroBetaTracker.objects.first()
            if tracker:
                remaining = tracker.get_remaining_slots()
                if remaining > 0:
                    return format_html(
                        '<span style="color: #059669; font-weight: bold;">{}/{}</span>',
                        f"{count:,}", f"{10000:,}"
                    )
                else:
                    return format_html(
                        '<span style="color: #DC2626; font-weight: bold;">{}/{} (FULL)</span>',
                        f"{count:,}", f"{10000:,}"
                    )
        
        return format_html('<span>{}</span>', f"{count:,}")
    users_earned.short_description = 'Users Earned'
    
    def total_earned_display(self, obj):
        count = obj.user_achievements.filter(status__in=['earned', 'claimed']).count()
        total = count * obj.confio_reward
        return f"{count:,} users × {obj.confio_reward} = {total:,} CONFIO"
    total_earned_display.short_description = 'Total Earned'
    
    def total_claimed_display(self, obj):
        count = obj.user_achievements.filter(status='claimed').count()
        total = count * obj.confio_reward
        return f"{count:,} users × {obj.confio_reward} = {total:,} CONFIO"
    total_claimed_display.short_description = 'Total Claimed'
    
    def category_display(self, obj):
        categories = {
            'onboarding': '👋 Bienvenida',
            'trading': '💱 Intercambios',
            'payments': '💸 Pagos',
            'social': '👥 Comunidad',
            'verification': '✅ Verificación',
            'ambassador': '👑 Embajador',
            # Also support old category names
            'bienvenida': '👋 Bienvenida',
            'verificacion': '✅ Verificación',
            'viral': '🚀 Viral',
            'embajador': '👑 Embajador'
        }
        return categories.get(obj.category, obj.category)
    category_display.short_description = "Category"
    
    def confio_reward_display(self, obj):
        return format_html(
            '<strong>{} CONFIO</strong><br><small style="color: #6B7280;">${}</small>',
            obj.confio_reward,
            obj.confio_reward / 4  # 4 CONFIO = $1
        )
    confio_reward_display.short_description = "Reward"


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    """Admin for user achievements"""
    list_display = ('user_display', 'achievement_display', 'status_display', 'reward_display', 'earned_at', 'claimed_at')
    list_filter = ('status', 'earned_at', 'claimed_at', 'achievement_type__category', 'achievement_type__is_active')
    search_fields = ('user__username', 'user__email', 'achievement_type__name', 'achievement_type__slug')
    readonly_fields = ('earned_at', 'claimed_at', 'created_at', 'updated_at', 'reward_amount_display')
    raw_id_fields = ('user', 'achievement_type')
    date_hierarchy = 'earned_at'
    
    fieldsets = (
        ('User & Achievement', {
            'fields': ('user', 'achievement_type', 'status')
        }),
        ('Reward Information', {
            'fields': ('reward_amount_display',),
        }),
        ('Timestamps', {
            'fields': ('earned_at', 'claimed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def user_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:users_user_change', args=[obj.user.id]),
            obj.user.username
        )
    user_display.short_description = 'User'
    user_display.admin_order_field = 'user__username'
    
    def achievement_display(self, obj):
        emoji = obj.achievement_type.icon_emoji or '🏆'
        # Special formatting for Pionero Beta
        if obj.achievement_type.slug == 'pionero_beta':
            return format_html(
                '{} <b>{}</b> 🎁',
                emoji,
                obj.achievement_type.name
            )
        return format_html(
            '{} {}',
            emoji,
            obj.achievement_type.name
        )
    achievement_display.short_description = 'Achievement'
    achievement_display.admin_order_field = 'achievement_type__name'
    
    def reward_display(self, obj):
        return format_html(
            '<span style="color: #00BFA5; font-weight: bold;">{} CONFIO</span>',
            obj.achievement_type.confio_reward
        )
    reward_display.short_description = 'Reward'
    
    def reward_amount_display(self, obj):
        reward = obj.achievement_type.confio_reward
        usd_value = reward / 4  # 4 CONFIO = $1
        return f"{reward} CONFIO (${usd_value:.2f} USD)"
    reward_amount_display.short_description = 'Reward Value'
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#9CA3AF',
            'earned': '#F59E0B',
            'claimed': '#10B981',
            'expired': '#EF4444'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"
    
    def can_claim(self, obj):
        if obj.can_claim_reward:
            return format_html('<span style="color: #10B981;">✅ Yes</span>')
        return format_html('<span style="color: #9CA3AF;">❌ No</span>')
    can_claim.short_description = "Can Claim?"
    
    actions = ['mark_as_earned', 'mark_as_claimed']
    
    def mark_as_earned(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='earned',
            earned_at=timezone.now()
        )
        self.message_user(request, f"{updated} achievements marked as earned.")
    mark_as_earned.short_description = "Mark selected as earned"
    
    def mark_as_claimed(self, request, queryset):
        count = 0
        for achievement in queryset.filter(status='earned'):
            if achievement.claim_reward():
                count += 1
        self.message_user(request, f"{count} achievements claimed with rewards distributed.")
    mark_as_claimed.short_description = "Claim rewards for selected"


@admin.register(InfluencerReferral)
class InfluencerReferralAdmin(admin.ModelAdmin):
    """Admin for influencer referrals"""
    list_display = ('referrer_identifier', 'referred_user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('referred_user__username', 'referred_user__email', 'referrer_identifier')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('referred_user', 'influencer_user')
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#9CA3AF',
            'active': '#10B981',
            'converted': '#8B5CF6',
            'ambassador': '#F59E0B'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"


@admin.register(TikTokViralShare)
class TikTokViralShareAdmin(admin.ModelAdmin):
    """Admin for TikTok viral shares"""
    list_display = ('user', 'tiktok_username', 'share_type', 'status_display', 'created_at')
    list_filter = ('status', 'share_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'tiktok_username')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user', 'achievement', 'verified_by')
    
    def status_display(self, obj):
        status_colors = {
            'pending_verification': '#9CA3AF',
            'verified': '#10B981',
            'rejected': '#EF4444',
            'rewarded': '#8B5CF6'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            status_colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"


@admin.register(ConfioRewardBalance)
class ConfioRewardBalanceAdmin(admin.ModelAdmin):
    """Admin for CONFIO reward balances"""
    list_display = ('user', 'total_earned', 'total_locked', 'available_balance', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user',)


@admin.register(ConfioRewardTransaction)
class ConfioRewardTransactionAdmin(admin.ModelAdmin):
    """Admin for CONFIO reward transactions"""
    list_display = ('user', 'transaction_type', 'amount', 'balance_after', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'description')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user',)


@admin.register(InfluencerAmbassador)
class InfluencerAmbassadorAdmin(admin.ModelAdmin):
    """Admin for influencer ambassadors"""
    list_display = ('user', 'referrer_identifier', 'tier', 'status', 'total_referrals', 'performance_score')
    list_filter = ('tier', 'status', 'created_at')
    search_fields = ('user__username', 'user__email', 'referrer_identifier')
    readonly_fields = ('created_at', 'updated_at', 'tier_achieved_at', 'last_activity_at')
    raw_id_fields = ('user', 'assigned_manager')


@admin.register(AmbassadorActivity)
class AmbassadorActivityAdmin(admin.ModelAdmin):
    """Admin for ambassador activities"""
    list_display = ('ambassador', 'activity_type', 'confio_earned', 'created_at')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('ambassador__user__username', 'description')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('ambassador',)


@admin.register(SuspiciousActivity)
class SuspiciousActivityAdmin(admin.ModelAdmin):
    """Admin for suspicious activities"""
    list_display = ('user', 'activity_type', 'status', 'severity_score', 'created_at')
    list_filter = ('activity_type', 'status', 'severity_score', 'created_at')
    search_fields = ('user__username', 'user__email', 'investigation_notes')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user', 'investigated_by')


@admin.register(PioneroBetaTracker)
class PioneroBetaTrackerAdmin(admin.ModelAdmin):
    """Admin for Pionero Beta tracker (singleton)"""
    list_display = ("progress_display", "count_display", "remaining_display", "last_user_link", "updated_at")
    readonly_fields = ("count", "last_user_id", "updated_at", "remaining_slots", "progress_bar", "statistics")
    
    fieldsets = (
        ('🚀 Pionero Beta Progress', {
            'fields': ('progress_bar', 'statistics'),
            'description': 'Track the first 10,000 users receiving Pionero Beta achievement'
        }),
        ('Details', {
            'fields': ('count', 'remaining_slots', 'last_user_id', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def progress_display(self, obj):
        percentage = (obj.count / 10000) * 100
        color = '#10B981' if percentage < 80 else '#F59E0B' if percentage < 95 else '#DC2626'
        return format_html(
            '<div style="display: flex; align-items: center;">'
            '<div style="width: 200px; height: 20px; background: #e5e7eb; border-radius: 10px; overflow: hidden; margin-right: 10px;">'
            '<div style="width: {}%; height: 100%; background: {}; transition: width 0.3s;"></div>'
            '</div>'
            '<span style="font-weight: bold; color: {};">{:.1f}%</span>'
            '</div>',
            percentage, color, color, percentage
        )
    progress_display.short_description = "Progress"
    
    def count_display(self, obj):
        return format_html(
            '<span style="font-size: 18px; font-weight: bold;">{:,}</span>',
            obj.count
        )
    count_display.short_description = "Users Awarded"
    
    def remaining_display(self, obj):
        remaining = obj.get_remaining_slots()
        color = '#DC2626' if remaining < 100 else '#F59E0B' if remaining < 500 else '#10B981'
        return format_html(
            '<span style="font-size: 18px; font-weight: bold; color: {};">{:,}</span>',
            color, remaining
        )
    remaining_display.short_description = "Slots Remaining"
    
    def last_user_link(self, obj):
        if obj.last_user_id:
            from users.models import User
            try:
                user = User.objects.get(id=obj.last_user_id)
                return format_html(
                    '<a href="{}">{}</a>',
                    reverse('admin:users_user_change', args=[user.id]),
                    user.username
                )
            except User.DoesNotExist:
                return "User not found"
        return "No users yet"
    last_user_link.short_description = "Last User"
    
    def remaining_slots(self, obj):
        remaining = obj.get_remaining_slots()
        return f"{remaining:,} slots"
    remaining_slots.short_description = "Remaining Slots"
    
    def progress_bar(self, obj):
        percentage = (obj.count / 10000) * 100
        color = '#10B981' if percentage < 80 else '#F59E0B' if percentage < 95 else '#DC2626'
        
        return format_html(
            '<div style="margin: 20px 0;">'
            '<div style="display: flex; justify-content: space-between; margin-bottom: 10px;">'
            '<span style="font-size: 24px; font-weight: bold;">{:,} / 10,000</span>'
            '<span style="font-size: 24px; font-weight: bold; color: {};">{:.1f}%</span>'
            '</div>'
            '<div style="width: 100%; height: 40px; background: #e5e7eb; border-radius: 20px; overflow: hidden; position: relative;">'
            '<div style="width: {}%; height: 100%; background: {}; transition: width 0.3s;"></div>'
            '<div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #374151;">'
            '{:,} users registered'
            '</div>'
            '</div>'
            '</div>',
            obj.count, color, percentage,
            percentage, color,
            obj.count
        )
    progress_bar.short_description = "Progress"
    
    def statistics(self, obj):
        remaining = obj.get_remaining_slots()
        rate_per_day = 0
        days_to_full = "∞"
        
        # Calculate growth rate from User model
        from users.models import User
        from datetime import timedelta
        week_ago = timezone.now() - timedelta(days=7)
        recent_users = User.objects.filter(date_joined__gte=week_ago).count()
        if recent_users > 0:
            rate_per_day = recent_users / 7
            
            if rate_per_day > 0 and remaining > 0:
                # Calculate days to full based on target growth rate
                # Target: 100K users in 3 months = ~1,111 users per day
                if rate_per_day < 200:
                    # Interpolate between current rate and target rate based on progress
                    progress_factor = obj.count / 10000
                    target_rate = 200 + (progress_factor * 800)  # Accelerating to 1000/day
                    rate_per_day = max(rate_per_day, target_rate * 0.5)  # Conservative estimate
                
                days_to_full = int(remaining / rate_per_day)
        
        return format_html(
            '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0;">'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Current Rate</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #1f2937;">{:.0f}/day</div>'
            '</div>'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Est. Days to Full</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #1f2937;">{}</div>'
            '</div>'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Value Awarded</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #00BFA5;">{:,} CONFIO</div>'
            '</div>'
            '</div>',
            rate_per_day,
            f"{days_to_full}d" if isinstance(days_to_full, int) else days_to_full,
            obj.count  # 1 CONFIO per user
        )
    statistics.short_description = "Statistics"
    
    def has_add_permission(self, request):
        # Don't allow adding more trackers
        return PioneroBetaTracker.objects.count() == 0
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deleting the tracker
        return False
