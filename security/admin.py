from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Q
from .models import (
    IdentityVerification, SuspiciousActivity, UserBan,
    IPAddress, UserSession, DeviceFingerprint, UserDevice, AMLCheck, IPDeviceUser
)


@admin.register(IdentityVerification)
class IdentityVerificationAdmin(admin.ModelAdmin):
    """Admin for identity verifications (KYC)"""
    list_display = (
        'user_link', 'verified_name', 'document_type', 'status_badge',
        'risk_score_badge', 'verified_at', 'created_at'
    )
    list_filter = (
        'status', 'document_type', 'document_issuing_country',
        'risk_score', 'created_at'
    )
    search_fields = (
        'user__username', 'user__email',
        'verified_first_name', 'verified_last_name',
        'document_number'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'verified_at',
        'risk_assessment_display', 'document_preview'
    )
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'status', 'risk_score', 'risk_factors')
        }),
        ('Verified Personal Information', {
            'fields': (
                'verified_first_name', 'verified_last_name',
                'verified_date_of_birth', 'verified_nationality'
            )
        }),
        ('Verified Address', {
            'fields': (
                'verified_address', 'verified_city', 'verified_state',
                'verified_country', 'verified_postal_code'
            )
        }),
        ('Document Information', {
            'fields': (
                'document_type', 'document_number',
                'document_issuing_country', 'document_expiry_date',
                'document_preview'
            )
        }),
        ('Document Files', {
            'fields': (
                'document_front_image', 'document_back_image',
                'selfie_with_document'
            ),
            'classes': ('collapse',)
        }),
        ('Verification Details', {
            'fields': (
                'verified_by', 'verified_at', 'rejected_reason',
                'risk_assessment_display'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['approve_verifications', 'reject_verifications']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def verified_name(self, obj):
        return f"{obj.verified_first_name} {obj.verified_last_name}"
    verified_name.short_description = 'Verified Name'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#FFA500',
            'verified': '#28A745',
            'rejected': '#DC3545',
            'expired': '#6C757D'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#6C757D'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def risk_score_badge(self, obj):
        if obj.risk_score < 30:
            color = '#28A745'
        elif obj.risk_score < 70:
            color = '#FFA500'
        else:
            color = '#DC3545'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.risk_score
        )
    risk_score_badge.short_description = 'Risk Score'
    
    def risk_assessment_display(self, obj):
        if not obj.risk_factors:
            return "No risk factors identified"
        
        html = '<ul>'
        for factor, details in obj.risk_factors.items():
            html += f'<li><strong>{factor}:</strong> {details}</li>'
        html += '</ul>'
        return format_html(html)
    risk_assessment_display.short_description = 'Risk Assessment'
    
    def document_preview(self, obj):
        if obj.document_front_image:
            return format_html(
                '<a href="{}" target="_blank">View Front</a>',
                obj.document_front_image.url
            )
        return "No document uploaded"
    document_preview.short_description = 'Document Preview'
    
    def approve_verifications(self, request, queryset):
        count = 0
        for verification in queryset.filter(status='pending'):
            verification.approve_verification(request.user)
            count += 1
        self.message_user(request, f"{count} verifications approved.")
    approve_verifications.short_description = "Approve selected verifications"
    
    def reject_verifications(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='rejected',
            verified_by=request.user,
            rejected_reason='Bulk rejection by admin'
        )
        self.message_user(request, f"{count} verifications rejected.")
    reject_verifications.short_description = "Reject selected verifications"


@admin.register(SuspiciousActivity)
class SuspiciousActivityAdmin(admin.ModelAdmin):
    """Admin for suspicious activities"""
    list_display = (
        'user_link', 'activity_type', 'status_badge', 'severity_badge',
        'related_users_count', 'created_at'
    )
    list_filter = (
        'activity_type', 'status', 'severity_score', 'created_at'
    )
    search_fields = (
        'user__username', 'user__email',
        'investigation_notes', 'action_taken'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'detection_data_display',
        'related_ips_display'
    )
    filter_horizontal = ('related_users',)
    
    fieldsets = (
        ('Activity Information', {
            'fields': (
                'user', 'activity_type', 'status', 'severity_score'
            )
        }),
        ('Detection Details', {
            'fields': (
                'detection_data', 'detection_data_display',
                'related_ips', 'related_ips_display'
            )
        }),
        ('Investigation', {
            'fields': (
                'investigated_by', 'investigation_notes', 'action_taken'
            )
        }),
        ('Related Users', {
            'fields': ('related_users',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['mark_as_investigating', 'mark_as_confirmed', 'mark_as_dismissed']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#FFA500',
            'investigating': '#17A2B8',
            'confirmed': '#DC3545',
            'dismissed': '#6C757D',
            'banned': '#000000'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#6C757D'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def severity_badge(self, obj):
        if obj.severity_score <= 3:
            color = '#28A745'
        elif obj.severity_score <= 7:
            color = '#FFA500'
        else:
            color = '#DC3545'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}/10</span>',
            color, obj.severity_score
        )
    severity_badge.short_description = 'Severity'
    
    def related_users_count(self, obj):
        count = obj.related_users.count()
        if count > 0:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">{}</span>',
                count
            )
        return count
    related_users_count.short_description = 'Related Users'
    
    def detection_data_display(self, obj):
        import json
        return format_html(
            '<pre style="white-space: pre-wrap;">{}</pre>',
            json.dumps(obj.detection_data, indent=2)
        )
    detection_data_display.short_description = 'Detection Data (Formatted)'
    
    def related_ips_display(self, obj):
        if not obj.related_ips:
            return "No IPs recorded"
        return format_html('<br>'.join(obj.related_ips))
    related_ips_display.short_description = 'Related IP Addresses'
    
    def mark_as_investigating(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='investigating',
            investigated_by=request.user
        )
        self.message_user(request, f"{count} activities marked as investigating.")
    mark_as_investigating.short_description = "Mark as investigating"
    
    def mark_as_confirmed(self, request, queryset):
        count = queryset.update(status='confirmed')
        self.message_user(request, f"{count} activities marked as confirmed.")
    mark_as_confirmed.short_description = "Mark as confirmed"
    
    def mark_as_dismissed(self, request, queryset):
        count = queryset.update(status='dismissed')
        self.message_user(request, f"{count} activities marked as dismissed.")
    mark_as_dismissed.short_description = "Mark as dismissed"


@admin.register(UserBan)
class UserBanAdmin(admin.ModelAdmin):
    """Admin for user bans"""
    list_display = (
        'user_link', 'ban_type_badge', 'reason', 'is_active_badge',
        'banned_at', 'expires_at', 'appeal_status'
    )
    list_filter = (
        'ban_type', 'reason', 'appeal_submitted', 'banned_at'
    )
    search_fields = (
        'user__username', 'user__email',
        'reason_details', 'appeal_text'
    )
    readonly_fields = (
        'banned_at', 'created_at', 'updated_at',
        'is_active_display'
    )
    
    fieldsets = (
        ('Ban Information', {
            'fields': (
                'user', 'ban_type', 'reason', 'reason_details',
                'banned_by', 'banned_at', 'expires_at',
                'is_active_display'
            )
        }),
        ('Related Activity', {
            'fields': ('suspicious_activity',)
        }),
        ('Appeal Process', {
            'fields': (
                'appeal_submitted', 'appeal_text',
                'appeal_reviewed_by', 'appeal_decision'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['lift_temporary_bans', 'process_appeals']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def ban_type_badge(self, obj):
        colors = {
            'temporary': '#FFA500',
            'permanent': '#DC3545',
            'trading': '#17A2B8',
            'withdrawal': '#6C757D'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            colors.get(obj.ban_type, '#6C757D'),
            obj.get_ban_type_display()
        )
    ban_type_badge.short_description = 'Ban Type'
    
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: #6C757D;">Inactive</span>'
        )
    is_active_badge.short_description = 'Status'
    
    def is_active_display(self, obj):
        return "Yes" if obj.is_active else "No"
    is_active_display.short_description = 'Currently Active'
    
    def appeal_status(self, obj):
        if not obj.appeal_submitted:
            return "-"
        if obj.appeal_reviewed_by:
            return format_html(
                '<span style="color: #28A745;">Reviewed</span>'
            )
        return format_html(
            '<span style="color: #FFA500;">Pending</span>'
        )
    appeal_status.short_description = 'Appeal'
    
    def lift_temporary_bans(self, request, queryset):
        count = queryset.filter(
            ban_type='temporary'
        ).update(
            expires_at=timezone.now()
        )
        self.message_user(request, f"{count} temporary bans lifted.")
    lift_temporary_bans.short_description = "Lift selected temporary bans"


@admin.register(IPAddress)
class IPAddressAdmin(admin.ModelAdmin):
    """Admin for IP addresses"""
    list_display = (
        'ip_address_display', 'country_flag', 'location', 'risk_indicators',
        'risk_score_badge', 'total_users', 'is_blocked_badge', 'last_seen'
    )
    list_filter = (
        'is_vpn', 'is_tor', 'is_datacenter', 'is_blocked',
        'country_code', 'risk_score'
    )
    search_fields = (
        'ip_address', 'country_name', 'city'
    )
    readonly_fields = (
        'first_seen', 'last_seen', 'blocked_at'
    )
    
    fieldsets = (
        ('IP Information', {
            'fields': (
                'ip_address', 'country_code', 'country_name',
                'region', 'city', 'latitude', 'longitude'
            )
        }),
        ('Risk Assessment', {
            'fields': (
                'is_vpn', 'is_tor', 'is_datacenter',
                'risk_score', 'total_users'
            )
        }),
        ('Blocking', {
            'fields': (
                'is_blocked', 'blocked_reason', 'blocked_at', 'blocked_by'
            )
        }),
        ('Tracking', {
            'fields': ('first_seen', 'last_seen'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['block_ips', 'unblock_ips', 'fetch_geolocation']
    
    def ip_address_display(self, obj):
        """Display IP address prominently"""
        return format_html(
            '<strong style="font-size: 1.1em; font-family: monospace;">{}</strong>',
            obj.ip_address
        )
    ip_address_display.short_description = 'IP Address'
    ip_address_display.admin_order_field = 'ip_address'
    
    def country_flag(self, obj):
        if obj.country_code:
            return format_html(
                '<span title="{}">{}</span>',
                obj.country_name,
                obj.country_code
            )
        return "-"
    country_flag.short_description = 'Country'
    
    def location(self, obj):
        parts = []
        if obj.city:
            parts.append(obj.city)
        if obj.region:
            parts.append(obj.region)
        if obj.country_name:
            parts.append(obj.country_name)
        return ", ".join(parts) or "-"
    location.short_description = 'Location'
    
    def risk_indicators(self, obj):
        indicators = []
        if obj.is_vpn:
            indicators.append('VPN')
        if obj.is_tor:
            indicators.append('TOR')
        if obj.is_datacenter:
            indicators.append('DC')
        
        if indicators:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">{}</span>',
                ' | '.join(indicators)
            )
        return format_html(
            '<span style="color: #28A745;">Clean</span>'
        )
    risk_indicators.short_description = 'Indicators'
    
    def risk_score_badge(self, obj):
        if obj.risk_score < 30:
            color = '#28A745'
        elif obj.risk_score < 70:
            color = '#FFA500'
        else:
            color = '#DC3545'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.risk_score
        )
    risk_score_badge.short_description = 'Risk'
    
    def is_blocked_badge(self, obj):
        if obj.is_blocked:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">✓ Blocked</span>'
            )
        return "-"
    is_blocked_badge.short_description = 'Blocked'
    
    def block_ips(self, request, queryset):
        count = queryset.filter(is_blocked=False).update(
            is_blocked=True,
            blocked_at=timezone.now(),
            blocked_by=request.user,
            blocked_reason='Bulk block by admin'
        )
        self.message_user(request, f"{count} IPs blocked.")
    block_ips.short_description = "Block selected IPs"
    
    def unblock_ips(self, request, queryset):
        count = queryset.filter(is_blocked=True).update(
            is_blocked=False,
            blocked_at=None,
            blocked_by=None,
            blocked_reason=''
        )
        self.message_user(request, f"{count} IPs unblocked.")
    unblock_ips.short_description = "Unblock selected IPs"
    
    def fetch_geolocation(self, request, queryset):
        """Fetch geolocation data for selected IPs on demand"""
        import requests
        success_count = 0
        error_count = 0
        
        for ip_obj in queryset:
            # Skip private/local IP addresses
            ip_parts = ip_obj.ip_address.split('.')
            if (ip_obj.ip_address.startswith(('10.', '192.168.', '127.')) or
                (ip_obj.ip_address.startswith('172.') and 16 <= int(ip_parts[1]) <= 31)):
                # This is a private IP - skip it
                error_count += 1
                continue
                
            try:
                # Use ipapi.co free service (1000 requests/day)
                response = requests.get(
                    f'https://ipapi.co/{ip_obj.ip_address}/json/',
                    timeout=5,
                    headers={'User-Agent': 'Confio Security Admin/1.0'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Check for error in response (e.g., reserved/private IP)
                    if data.get('error'):
                        error_count += 1
                        continue
                    
                    # Update IP object with geographic data
                    ip_obj.country_code = data.get('country_code', '')[:2]
                    ip_obj.country_name = data.get('country_name', '')[:100]
                    ip_obj.city = data.get('city', '')[:100]
                    ip_obj.region = data.get('region', '')[:100]
                    
                    # Handle latitude/longitude safely
                    try:
                        if data.get('latitude'):
                            ip_obj.latitude = float(data.get('latitude'))
                        if data.get('longitude'):
                            ip_obj.longitude = float(data.get('longitude'))
                    except (ValueError, TypeError):
                        pass
                    
                    ip_obj.save()
                    success_count += 1
                    
                else:
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
        
        if success_count > 0:
            self.message_user(
                request, 
                f"Successfully fetched geolocation for {success_count} IPs."
            )
        if error_count > 0:
            self.message_user(
                request, 
                f"Failed to fetch geolocation for {error_count} IPs.", 
                level='WARNING'
            )
    fetch_geolocation.short_description = "Fetch geolocation data (uses API quota)"


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    """Admin for user sessions"""
    list_display = (
        'user_link', 'device_info', 'ip_info', 'duration',
        'is_suspicious_badge', 'started_at'
    )
    list_filter = (
        'device_type', 'is_suspicious', 'started_at'
    )
    search_fields = (
        'user__username', 'user__email',
        'session_key', 'device_fingerprint'
    )
    readonly_fields = (
        'started_at', 'last_activity', 'ended_at',
        'suspicious_reasons_display'
    )
    
    fieldsets = (
        ('Session Information', {
            'fields': (
                'user', 'session_key', 'started_at',
                'last_activity', 'ended_at'
            )
        }),
        ('Device Information', {
            'fields': (
                'device_fingerprint', 'user_agent', 'device_type',
                'os_name', 'browser_name'
            )
        }),
        ('Location', {
            'fields': ('ip_address',)
        }),
        ('Security', {
            'fields': (
                'is_suspicious', 'suspicious_reasons',
                'suspicious_reasons_display'
            )
        })
    )
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def device_info(self, obj):
        return f"{obj.device_type} - {obj.os_name}/{obj.browser_name}"
    device_info.short_description = 'Device'
    
    def ip_info(self, obj):
        if obj.ip_address:
            return format_html(
                '<a href="{}">{}</a>',
                reverse('admin:security_ipaddress_change', args=[obj.ip_address.id]),
                obj.ip_address.ip_address
            )
        return "-"
    ip_info.short_description = 'IP Address'
    
    def duration(self, obj):
        if obj.ended_at:
            duration = obj.ended_at - obj.started_at
        else:
            duration = timezone.now() - obj.started_at
        
        hours = duration.total_seconds() // 3600
        minutes = (duration.total_seconds() % 3600) // 60
        
        if hours > 0:
            return f"{int(hours)}h {int(minutes)}m"
        return f"{int(minutes)}m"
    duration.short_description = 'Duration'
    
    def is_suspicious_badge(self, obj):
        if obj.is_suspicious:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">⚠️ Suspicious</span>'
            )
        return "-"
    is_suspicious_badge.short_description = 'Suspicious'
    
    def suspicious_reasons_display(self, obj):
        if not obj.suspicious_reasons:
            return "No suspicious indicators"
        return format_html('<br>'.join(obj.suspicious_reasons))
    suspicious_reasons_display.short_description = 'Suspicious Reasons'


@admin.register(DeviceFingerprint)
class DeviceFingerprintAdmin(admin.ModelAdmin):
    """Admin for device fingerprints"""
    list_display = (
        'fingerprint_short', 'total_users', 'risk_score_badge',
        'is_blocked_badge', 'first_seen', 'last_seen'
    )
    list_filter = (
        'is_blocked', 'risk_score', 'total_users'
    )
    search_fields = ('fingerprint',)
    readonly_fields = (
        'fingerprint', 'first_seen', 'last_seen',
        'device_details_display', 'users_list'
    )
    
    fieldsets = (
        ('Device Information', {
            'fields': (
                'fingerprint', 'device_details', 'device_details_display'
            )
        }),
        ('Risk Assessment', {
            'fields': (
                'risk_score', 'total_users', 'users_list'
            )
        }),
        ('Blocking', {
            'fields': (
                'is_blocked', 'blocked_reason'
            )
        }),
        ('Tracking', {
            'fields': ('first_seen', 'last_seen'),
            'classes': ('collapse',)
        })
    )
    
    def fingerprint_short(self, obj):
        return f"{obj.fingerprint[:20]}..."
    fingerprint_short.short_description = 'Fingerprint'
    
    def risk_score_badge(self, obj):
        if obj.risk_score < 30:
            color = '#28A745'
        elif obj.risk_score < 70:
            color = '#FFA500'
        else:
            color = '#DC3545'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.risk_score
        )
    risk_score_badge.short_description = 'Risk'
    
    def is_blocked_badge(self, obj):
        if obj.is_blocked:
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">✓ Blocked</span>'
            )
        return "-"
    is_blocked_badge.short_description = 'Blocked'
    
    def device_details_display(self, obj):
        import json
        return format_html(
            '<pre style="white-space: pre-wrap;">{}</pre>',
            json.dumps(obj.device_details, indent=2)
        )
    device_details_display.short_description = 'Device Details (Formatted)'
    
    def users_list(self, obj):
        users = obj.users.all()[:10]
        if not users:
            return "No users"
        
        links = []
        for user in users:
            url = reverse('admin:users_user_change', args=[user.id])
            links.append(f'<a href="{url}">{user.username}</a>')
        
        html = '<br>'.join(links)
        if obj.total_users > 10:
            html += f'<br>... and {obj.total_users - 10} more'
        
        return format_html(html)
    users_list.short_description = 'Associated Users'


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    """Admin for user-device relationships"""
    list_display = (
        'user', 'device_short', 'is_trusted', 'total_sessions',
        'first_used', 'last_used'
    )
    list_filter = ('is_trusted', 'first_used')
    search_fields = (
        'user__username', 'user__email',
        'device__fingerprint'
    )
    raw_id_fields = ('user', 'device')
    
    def device_short(self, obj):
        return f"{obj.device.fingerprint[:20]}..."
    device_short.short_description = 'Device'


@admin.register(IPDeviceUser)
class IPDeviceUserAdmin(admin.ModelAdmin):
    """Admin for IP-Device-User associations for fraud detection"""
    list_display = (
        'user_link', 'ip_link', 'device_short', 'total_sessions',
        'is_suspicious_badge', 'auth_method', 'last_seen'
    )
    list_filter = (
        'is_suspicious', 'auth_method', 'first_seen', 'last_seen'
    )
    search_fields = (
        'user__username', 'user__email',
        'ip_address__ip_address', 'device_fingerprint__fingerprint'
    )
    readonly_fields = (
        'first_seen', 'last_seen', 'risk_factors_display',
        'location_info_display', 'fraud_patterns_display'
    )
    raw_id_fields = ('user', 'ip_address', 'device_fingerprint')
    
    fieldsets = (
        ('Association Information', {
            'fields': (
                'user', 'ip_address', 'device_fingerprint', 'auth_method'
            )
        }),
        ('Activity Tracking', {
            'fields': (
                'first_seen', 'last_seen', 'total_sessions'
            )
        }),
        ('Risk Assessment', {
            'fields': (
                'is_suspicious', 'risk_factors', 'risk_factors_display'
            )
        }),
        ('Location Information', {
            'fields': (
                'location_info', 'location_info_display'
            ),
            'classes': ('collapse',)
        }),
        ('Fraud Analysis', {
            'fields': ('fraud_patterns_display',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['mark_as_suspicious', 'mark_as_safe', 'calculate_risk_factors', 'analyze_fraud_patterns']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    user_link.admin_order_field = 'user__username'
    
    def ip_link(self, obj):
        url = reverse('admin:security_ipaddress_change', args=[obj.ip_address.id])
        return format_html(
            '<a href="{}" style="font-family: monospace;">{}</a>',
            url, obj.ip_address.ip_address
        )
    ip_link.short_description = 'IP Address'
    ip_link.admin_order_field = 'ip_address__ip_address'
    
    def device_short(self, obj):
        url = reverse('admin:security_devicefingerprint_change', args=[obj.device_fingerprint.id])
        return format_html(
            '<a href="{}" style="font-family: monospace;">{}</a>',
            url, f"{obj.device_fingerprint.fingerprint[:16]}..."
        )
    device_short.short_description = 'Device'
    device_short.admin_order_field = 'device_fingerprint__fingerprint'
    
    def is_suspicious_badge(self, obj):
        if obj.is_suspicious:
            risk_count = len(obj.risk_factors) if obj.risk_factors else 0
            return format_html(
                '<span style="color: #DC3545; font-weight: bold;">⚠️ Suspicious ({})</span>',
                risk_count
            )
        return format_html('<span style="color: #28A745;">✓ Clean</span>')
    is_suspicious_badge.short_description = 'Status'
    is_suspicious_badge.admin_order_field = 'is_suspicious'
    
    def risk_factors_display(self, obj):
        if not obj.risk_factors:
            return "No risk factors identified"
        
        html = '<ul style="margin: 0; padding-left: 20px;">'
        for factor in obj.risk_factors:
            html += f'<li><strong>{factor.replace("_", " ").title()}</strong></li>'
        html += '</ul>'
        return format_html(html)
    risk_factors_display.short_description = 'Risk Factors'
    
    def location_info_display(self, obj):
        if not obj.location_info:
            return "No location data"
        
        import json
        return format_html(
            '<pre style="white-space: pre-wrap; font-size: 11px;">{}</pre>',
            json.dumps(obj.location_info, indent=2)
        )
    location_info_display.short_description = 'Location Data'
    
    def fraud_patterns_display(self, obj):
        """Show fraud patterns analysis for this association"""
        try:
            from security.utils import get_ip_fraud_patterns, get_device_fraud_patterns, get_user_fraud_patterns
            
            # Get patterns for this specific association
            ip_patterns = get_ip_fraud_patterns(
                ip_address=obj.ip_address.ip_address,
                days=30
            )
            
            device_patterns = get_device_fraud_patterns(
                device_fingerprint=obj.device_fingerprint.fingerprint,
                days=30
            )
            
            user_patterns = get_user_fraud_patterns(
                user_id=obj.user.id,
                days=30
            )
            
            html = '<div style="font-size: 11px;">'
            
            # IP Patterns
            html += f'<h4 style="margin: 5px 0;">IP Patterns (Risk: {ip_patterns["risk_score"]}/100)</h4>'
            if ip_patterns['patterns']:
                html += '<ul style="margin: 0; padding-left: 15px;">'
                for pattern in ip_patterns['patterns'][:3]:  # Show top 3
                    html += f'<li><strong>{pattern["type"]}:</strong> {pattern["description"]}</li>'
                html += '</ul>'
            else:
                html += '<em>No suspicious IP patterns</em>'
            
            # Device Patterns
            html += f'<h4 style="margin: 5px 0;">Device Patterns (Risk: {device_patterns["risk_score"]}/100)</h4>'
            if device_patterns['patterns']:
                html += '<ul style="margin: 0; padding-left: 15px;">'
                for pattern in device_patterns['patterns'][:3]:  # Show top 3
                    html += f'<li><strong>{pattern["type"]}:</strong> {pattern["description"]}</li>'
                html += '</ul>'
            else:
                html += '<em>No suspicious device patterns</em>'
            
            # User Patterns
            html += f'<h4 style="margin: 5px 0;">User Patterns (Risk: {user_patterns["risk_score"]}/100)</h4>'
            if user_patterns['patterns']:
                html += '<ul style="margin: 0; padding-left: 15px;">'
                for pattern in user_patterns['patterns'][:3]:  # Show top 3
                    html += f'<li><strong>{pattern["type"]}:</strong> {pattern["description"]}</li>'
                html += '</ul>'
            else:
                html += '<em>No suspicious user patterns</em>'
            
            html += '</div>'
            return format_html(html)
            
        except Exception as e:
            return format_html(
                '<div style="color: #DC3545;">Error analyzing patterns: {}</div>',
                str(e)
            )
    fraud_patterns_display.short_description = 'Fraud Analysis'
    
    def mark_as_suspicious(self, request, queryset):
        count = queryset.update(is_suspicious=True)
        self.message_user(request, f"{count} associations marked as suspicious.")
    mark_as_suspicious.short_description = "Mark as suspicious"
    
    def mark_as_safe(self, request, queryset):
        count = queryset.update(is_suspicious=False, risk_factors=[])
        self.message_user(request, f"{count} associations marked as safe.")
    mark_as_safe.short_description = "Mark as safe"
    
    def calculate_risk_factors(self, request, queryset):
        count = 0
        for association in queryset:
            association.calculate_risk_factors()
            count += 1
        self.message_user(request, f"Risk factors calculated for {count} associations.")
    calculate_risk_factors.short_description = "Recalculate risk factors"
    
    def analyze_fraud_patterns(self, request, queryset):
        """Analyze fraud patterns for selected associations"""
        try:
            from security.utils import get_ip_fraud_patterns, get_device_fraud_patterns, get_user_fraud_patterns
            
            high_risk_count = 0
            total_analyzed = 0
            
            for association in queryset[:10]:  # Limit to 10 to avoid timeout
                # Check if any patterns indicate high risk
                ip_patterns = get_ip_fraud_patterns(ip_address=association.ip_address.ip_address, days=30)
                device_patterns = get_device_fraud_patterns(device_fingerprint=association.device_fingerprint.fingerprint, days=30)
                user_patterns = get_user_fraud_patterns(user_id=association.user.id, days=30)
                
                max_risk = max(ip_patterns['risk_score'], device_patterns['risk_score'], user_patterns['risk_score'])
                
                if max_risk > 70:
                    association.is_suspicious = True
                    association.save(update_fields=['is_suspicious'])
                    high_risk_count += 1
                
                total_analyzed += 1
            
            if total_analyzed > 0:
                self.message_user(
                    request, 
                    f"Analyzed {total_analyzed} associations. {high_risk_count} marked as high-risk."
                )
            else:
                self.message_user(request, "No associations to analyze.")
                
        except Exception as e:
            self.message_user(
                request, 
                f"Error during fraud analysis: {str(e)}", 
                level='ERROR'
            )
    analyze_fraud_patterns.short_description = "Analyze fraud patterns (top 10)"


@admin.register(AMLCheck)
class AMLCheckAdmin(admin.ModelAdmin):
    """Admin for AML checks"""
    list_display = (
        'user_link', 'check_type', 'status_badge', 'risk_score_badge',
        'transaction_volume', 'reviewed_status', 'created_at'
    )
    list_filter = (
        'check_type', 'status', 'risk_score', 'created_at'
    )
    search_fields = (
        'user__username', 'user__email',
        'review_notes'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'reviewed_at',
        'risk_factors_display', 'unusual_patterns_display'
    )
    
    fieldsets = (
        ('Check Information', {
            'fields': (
                'user', 'check_type', 'status', 'risk_score'
            )
        }),
        ('Risk Assessment', {
            'fields': (
                'risk_factors', 'risk_factors_display',
                'unusual_patterns', 'unusual_patterns_display'
            )
        }),
        ('Transaction Analysis', {
            'fields': (
                'transaction_volume_30d', 'transaction_count_30d'
            )
        }),
        ('Review Process', {
            'fields': (
                'reviewed_by', 'reviewed_at', 'review_notes'
            )
        }),
        ('Actions', {
            'fields': (
                'actions_required', 'actions_taken'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['mark_as_cleared', 'mark_as_flagged', 'escalate_checks']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#FFA500',
            'cleared': '#28A745',
            'flagged': '#DC3545',
            'escalated': '#17A2B8',
            'blocked': '#000000'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#6C757D'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def risk_score_badge(self, obj):
        if obj.risk_score < 30:
            color = '#28A745'
        elif obj.risk_score < 70:
            color = '#FFA500'
        else:
            color = '#DC3545'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.risk_score
        )
    risk_score_badge.short_description = 'Risk'
    
    def transaction_volume(self, obj):
        return f"${obj.transaction_volume_30d:,.2f}"
    transaction_volume.short_description = '30d Volume'
    
    def reviewed_status(self, obj):
        if obj.reviewed_by:
            return format_html(
                '<span style="color: #28A745;">✓ Reviewed</span>'
            )
        return format_html(
            '<span style="color: #FFA500;">Pending</span>'
        )
    reviewed_status.short_description = 'Review'
    
    def risk_factors_display(self, obj):
        if not obj.risk_factors:
            return "No risk factors identified"
        
        import json
        return format_html(
            '<pre style="white-space: pre-wrap;">{}</pre>',
            json.dumps(obj.risk_factors, indent=2)
        )
    risk_factors_display.short_description = 'Risk Factors (Formatted)'
    
    def unusual_patterns_display(self, obj):
        if not obj.unusual_patterns:
            return "No unusual patterns detected"
        return format_html('<br>'.join(obj.unusual_patterns))
    unusual_patterns_display.short_description = 'Unusual Patterns'
    
    def mark_as_cleared(self, request, queryset):
        count = queryset.update(
            status='cleared',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f"{count} checks marked as cleared.")
    mark_as_cleared.short_description = "Mark as cleared"
    
    def mark_as_flagged(self, request, queryset):
        count = queryset.update(
            status='flagged',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f"{count} checks marked as flagged.")
    mark_as_flagged.short_description = "Mark as flagged"
    
    def escalate_checks(self, request, queryset):
        count = queryset.update(status='escalated')
        self.message_user(request, f"{count} checks escalated for senior review.")
    escalate_checks.short_description = "Escalate for senior review"