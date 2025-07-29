"""
Security middleware for tracking IPs, sessions, and device fingerprints
"""
import json
import logging
from typing import Optional, Dict
from django.utils import timezone
import requests
from django.conf import settings
from django.core.cache import cache
from user_agents import parse

from .models import IPAddress, UserSession, DeviceFingerprint, UserDevice, UserBan
from .utils import calculate_device_fingerprint, check_ip_reputation

logger = logging.getLogger(__name__)


class SecurityMiddleware:
    """Main security middleware for tracking and monitoring"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Check if user is banned before processing
        if request.user.is_authenticated:
            if self.check_user_banned(request.user):
                from django.http import HttpResponseForbidden
                return HttpResponseForbidden("Your account has been suspended. Please contact support.")
        
        # Track IP address
        ip_address = self.track_ip_address(request)
        
        # Track session and device
        if request.user.is_authenticated:
            self.track_user_session(request, ip_address)
        
        # Process request
        response = self.get_response(request)
        
        # Update last activity
        if hasattr(request, 'security_session'):
            request.security_session.last_activity = timezone.now()
            request.security_session.save(update_fields=['last_activity'])
        
        return response
    
    def check_user_banned(self, user) -> bool:
        """Check if user has active ban"""
        # Cache ban status for 5 minutes to reduce DB queries
        cache_key = f"user_ban_status_{user.id}"
        banned = cache.get(cache_key)
        
        if banned is None:
            banned = UserBan.objects.filter(
                user=user,
                deleted_at__isnull=True
            ).exclude(
                ban_type='temporary',
                expires_at__lt=timezone.now()
            ).exists()
            
            cache.set(cache_key, banned, 300)  # Cache for 5 minutes
        
        return banned
    
    def get_client_ip(self, request) -> str:
        """Extract client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def track_ip_address(self, request) -> Optional[IPAddress]:
        """Track and analyze IP address"""
        ip_str = self.get_client_ip(request)
        if not ip_str:
            return None
        
        # Get or create IP record
        ip_obj, created = IPAddress.objects.get_or_create(
            ip_address=ip_str,
            defaults={
                'first_seen': timezone.now(),
                'last_seen': timezone.now()
            }
        )
        
        # Update last seen
        if not created:
            ip_obj.last_seen = timezone.now()
            ip_obj.save(update_fields=['last_seen'])
        
        # Commented out automatic geo lookup to save API calls (1000/day limit)
        # Geo info can be fetched manually from admin panel
        # if created or not ip_obj.country_code:
        #     self.update_ip_geo_info(ip_obj)
        
        # Check IP reputation if new
        if created:
            self.check_and_update_ip_reputation(ip_obj)
        
        request.security_ip = ip_obj
        return ip_obj
    
    def update_ip_geo_info(self, ip_obj: IPAddress):
        """Update IP geographical information using free IP geolocation API"""
        try:
            # Use ipapi.co free service (1000 requests/day)
            response = requests.get(
                f'https://ipapi.co/{ip_obj.ip_address}/json/',
                timeout=5,
                headers={'User-Agent': 'Confio Security/1.0'}
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Update IP object with geographic data
                ip_obj.country_code = data.get('country_code', '')[:2]  # Ensure max 2 chars
                ip_obj.country_name = data.get('country_name', '')[:100]  # Ensure max 100 chars
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
                logger.info(f"Updated geo info for IP {ip_obj.ip_address}: {data.get('country_code', 'Unknown')}")
                
        except requests.RequestException as e:
            logger.warning(f"Could not fetch geo info for IP {ip_obj.ip_address}: {e}")
        except Exception as e:
            logger.error(f"Error updating geo info for IP {ip_obj.ip_address}: {e}")
    
    def check_and_update_ip_reputation(self, ip_obj: IPAddress):
        """Check IP reputation using external services"""
        try:
            reputation_data = check_ip_reputation(ip_obj.ip_address)
            
            ip_obj.is_vpn = reputation_data.get('is_vpn', False)
            ip_obj.is_tor = reputation_data.get('is_tor', False)
            ip_obj.is_datacenter = reputation_data.get('is_datacenter', False)
            
            # Calculate risk score based on reputation
            risk_score = 0
            if ip_obj.is_vpn:
                risk_score += 30
            if ip_obj.is_tor:
                risk_score += 40
            if ip_obj.is_datacenter:
                risk_score += 20
            
            ip_obj.risk_score = min(risk_score, 100)
            ip_obj.save()
        except Exception as e:
            logger.error(f"Error checking IP reputation: {e}")
    
    def track_user_session(self, request, ip_address: Optional[IPAddress]):
        """Track user session and device"""
        if not hasattr(request, 'session') or not request.session.session_key:
            return
        
        # Get device fingerprint
        fingerprint_data = self.extract_device_fingerprint(request)
        fingerprint_hash = calculate_device_fingerprint(fingerprint_data)
        
        # Get or create device fingerprint
        device, device_created = DeviceFingerprint.objects.get_or_create(
            fingerprint=fingerprint_hash,
            defaults={
                'device_details': fingerprint_data,
                'first_seen': timezone.now(),
                'last_seen': timezone.now()
            }
        )
        
        if not device_created:
            device.last_seen = timezone.now()
            device.save(update_fields=['last_seen'])
        
        # Get or create user-device relationship
        user_device, ud_created = UserDevice.objects.get_or_create(
            user=request.user,
            device=device,
            defaults={
                'first_used': timezone.now(),
                'last_used': timezone.now(),
                'total_sessions': 1
            }
        )
        
        if not ud_created:
            user_device.last_used = timezone.now()
            user_device.total_sessions += 1
            user_device.save(update_fields=['last_used', 'total_sessions'])
        
        # Update device total users count
        if device_created or ud_created:
            device.total_users = device.users.count()
            device.save(update_fields=['total_users'])
        
        # Check for suspicious device usage
        self.check_device_suspicious_activity(device, request.user)
        
        # Get or create session
        session, session_created = UserSession.objects.get_or_create(
            session_key=request.session.session_key,
            defaults={
                'user': request.user,
                'started_at': timezone.now(),
                'last_activity': timezone.now(),
                'device_fingerprint': fingerprint_hash,
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'device_type': self.get_device_type(request),
                'os_name': self.get_os_name(request),
                'browser_name': self.get_browser_name(request),
                'ip_address': ip_address
            }
        )
        
        if not session_created:
            session.last_activity = timezone.now()
            session.save(update_fields=['last_activity'])
        
        # Check for suspicious session patterns
        self.check_session_suspicious_patterns(session, request)
        
        # Store session in request for later use
        request.security_session = session
        request.security_device = device
        request.security_user_device = user_device
    
    def extract_device_fingerprint(self, request) -> Dict:
        """Extract device fingerprint data from request"""
        # Try to get enhanced fingerprint from React Native app
        enhanced_fingerprint = self.get_enhanced_fingerprint(request)
        if enhanced_fingerprint:
            return enhanced_fingerprint
        
        # Fallback to basic fingerprint data
        return {
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'accept_language': request.META.get('HTTP_ACCEPT_LANGUAGE', ''),
            'accept_encoding': request.META.get('HTTP_ACCEPT_ENCODING', ''),
            'accept': request.META.get('HTTP_ACCEPT', ''),
            'dnt': request.META.get('HTTP_DNT', ''),
            # Add client-side fingerprint data if available
            'screen_resolution': request.POST.get('screen_resolution', ''),
            'timezone': request.POST.get('timezone', ''),
            'plugins': request.POST.get('plugins', ''),
            'canvas_hash': request.POST.get('canvas_hash', ''),
            'webgl_hash': request.POST.get('webgl_hash', ''),
            'audio_hash': request.POST.get('audio_hash', ''),
            'source': 'basic_extraction'
        }
    
    def get_enhanced_fingerprint(self, request) -> Dict:
        """Extract enhanced fingerprint from React Native app"""
        try:
            # Check for fingerprint in POST data (GraphQL variables)
            fingerprint_json = None
            
            # Try to get from GraphQL variables
            if hasattr(request, 'body') and request.body:
                import json
                try:
                    body = json.loads(request.body.decode('utf-8'))
                    variables = body.get('variables', {})
                    
                    # Check for deviceFingerprint in variables
                    if 'deviceFingerprint' in variables:
                        fingerprint_json = variables['deviceFingerprint']
                    
                    # Check for fingerprint data in input
                    input_data = variables.get('input', {})
                    if 'deviceFingerprint' in input_data:
                        fingerprint_json = input_data['deviceFingerprint']
                        
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            
            # Try to get from HTTP headers (alternative method)
            if not fingerprint_json:
                fingerprint_json = request.META.get('HTTP_X_DEVICE_FINGERPRINT')
            
            # Try to get from POST parameters
            if not fingerprint_json:
                fingerprint_json = request.POST.get('device_fingerprint')
            
            if fingerprint_json:
                if isinstance(fingerprint_json, str):
                    import json
                    fingerprint_data = json.loads(fingerprint_json)
                else:
                    fingerprint_data = fingerprint_json
                
                # Validate and enhance the fingerprint data
                enhanced_data = self.process_enhanced_fingerprint(fingerprint_data)
                enhanced_data['source'] = 'react_native_app'
                return enhanced_data
                
        except Exception as e:
            logger.error(f"Error extracting enhanced fingerprint: {e}")
        
        return None
    
    def process_enhanced_fingerprint(self, fingerprint_data: Dict) -> Dict:
        """Process and validate enhanced fingerprint data from React Native"""
        processed = {
            'fingerprint_version': fingerprint_data.get('fingerprintVersion', '1.0'),
            'timestamp': fingerprint_data.get('timestamp'),
            'is_fallback': fingerprint_data.get('isFallback', False)
        }
        
        # Extract device information
        device_info = fingerprint_data.get('deviceInfo', {})
        processed.update({
            'platform': device_info.get('platform', 'unknown'),
            'platform_version': device_info.get('platformVersion', 'unknown'),
            'is_testing': device_info.get('isTesting', False),
            'is_tv': device_info.get('isTV', False)
        })
        
        # Extract system information
        system_info = fingerprint_data.get('systemInfo', {})
        processed.update({
            'system_name': system_info.get('systemName', ''),
            'system_version': system_info.get('systemVersion', ''),
            'model': system_info.get('model', 'unknown'),
            'brand': system_info.get('brand', 'unknown'),
            'manufacturer': system_info.get('manufacturer', 'unknown')
        })
        
        # Extract screen information
        screen_info = fingerprint_data.get('screenInfo', {})
        processed.update({
            'screen_width': screen_info.get('screenWidth', 0),
            'screen_height': screen_info.get('screenHeight', 0),
            'pixel_ratio': screen_info.get('pixelRatio', 1),
            'font_scale': screen_info.get('fontScale', 1),
            'density_category': screen_info.get('densityCategory', 'unknown'),
            'aspect_ratio': screen_info.get('aspectRatio', 0)
        })
        
        # Extract locale information
        locale_info = fingerprint_data.get('localeInfo', {})
        processed.update({
            'timezone': locale_info.get('timezone', 'unknown'),
            'locale': locale_info.get('locale', 'unknown'),
            'country': locale_info.get('country', 'unknown'),
            'language': locale_info.get('language', 'unknown'),
            'timezone_offset': locale_info.get('timezoneOffset', 0),
            'currency': locale_info.get('currency', 'unknown')
        })
        
        # Extract hardware information
        hardware_info = fingerprint_data.get('hardwareInfo', {})
        processed.update({
            'hardware_class': hardware_info.get('hardwareClass', 'unknown'),
            'screen_size': hardware_info.get('screenSize', 'unknown'),
            'estimated_memory': hardware_info.get('estimatedMemory', 'unknown'),
            'screen_pixel_count': hardware_info.get('screenPixelCount', 0)
        })
        
        # Extract React Native information
        rn_info = fingerprint_data.get('rnInfo', {})
        processed.update({
            'hermes_enabled': rn_info.get('hermes', False),
            'is_debug': rn_info.get('__DEV__', False),
            'available_modules': rn_info.get('availableModules', {})
        })
        
        # Extract behavioral information
        behavioral_info = fingerprint_data.get('behavioralInfo', {})
        processed.update({
            'app_launch_count': behavioral_info.get('appLaunchCount', 0),
            'first_install_time': behavioral_info.get('firstInstallTime'),
            'session_pattern_count': len(behavioral_info.get('sessionPattern', []))
        })
        
        # Extract persistent ID
        processed['persistent_device_id'] = fingerprint_data.get('persistentId', 'unknown')
        
        return processed
    
    def get_device_type(self, request) -> str:
        """Determine device type from user agent"""
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        if not ua_string:
            return 'unknown'
        
        user_agent = parse(ua_string)
        
        if user_agent.is_mobile:
            return 'mobile'
        elif user_agent.is_tablet:
            return 'tablet'
        elif user_agent.is_pc:
            return 'desktop'
        else:
            return 'unknown'
    
    def get_os_name(self, request) -> str:
        """Extract OS name from user agent"""
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        if not ua_string:
            return ''
        
        user_agent = parse(ua_string)
        return f"{user_agent.os.family} {user_agent.os.version_string}".strip()
    
    def get_browser_name(self, request) -> str:
        """Extract browser name from user agent"""
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        if not ua_string:
            return ''
        
        user_agent = parse(ua_string)
        return f"{user_agent.browser.family} {user_agent.browser.version_string}".strip()
    
    def check_device_suspicious_activity(self, device: DeviceFingerprint, user):
        """Check for suspicious device usage patterns"""
        # Check if too many users on same device
        if device.total_users > 5:
            device.risk_score = min(device.risk_score + 20, 100)
            device.save(update_fields=['risk_score'])
            
            # Create suspicious activity record
            from .models import SuspiciousActivity
            SuspiciousActivity.objects.get_or_create(
                user=user,
                activity_type='multiple_accounts',
                defaults={
                    'detection_data': {
                        'device_fingerprint': device.fingerprint,
                        'total_users': device.total_users,
                        'device_id': device.id
                    },
                    'severity_score': min(device.total_users, 10),
                    'status': 'pending'
                }
            )
    
    def check_session_suspicious_patterns(self, session: UserSession, request):
        """Check for suspicious session patterns"""
        suspicious_reasons = []
        
        # Check for rapid location changes
        if session.ip_address:
            last_session = UserSession.objects.filter(
                user=session.user,
                ended_at__isnull=False
            ).exclude(
                id=session.id
            ).order_by('-ended_at').first()
            
            if last_session and last_session.ip_address:
                # If countries are different and time is less than 1 hour
                time_diff = (session.started_at - last_session.ended_at).total_seconds()
                if (last_session.ip_address.country_code != session.ip_address.country_code 
                    and time_diff < 3600):
                    suspicious_reasons.append('rapid_location_change')
        
        # Check for VPN/TOR usage
        if session.ip_address and (session.ip_address.is_vpn or session.ip_address.is_tor):
            suspicious_reasons.append('vpn_tor_usage')
        
        # Update session if suspicious
        if suspicious_reasons:
            session.is_suspicious = True
            session.suspicious_reasons = suspicious_reasons
            session.save(update_fields=['is_suspicious', 'suspicious_reasons'])


class DeviceFingerprintMiddleware:
    """Middleware to collect client-side device fingerprint data"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Inject fingerprint collection script into response
        response = self.get_response(request)
        
        # Only inject for HTML responses
        if response.get('Content-Type', '').startswith('text/html'):
            # This would normally inject JavaScript for client-side fingerprinting
            # For React Native app, this would be handled differently
            pass
        
        return response