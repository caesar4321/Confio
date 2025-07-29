from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, path
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.template.response import TemplateResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
import logging

from .models import (
    AchievementType, UserAchievement, InfluencerReferral, 
    TikTokViralShare, ConfioRewardBalance, ConfioRewardTransaction,
    InfluencerAmbassador, AmbassadorActivity,
    PioneroBetaTracker
)

logger = logging.getLogger(__name__)


class FraudStatusFilter(admin.SimpleListFilter):
    """Custom filter for fraud detection status"""
    title = 'Fraud Status'
    parameter_name = 'fraud_status'
    
    def lookups(self, request, model_admin):
        return (
            ('clean', 'Clean'),
            ('suspicious', 'Suspicious'),
            ('fraud', 'Confirmed Fraud'),
            ('multi_device', 'Multiple on Same Device'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'clean':
            # No fraud indicators
            return queryset.filter(
                Q(security_metadata={}) | Q(security_metadata__isnull=True)
            )
        elif self.value() == 'suspicious':
            # Has suspicious indicators but not confirmed fraud
            return queryset.filter(
                security_metadata__suspicious_ip=True
            ).exclude(
                security_metadata__fraud_detected__isnull=False
            )
        elif self.value() == 'fraud':
            # Confirmed fraud
            return queryset.filter(
                security_metadata__fraud_detected__isnull=False
            )
        elif self.value() == 'multi_device':
            # Find achievements where device has multiple users
            from django.db.models import Subquery, OuterRef
            
            # Get device hashes that appear for multiple users
            multi_device = UserAchievement.objects.filter(
                device_fingerprint_hash=OuterRef('device_fingerprint_hash')
            ).exclude(
                user=OuterRef('user')
            ).values('device_fingerprint_hash')[:1]
            
            return queryset.filter(
                device_fingerprint_hash__isnull=False
            ).filter(
                device_fingerprint_hash__in=Subquery(multi_device)
            )
        
        return queryset


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
    list_display = ('user_display', 'achievement_display', 'status_display', 'reward_display', 'fraud_indicator', 'earned_at', 'claimed_at')
    list_filter = ('status', FraudStatusFilter, 'earned_at', 'claimed_at', 'achievement_type__category', 'achievement_type__is_active')
    search_fields = ('user__username', 'user__email', 'achievement_type__name', 'achievement_type__slug', 'device_fingerprint_hash', 'claim_ip_address')
    readonly_fields = ('earned_at', 'claimed_at', 'created_at', 'updated_at', 'reward_amount_display', 'device_fingerprint_display', 'security_metadata_display')
    raw_id_fields = ('user', 'achievement_type')
    date_hierarchy = 'earned_at'
    
    def changelist_view(self, request, extra_context=None):
        """Add fraud statistics to the changelist view"""
        response = super().changelist_view(request, extra_context)
        
        try:
            # Get the filtered queryset
            qs = response.context_data['cl'].queryset
            
            # Calculate fraud statistics
            total_achievements = qs.count()
            fraud_detected = qs.filter(security_metadata__fraud_detected__isnull=False).count()
            suspicious_ips = qs.filter(security_metadata__suspicious_ip=True).count()
            
            # Count unique devices with multiple users
            device_counts = {}
            for achievement in qs.filter(device_fingerprint_hash__isnull=False):
                device_hash = achievement.device_fingerprint_hash
                if device_hash not in device_counts:
                    device_counts[device_hash] = set()
                device_counts[device_hash].add(achievement.user_id)
            
            multi_user_devices = sum(1 for users in device_counts.values() if len(users) > 1)
            
            # Add to context
            response.context_data.update({
                'fraud_stats': {
                    'total': total_achievements,
                    'fraud_detected': fraud_detected,
                    'fraud_percentage': (fraud_detected / total_achievements * 100) if total_achievements > 0 else 0,
                    'suspicious_ips': suspicious_ips,
                    'multi_user_devices': multi_user_devices,
                }
            })
        except (AttributeError, KeyError):
            pass
        
        return response
    
    def get_urls(self):
        """Add custom admin URLs"""
        urls = super().get_urls()
        custom_urls = [
            path('fraud-dashboard/', self.admin_site.admin_view(self.fraud_dashboard_view), name='achievements_userachievement_fraud_dashboard'),
        ]
        return custom_urls + urls
    
    @method_decorator(staff_member_required)
    def fraud_dashboard_view(self, request):
        """Comprehensive fraud detection dashboard"""
        from django.db.models import Count, Q, F
        from collections import defaultdict
        import json
        
        # Get all achievements with device fingerprints
        achievements = UserAchievement.objects.filter(
            device_fingerprint_hash__isnull=False
        ).select_related('user', 'achievement_type')
        
        # 1. Device Analysis
        device_stats = defaultdict(lambda: {'users': set(), 'achievements': [], 'total_confio': 0})
        
        for achievement in achievements:
            device_hash = achievement.device_fingerprint_hash
            device_stats[device_hash]['users'].add(achievement.user_id)
            device_stats[device_hash]['achievements'].append(achievement)
            if achievement.status == 'claimed':
                device_stats[device_hash]['total_confio'] += float(achievement.achievement_type.confio_reward)
        
        # Find suspicious devices (multiple users)
        suspicious_devices = []
        for device_hash, stats in device_stats.items():
            if len(stats['users']) > 1:
                suspicious_devices.append({
                    'device_hash': device_hash,
                    'device_hash_short': device_hash[:8] + '...',
                    'user_count': len(stats['users']),
                    'achievement_count': len(stats['achievements']),
                    'total_confio': stats['total_confio'],
                    'users': list(stats['users'])[:10],  # Limit to first 10 for display
                })
        
        suspicious_devices.sort(key=lambda x: x['user_count'], reverse=True)
        
        # 2. IP Analysis
        ip_stats = defaultdict(lambda: {'users': set(), 'achievements': 0})
        
        achievements_with_ip = UserAchievement.objects.filter(
            claim_ip_address__isnull=False
        )
        
        for achievement in achievements_with_ip:
            ip = achievement.claim_ip_address
            ip_stats[ip]['users'].add(achievement.user_id)
            ip_stats[ip]['achievements'] += 1
        
        # Find suspicious IPs
        suspicious_ips = []
        for ip, stats in ip_stats.items():
            if len(stats['users']) > 3:  # More than 3 users from same IP
                suspicious_ips.append({
                    'ip': ip,
                    'user_count': len(stats['users']),
                    'achievement_count': stats['achievements'],
                })
        
        suspicious_ips.sort(key=lambda x: x['user_count'], reverse=True)
        
        # 3. Recent Fraud Activity
        recent_fraud = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False
        ).order_by('-updated_at')[:20]
        
        # 4. Achievement Type Analysis
        achievement_fraud_stats = AchievementType.objects.annotate(
            total_earned=Count('user_achievements', filter=Q(user_achievements__status__in=['earned', 'claimed'])),
            fraud_count=Count('user_achievements', filter=Q(user_achievements__security_metadata__fraud_detected__isnull=False)),
            suspicious_count=Count('user_achievements', filter=Q(user_achievements__security_metadata__suspicious_ip=True))
        ).order_by('-fraud_count')
        
        # 5. Overall Statistics
        total_achievements = UserAchievement.objects.count()
        total_fraud = UserAchievement.objects.filter(security_metadata__fraud_detected__isnull=False).count()
        total_suspicious = UserAchievement.objects.filter(security_metadata__suspicious_ip=True).count()
        total_devices_tracked = UserAchievement.objects.filter(device_fingerprint_hash__isnull=False).values('device_fingerprint_hash').distinct().count()
        
        # Calculate potential fraud loss
        potential_loss = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False,
            status='claimed'
        ).aggregate(
            total=Sum('achievement_type__confio_reward')
        )['total'] or 0
        
        context = {
            **self.admin_site.each_context(request),
            'title': 'Achievement Fraud Detection Dashboard',
            'suspicious_devices': suspicious_devices[:20],  # Top 20
            'suspicious_ips': suspicious_ips[:20],  # Top 20
            'recent_fraud': recent_fraud,
            'achievement_fraud_stats': achievement_fraud_stats,
            'stats': {
                'total_achievements': total_achievements,
                'total_fraud': total_fraud,
                'total_suspicious': total_suspicious,
                'total_devices_tracked': total_devices_tracked,
                'fraud_percentage': (total_fraud / total_achievements * 100) if total_achievements > 0 else 0,
                'potential_loss': potential_loss,
                'potential_loss_usd': float(potential_loss) / 4,  # 4 CONFIO = $1
            },
            'opts': self.model._meta,
            'has_filters': False,
        }
        
        return TemplateResponse(request, 'admin/achievements/userachievement/fraud_dashboard.html', context)
    
    fieldsets = (
        ('User & Achievement', {
            'fields': ('user', 'achievement_type', 'status')
        }),
        ('Reward Information', {
            'fields': ('reward_amount_display',),
        }),
        ('Security & Fraud Detection', {
            'fields': ('device_fingerprint_display', 'claim_ip_address', 'security_metadata_display'),
            'classes': ('collapse',),
            'description': 'Device fingerprint and security information for fraud prevention'
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
    
    def fraud_indicator(self, obj):
        """Display fraud indicators based on security metadata"""
        if not obj.security_metadata:
            return format_html('<span style="color: #10B981;">✓</span>')
        
        if obj.security_metadata.get('fraud_detected'):
            reason = obj.security_metadata.get('blocked_reason', 'Fraud detected')
            return format_html(
                '<span style="color: #DC2626; font-weight: bold;" title="{}">⚠️ FRAUD</span>',
                reason
            )
        elif obj.security_metadata.get('suspicious_ip'):
            return format_html(
                '<span style="color: #F59E0B;" title="Suspicious IP activity">⚠️ Suspicious</span>'
            )
        else:
            return format_html('<span style="color: #10B981;">✓</span>')
    fraud_indicator.short_description = "Security"
    
    def device_fingerprint_display(self, obj):
        """Display device fingerprint information"""
        if not obj.device_fingerprint_hash:
            return format_html('<span style="color: #9CA3AF;">No device data</span>')
        
        # Show first 8 chars of hash for identification
        hash_preview = obj.device_fingerprint_hash[:8]
        
        # Check how many achievements from this device
        same_device_count = UserAchievement.objects.filter(
            device_fingerprint_hash=obj.device_fingerprint_hash
        ).exclude(id=obj.id).count()
        
        if same_device_count > 0:
            color = '#F59E0B' if same_device_count < 3 else '#DC2626'
            return format_html(
                '<span style="color: {};" title="Full hash: {}">{}... ({} other achievements)</span>',
                color,
                obj.device_fingerprint_hash,
                hash_preview,
                same_device_count
            )
        else:
            return format_html(
                '<span title="Full hash: {}">{}...</span>',
                obj.device_fingerprint_hash,
                hash_preview
            )
    device_fingerprint_display.short_description = "Device ID"
    
    def security_metadata_display(self, obj):
        """Display security metadata in readable format"""
        if not obj.security_metadata:
            return "No metadata"
        
        try:
            # Format metadata as a simple list
            items = []
            for key, value in obj.security_metadata.items():
                if key == 'fraud_detected':
                    items.append(f"Fraud Type: {value}")
                elif key == 'blocked_reason':
                    items.append(f"Reason: {value}")
                elif key == 'suspicious_ip':
                    items.append(f"Suspicious IP: Yes")
                elif key == 'recent_registrations':
                    items.append(f"Recent Registrations: {value}")
                else:
                    items.append(f"{key}: {value}")
            
            return format_html(
                '<pre style="margin: 0; font-size: 11px;">{}</pre>',
                '\n'.join(items)
            )
        except Exception as e:
            return f"Error displaying metadata: {e}"
    security_metadata_display.short_description = "Security Metadata"
    
    def can_claim(self, obj):
        if obj.can_claim_reward:
            return format_html('<span style="color: #10B981;">✅ Yes</span>')
        return format_html('<span style="color: #9CA3AF;">❌ No</span>')
    can_claim.short_description = "Can Claim?"
    
    actions = ['mark_as_earned', 'mark_as_claimed', 'mark_as_fraudulent', 'block_device']
    
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
    
    def mark_as_fraudulent(self, request, queryset):
        """Mark selected achievements as fraudulent"""
        from django.contrib import messages
        
        fraud_count = 0
        for achievement in queryset:
            if achievement.status in ['earned', 'claimed']:
                # Update security metadata
                achievement.security_metadata['fraud_detected'] = 'manual_review'
                achievement.security_metadata['blocked_reason'] = 'Manually marked as fraudulent by admin'
                achievement.security_metadata['blocked_by'] = request.user.username
                achievement.security_metadata['blocked_at'] = timezone.now().isoformat()
                
                # Change status to expired to prevent claiming
                if achievement.status == 'earned':
                    achievement.status = 'expired'
                
                achievement.save()
                fraud_count += 1
                
                logger.warning(
                    f"Achievement {achievement.id} marked as fraudulent by {request.user.username}. "
                    f"User: {achievement.user.id}, Type: {achievement.achievement_type.slug}"
                )
        
        messages.warning(request, f"{fraud_count} achievements marked as fraudulent.")
    mark_as_fraudulent.short_description = "Mark selected as fraudulent"
    
    def block_device(self, request, queryset):
        """Block all achievements from the same device"""
        from django.contrib import messages
        
        device_hashes = set()
        for achievement in queryset:
            if achievement.device_fingerprint_hash:
                device_hashes.add(achievement.device_fingerprint_hash)
        
        if not device_hashes:
            messages.warning(request, "No device fingerprints found in selected achievements.")
            return
        
        blocked_count = 0
        for device_hash in device_hashes:
            # Find all achievements from this device
            device_achievements = UserAchievement.objects.filter(
                device_fingerprint_hash=device_hash,
                status__in=['earned', 'pending']
            )
            
            for achievement in device_achievements:
                achievement.security_metadata['fraud_detected'] = 'device_blocked'
                achievement.security_metadata['blocked_reason'] = 'Device blocked by admin'
                achievement.security_metadata['blocked_by'] = request.user.username
                achievement.security_metadata['blocked_at'] = timezone.now().isoformat()
                
                if achievement.status == 'earned':
                    achievement.status = 'expired'
                
                achievement.save()
                blocked_count += 1
            
            logger.warning(
                f"Device {device_hash[:8]}... blocked by {request.user.username}. "
                f"{blocked_count} achievements affected."
            )
        
        messages.warning(
            request, 
            f"Blocked {blocked_count} achievements from {len(device_hashes)} device(s)."
        )
    block_device.short_description = "Block all achievements from same device"


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
        percentage_str = f"{percentage:.1f}"
        return format_html(
            '<div style="display: flex; align-items: center;">'
            '<div style="width: 200px; height: 20px; background: #e5e7eb; border-radius: 10px; overflow: hidden; margin-right: 10px;">'
            '<div style="width: {}%; height: 100%; background: {}; transition: width 0.3s;"></div>'
            '</div>'
            '<span style="font-weight: bold; color: {};">{}%</span>'
            '</div>',
            percentage, color, color, percentage_str
        )
    progress_display.short_description = "Progress"
    
    def count_display(self, obj):
        count_str = f"{obj.count:,}"
        return format_html(
            '<span style="font-size: 18px; font-weight: bold;">{}</span>',
            count_str
        )
    count_display.short_description = "Users Awarded"
    
    def remaining_display(self, obj):
        remaining = obj.get_remaining_slots()
        color = '#DC2626' if remaining < 100 else '#F59E0B' if remaining < 500 else '#10B981'
        remaining_str = f"{remaining:,}"
        return format_html(
            '<span style="font-size: 18px; font-weight: bold; color: {};">{}</span>',
            color, remaining_str
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
        count_str = f"{obj.count:,}"
        percentage_str = f"{percentage:.1f}"
        
        return format_html(
            '<div style="margin: 20px 0;">'
            '<div style="display: flex; justify-content: space-between; margin-bottom: 10px;">'
            '<span style="font-size: 24px; font-weight: bold;">{} / 10,000</span>'
            '<span style="font-size: 24px; font-weight: bold; color: {};">{}%</span>'
            '</div>'
            '<div style="width: 100%; height: 40px; background: #e5e7eb; border-radius: 20px; overflow: hidden; position: relative;">'
            '<div style="width: {}%; height: 100%; background: {}; transition: width 0.3s;"></div>'
            '<div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #374151;">'
            '{} users registered'
            '</div>'
            '</div>'
            '</div>',
            count_str, color, percentage_str,
            percentage, color,
            count_str
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
        
        rate_str = f"{rate_per_day:.0f}"
        days_str = f"{days_to_full}d" if isinstance(days_to_full, int) else days_to_full
        confio_str = f"{obj.count:,}"
        
        return format_html(
            '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0;">'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Current Rate</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #1f2937;">{}/day</div>'
            '</div>'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Est. Days to Full</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #1f2937;">{}</div>'
            '</div>'
            '<div style="background: #f3f4f6; padding: 15px; border-radius: 10px; text-align: center;">'
            '<div style="font-size: 12px; color: #6b7280; margin-bottom: 5px;">Value Awarded</div>'
            '<div style="font-size: 20px; font-weight: bold; color: #00BFA5;">{} CONFIO</div>'
            '</div>'
            '</div>',
            rate_str,
            days_str,
            confio_str  # 1 CONFIO per user
        )
    statistics.short_description = "Statistics"
    
    def has_add_permission(self, request):
        # Don't allow adding more trackers
        return PioneroBetaTracker.objects.count() == 0
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deleting the tracker
        return False
