"""
Security utilities for the Confio platform
"""
import hashlib
import json
import requests
import logging
from typing import Dict, Optional, List, Tuple
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, Sum, Count, DecimalField
from django.db.models.functions import Cast
from functools import wraps

logger = logging.getLogger(__name__)


def calculate_device_fingerprint(fingerprint_data: Dict) -> str:
    """Calculate a unique hash for device fingerprint"""
    # Handle simplified deviceId-only format
    if isinstance(fingerprint_data, dict) and 'deviceId' in fingerprint_data:
        device_id = fingerprint_data['deviceId']
        return hashlib.sha256(device_id.encode()).hexdigest()
    
    # Fallback for old format
    sorted_data = json.dumps(fingerprint_data, sort_keys=True)
    return hashlib.sha256(sorted_data.encode()).hexdigest()


def check_ip_reputation(ip_address: str) -> Dict:
    """
    Check IP reputation using external services
    Returns dict with is_vpn, is_tor, is_datacenter flags
    """
    # Cache results for 24 hours
    cache_key = f"ip_reputation_{ip_address}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result
    
    result = {
        'is_vpn': False,
        'is_tor': False,
        'is_datacenter': False,
        'is_proxy': False
    }
    
    # Check against known TOR exit nodes (would normally fetch from external API)
    # For now, just check some basic patterns
    if ip_address.startswith(('10.', '172.16.', '192.168.')):
        # Private IP ranges - not VPN/TOR but suspicious for external connections
        result['is_datacenter'] = True
    
    # In production, integrate with services like:
    # - IPQualityScore
    # - MaxMind
    # - IP2Proxy
    # - AbuseIPDB
    
    cache.set(cache_key, result, 86400)  # Cache for 24 hours
    return result


# KYC REQUIREMENT CHECK - DISABLED FOR BLOCKCHAIN MVP
# This function previously enforced KYC requirements based on transaction amounts
# and cumulative monthly volumes. For a blockchain/Web3 MVP, KYC requirements
# are not appropriate as they go against the permissionless nature of crypto.
# 
# The function is being kept but commented out in case it needs to be
# re-enabled for specific jurisdictions or compliance requirements in the future.
#
# def check_kyc_required(user, operation_type: str, amount: Optional[Decimal] = None) -> Tuple[bool, str]:
#     """
#     Check if KYC is required for a specific operation
#     Returns (is_required, reason)
#     """
#     from .models import IdentityVerification
#     
#     # Check if user already has verified KYC
#     has_verified_kyc = IdentityVerification.objects.filter(
#         user=user,
#         status='verified'
#     ).exists()
#     
#     # Define KYC thresholds
#     kyc_thresholds = {
#         'send_money': Decimal('100'),  # Require KYC for sends over $100
#         'receive_money': Decimal('500'),  # Require KYC for receives over $500
#         'p2p_trade': Decimal('200'),  # Require KYC for P2P trades over $200
#         'withdrawal': Decimal('50'),  # Require KYC for any withdrawal
#         'business_account': Decimal('0'),  # Always require KYC for business accounts
#     }
#     
#     threshold = kyc_thresholds.get(operation_type, Decimal('1000'))
#     
#     if operation_type == 'withdrawal' and not has_verified_kyc:
#         return True, "KYC verification required for withdrawals"
#     
#     if operation_type == 'business_account' and not has_verified_kyc:
#         return True, "KYC verification required for business accounts"
#     
#     if amount and amount > threshold and not has_verified_kyc:
#         return True, f"KYC verification required for transactions over ${threshold}"
#     
#     # Check cumulative amounts
#     if not has_verified_kyc:
#         # Check 30-day transaction volume
#         from send.models import SendTransaction
#         from p2p_exchange.models import P2PTrade
#         
#         thirty_days_ago = timezone.now() - timedelta(days=30)
#         
#         # Calculate total volume
#         send_volume = SendTransaction.objects.filter(
#             sender_user=user,
#             created_at__gte=thirty_days_ago,
#             status='CONFIRMED'
#         ).aggregate(
#             total=Sum(Cast('amount', DecimalField(max_digits=20, decimal_places=2)))
#         )['total'] or Decimal('0')
#         
#         p2p_volume = P2PTrade.objects.filter(
#             Q(buyer_user=user) | Q(seller_user=user),
#             created_at__gte=thirty_days_ago,
#             status='COMPLETED'
#         ).aggregate(
#             total=Sum('fiat_amount')
#         )['total'] or Decimal('0')
#         
#         total_volume = send_volume + p2p_volume
#         
#         if total_volume > Decimal('1000'):
#             return True, "KYC verification required - monthly transaction limit exceeded"
#     
#     return False, ""

# Simplified version for MVP - always return False (no KYC required)
def check_kyc_required(user, operation_type: str, amount: Optional[Decimal] = None) -> Tuple[bool, str]:
    """KYC check stub for MVP - always returns False
    
    In a blockchain MVP, KYC is not required for any operations.
    This maintains the function signature for compatibility.
    """
    return False, ""


def perform_aml_check(user, transaction_type: str, amount: Decimal) -> Dict:
    """
    Perform AML (Anti-Money Laundering) check
    Returns risk assessment dict
    """
    from .models import AMLCheck, SuspiciousActivity
    from send.models import SendTransaction
    from p2p_exchange.models import P2PTrade
    
    risk_factors = {}
    risk_score = 0
    actions_required = []
    
    # Get recent transaction data
    thirty_days_ago = timezone.now() - timedelta(days=30)
    seven_days_ago = timezone.now() - timedelta(days=7)
    
    # Calculate transaction volumes
    recent_sends = SendTransaction.objects.filter(
        sender_user=user,
        created_at__gte=thirty_days_ago,
        status='CONFIRMED'
    )
    
    recent_p2p = P2PTrade.objects.filter(
        Q(buyer_user=user) | Q(seller_user=user),
        created_at__gte=thirty_days_ago,
        status='COMPLETED'
    )
    
    # Risk factor: High transaction volume
    total_volume_30d = (
        recent_sends.aggregate(total=Sum(Cast('amount', DecimalField(max_digits=20, decimal_places=2))))['total'] or Decimal('0')
    ) + (
        recent_p2p.aggregate(total=Sum('fiat_amount'))['total'] or Decimal('0')
    )
    
    if total_volume_30d > Decimal('10000'):
        risk_factors['high_volume'] = f"${total_volume_30d} in 30 days"
        risk_score += 30
    
    # Risk factor: Rapid transactions
    rapid_txns = recent_sends.filter(created_at__gte=seven_days_ago).count()
    rapid_p2p = recent_p2p.filter(created_at__gte=seven_days_ago).count()
    
    if rapid_txns + rapid_p2p > 20:
        risk_factors['rapid_transactions'] = f"{rapid_txns + rapid_p2p} in 7 days"
        risk_score += 20
    
    # Risk factor: Multiple countries
    countries = set()
    for trade in recent_p2p:
        countries.add(trade.country_code)
    
    if len(countries) > 3:
        risk_factors['multiple_countries'] = f"{len(countries)} countries"
        risk_score += 15
    
    # Risk factor: Previous suspicious activity
    previous_suspicious = SuspiciousActivity.objects.filter(
        user=user,
        status__in=['confirmed', 'investigating']
    ).count()
    
    if previous_suspicious > 0:
        risk_factors['previous_suspicious'] = f"{previous_suspicious} incidents"
        risk_score += 25
    
    # Risk factor: Large single transaction
    if amount > Decimal('5000'):
        risk_factors['large_transaction'] = f"${amount}"
        risk_score += 20
    
    # Determine actions required
    if risk_score >= 70:
        actions_required.append('manual_review')
        actions_required.append('enhanced_due_diligence')
    elif risk_score >= 50:
        actions_required.append('enhanced_monitoring')
    
    # Create AML check record
    aml_check = AMLCheck.objects.create(
        user=user,
        check_type='triggered',
        risk_score=min(risk_score, 100),
        risk_factors=risk_factors,
        transaction_volume_30d=total_volume_30d,
        transaction_count_30d=rapid_txns + rapid_p2p,
        actions_required=actions_required,
        status='pending' if risk_score >= 50 else 'cleared'
    )
    
    return {
        'risk_score': risk_score,
        'risk_factors': risk_factors,
        'actions_required': actions_required,
        'requires_review': risk_score >= 50,
        'aml_check_id': aml_check.id
    }


def check_user_banned(user) -> Tuple[bool, Optional[str]]:
    """
    Check if user is banned
    Returns (is_banned, ban_reason)
    """
    from .models import UserBan
    
    active_ban = UserBan.objects.filter(
        user=user,
        deleted_at__isnull=True
    ).exclude(
        ban_type='temporary',
        expires_at__lt=timezone.now()
    ).first()
    
    if active_ban:
        return True, active_ban.reason
    
    return False, None


def check_ip_blocked(ip_address: str) -> bool:
    """Check if IP address is blocked"""
    from .models import IPAddress
    
    try:
        ip_obj = IPAddress.objects.get(ip_address=ip_address)
        return ip_obj.is_blocked
    except IPAddress.DoesNotExist:
        return False


def create_suspicious_activity(user, activity_type: str, detection_data: Dict, 
                             severity: int = 5, related_users: List = None):
    """Create a suspicious activity record"""
    from .models import SuspiciousActivity
    
    activity = SuspiciousActivity.objects.create(
        user=user,
        activity_type=activity_type,
        detection_data=detection_data,
        severity_score=min(severity, 10),
        status='pending'
    )
    
    if related_users:
        activity.related_users.set(related_users)
    
    # Auto-escalate high severity activities
    if severity >= 8:
        activity.status = 'investigating'
        activity.save()
        
        # Notify admins
        logger.warning(f"High severity suspicious activity detected: {activity}")
    
    return activity


# Decorators for security checks

def require_kyc(operation_type: str):
    """Decorator to require KYC for specific operations"""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Extract amount if available
            amount = None
            if request.method == 'POST':
                amount = request.POST.get('amount') or request.data.get('amount')
                if amount:
                    amount = Decimal(str(amount))
            
            required, reason = check_kyc_required(request.user, operation_type, amount)
            
            if required:
                from django.http import JsonResponse
                return JsonResponse({
                    'error': 'kyc_required',
                    'message': reason
                }, status=403)
            
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_device_trust(trust_threshold: int = 3):
    """Decorator to require trusted device for sensitive operations"""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'security_user_device'):
                from django.http import JsonResponse
                return JsonResponse({
                    'error': 'device_not_tracked',
                    'message': 'Device verification required'
                }, status=403)
            
            user_device = request.security_user_device
            
            # Check if device is trusted or has enough history
            if not user_device.is_trusted and user_device.total_sessions < trust_threshold:
                from django.http import JsonResponse
                return JsonResponse({
                    'error': 'untrusted_device',
                    'message': 'This operation requires a trusted device'
                }, status=403)
            
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def track_suspicious_pattern(pattern_type: str, threshold: int = 5):
    """Decorator to track suspicious patterns in user behavior"""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Track the action
            cache_key = f"suspicious_pattern_{pattern_type}_{request.user.id}"
            count = cache.get(cache_key, 0) + 1
            cache.set(cache_key, count, 3600)  # Track for 1 hour
            
            # Check if threshold exceeded
            if count > threshold:
                create_suspicious_activity(
                    user=request.user,
                    activity_type='unusual_pattern',
                    detection_data={
                        'pattern_type': pattern_type,
                        'count': count,
                        'threshold': threshold,
                        'timeframe': '1 hour'
                    },
                    severity=min(count // threshold, 10)
                )
            
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def track_user_device(user, device_fingerprint_data: Dict, request=None):
    """
    Track user device from mobile app authentication
    Creates or updates device fingerprint and associates it with the user
    """
    from .models import DeviceFingerprint, UserDevice, IPAddress, IPDeviceUser
    
    try:
        # Calculate fingerprint hash
        fingerprint_hash = calculate_device_fingerprint(device_fingerprint_data)
        
        # Get or create device fingerprint
        device, created = DeviceFingerprint.objects.get_or_create(
            fingerprint=fingerprint_hash,
            defaults={
                'device_details': device_fingerprint_data,
                'first_seen': timezone.now(),
                'last_seen': timezone.now()
            }
        )
        
        if not created:
            device.last_seen = timezone.now()
            device.device_details = device_fingerprint_data  # Update with latest data
            device.save(update_fields=['last_seen', 'device_details'])
        
        # Get or create user-device relationship
        user_device, ud_created = UserDevice.objects.get_or_create(
            user=user,
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
        if created or ud_created:
            device.total_users = device.users.count()
            device.save(update_fields=['total_users'])
        
        # Check for suspicious device usage (too many users on same device)
        if device.total_users > 5:
            device.risk_score = min(device.risk_score + 20, 100)
            device.save(update_fields=['risk_score'])
            
            # Create suspicious activity record
            create_suspicious_activity(
                user=user,
                activity_type='multiple_accounts',
                detection_data={
                    'device_fingerprint': device.fingerprint,
                    'total_users': device.total_users,
                    'device_id': device.id
                },
                severity=min(device.total_users, 10)
            )
        
        # Track IP and create IP-Device-User association
        ip_obj = None
        if request and hasattr(request, 'META'):
            ip_str = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip_str:
                ip_str = request.META.get('REMOTE_ADDR', '')
            
            if ip_str:
                # Get or create IP address record
                ip_obj, ip_created = IPAddress.objects.get_or_create(
                    ip_address=ip_str,
                    defaults={
                        'first_seen': timezone.now(),
                        'last_seen': timezone.now(),
                        'total_users': 0
                    }
                )
                
                if not ip_created:
                    ip_obj.last_seen = timezone.now()
                    ip_obj.save(update_fields=['last_seen'])
                
                # Get or create IP-Device-User association
                ip_device_user, idu_created = IPDeviceUser.objects.get_or_create(
                    ip_address=ip_obj,
                    device_fingerprint=device,
                    user=user,
                    defaults={
                        'first_seen': timezone.now(),
                        'last_seen': timezone.now(),
                        'total_sessions': 1,
                        'auth_method': 'google'  # Default, could be passed as parameter
                    }
                )
                
                if not idu_created:
                    ip_device_user.last_seen = timezone.now()
                    ip_device_user.total_sessions += 1
                    ip_device_user.save(update_fields=['last_seen', 'total_sessions'])
                
                # Update IP total users count after creating the association
                if idu_created:
                    unique_users_on_ip = IPDeviceUser.objects.filter(
                        ip_address=ip_obj
                    ).values('user').distinct().count()
                    ip_obj.total_users = unique_users_on_ip
                    ip_obj.save(update_fields=['total_users'])
                
                # Calculate risk factors for this association
                risk_factors = ip_device_user.calculate_risk_factors()
                
                logger.info(
                    f"IP-Device-User association tracked: "
                    f"user={user.id}, device={fingerprint_hash[:8]}..., "
                    f"ip={ip_str}, new_association={idu_created}, "
                    f"risk_factors={risk_factors}"
                )
        
        logger.info(f"Device tracked for user {user.id}: fingerprint={fingerprint_hash[:10]}..., new_device={created}")
        
        return {
            'device': device,
            'user_device': user_device,
            'ip_address': ip_obj,
            'is_new_device': created,
            'is_trusted': user_device.is_trusted
        }
        
    except Exception as e:
        logger.error(f"Error tracking user device: {e}")
        raise


def get_ip_fraud_patterns(ip_address: str = None, user_id: int = None, days: int = 30) -> Dict:
    """
    Analyze IP patterns for fraud detection
    Returns fraud indicators and statistics
    """
    from .models import IPDeviceUser, IPAddress
    from django.db.models import Count, Q
    
    result = {
        'patterns': [],
        'risk_score': 0,
        'statistics': {},
        'recommendations': []
    }
    
    try:
        # Build query filters
        filters = Q()
        if ip_address:
            filters &= Q(ip_address__ip_address=ip_address)
        if user_id:
            filters &= Q(user_id=user_id)
        
        # Add time filter
        since_date = timezone.now() - timedelta(days=days)
        filters &= Q(last_seen__gte=since_date)
        
        # Get IP-Device-User associations
        associations = IPDeviceUser.objects.filter(filters).select_related(
            'ip_address', 'device_fingerprint', 'user'
        )
        
        if not associations.exists():
            return result
        
        # Pattern 1: High user count per IP
        ip_user_counts = associations.values('ip_address').annotate(
            user_count=Count('user', distinct=True)
        ).filter(user_count__gt=3)
        
        for ip_stat in ip_user_counts:
            ip_obj = IPAddress.objects.get(id=ip_stat['ip_address'])
            user_count = ip_stat['user_count']
            
            if user_count > 10:
                result['patterns'].append({
                    'type': 'high_user_count_ip',
                    'severity': 'high',
                    'description': f'IP {ip_obj.ip_address} has {user_count} different users',
                    'data': {'ip': ip_obj.ip_address, 'user_count': user_count}
                })
                result['risk_score'] += 40
            elif user_count > 5:
                result['patterns'].append({
                    'type': 'moderate_user_count_ip',
                    'severity': 'medium',
                    'description': f'IP {ip_obj.ip_address} has {user_count} different users',
                    'data': {'ip': ip_obj.ip_address, 'user_count': user_count}
                })
                result['risk_score'] += 20
        
        # Pattern 2: Multiple devices per user from same IP
        user_device_counts = associations.values('user', 'ip_address').annotate(
            device_count=Count('device_fingerprint', distinct=True)
        ).filter(device_count__gt=2)
        
        for user_stat in user_device_counts:
            device_count = user_stat['device_count']
            ip_obj = IPAddress.objects.get(id=user_stat['ip_address'])
            
            if device_count > 5:
                result['patterns'].append({
                    'type': 'multiple_devices_per_user',
                    'severity': 'high',
                    'description': f'User {user_stat["user"]} uses {device_count} devices from IP {ip_obj.ip_address}',
                    'data': {'user_id': user_stat['user'], 'device_count': device_count, 'ip': ip_obj.ip_address}
                })
                result['risk_score'] += 30
        
        # Pattern 3: Rapid location changes (if geo data available)
        suspicious_associations = associations.filter(is_suspicious=True)
        if suspicious_associations.exists():
            result['patterns'].append({
                'type': 'flagged_associations',
                'severity': 'medium',
                'description': f'{suspicious_associations.count()} suspicious IP-Device-User associations found',
                'data': {'count': suspicious_associations.count()}
            })
            result['risk_score'] += 15
        
        # Pattern 4: VPN/Tor/Datacenter usage
        risky_ips = associations.filter(
            Q(ip_address__is_vpn=True) | 
            Q(ip_address__is_tor=True) | 
            Q(ip_address__is_datacenter=True)
        ).values('ip_address__ip_address', 'ip_address__is_vpn', 'ip_address__is_tor', 'ip_address__is_datacenter').distinct()
        
        for risky_ip in risky_ips:
            risk_types = []
            if risky_ip['ip_address__is_vpn']:
                risk_types.append('VPN')
            if risky_ip['ip_address__is_tor']:
                risk_types.append('Tor')
            if risky_ip['ip_address__is_datacenter']:
                risk_types.append('Datacenter')
            
            result['patterns'].append({
                'type': 'risky_ip_usage',
                'severity': 'medium',
                'description': f'Usage from {", ".join(risk_types)} IP: {risky_ip["ip_address__ip_address"]}',
                'data': {'ip': risky_ip['ip_address__ip_address'], 'risk_types': risk_types}
            })
            result['risk_score'] += 25
        
        # Generate statistics
        result['statistics'] = {
            'total_associations': associations.count(),
            'unique_ips': associations.values('ip_address').distinct().count(),
            'unique_devices': associations.values('device_fingerprint').distinct().count(),
            'unique_users': associations.values('user').distinct().count(),
            'suspicious_count': suspicious_associations.count(),
            'risky_ip_count': risky_ips.count()
        }
        
        # Generate recommendations
        if result['risk_score'] > 80:
            result['recommendations'].append('Consider immediate manual review')
            result['recommendations'].append('Temporarily restrict high-value transactions')
        elif result['risk_score'] > 50:
            result['recommendations'].append('Enable enhanced monitoring')
            result['recommendations'].append('Require additional verification for sensitive operations')
        elif result['risk_score'] > 20:
            result['recommendations'].append('Monitor closely for additional patterns')
        
        # Cap risk score at 100
        result['risk_score'] = min(result['risk_score'], 100)
        
    except Exception as e:
        logger.error(f"Error analyzing IP fraud patterns: {e}")
        result['error'] = str(e)
    
    return result


def get_device_fraud_patterns(device_fingerprint: str = None, user_id: int = None, days: int = 30) -> Dict:
    """
    Analyze device patterns for fraud detection
    Returns fraud indicators and statistics
    """
    from .models import DeviceFingerprint, UserDevice, IPDeviceUser
    from django.db.models import Count, Q
    
    result = {
        'patterns': [],
        'risk_score': 0,
        'statistics': {},
        'recommendations': []
    }
    
    try:
        # Build query filters
        filters = Q()
        if device_fingerprint:
            filters &= Q(device_fingerprint__fingerprint=device_fingerprint)
        if user_id:
            filters &= Q(user_id=user_id)
        
        # Add time filter
        since_date = timezone.now() - timedelta(days=days)
        filters &= Q(last_seen__gte=since_date)
        
        # Get device associations
        associations = IPDeviceUser.objects.filter(filters).select_related(
            'device_fingerprint', 'user', 'ip_address'
        )
        
        if not associations.exists():
            return result
        
        # Pattern 1: Device used by multiple users
        device_user_counts = associations.values('device_fingerprint').annotate(
            user_count=Count('user', distinct=True)
        ).filter(user_count__gt=1)
        
        for device_stat in device_user_counts:
            device_obj = DeviceFingerprint.objects.get(id=device_stat['device_fingerprint'])
            user_count = device_stat['user_count']
            
            if user_count > 5:
                result['patterns'].append({
                    'type': 'high_user_count_device',
                    'severity': 'high',
                    'description': f'Device {device_obj.fingerprint[:16]}... used by {user_count} users',
                    'data': {'device_fingerprint': device_obj.fingerprint, 'user_count': user_count}
                })
                result['risk_score'] += 50
            elif user_count > 2:
                result['patterns'].append({
                    'type': 'moderate_user_count_device',
                    'severity': 'medium',
                    'description': f'Device {device_obj.fingerprint[:16]}... used by {user_count} users',
                    'data': {'device_fingerprint': device_obj.fingerprint, 'user_count': user_count}
                })
                result['risk_score'] += 30
        
        # Pattern 2: Device used from multiple IPs rapidly
        device_ip_counts = associations.values('device_fingerprint').annotate(
            ip_count=Count('ip_address', distinct=True)
        ).filter(ip_count__gt=3)
        
        for device_stat in device_ip_counts:
            device_obj = DeviceFingerprint.objects.get(id=device_stat['device_fingerprint'])
            ip_count = device_stat['ip_count']
            
            result['patterns'].append({
                'type': 'multiple_ip_device',
                'severity': 'medium',
                'description': f'Device {device_obj.fingerprint[:16]}... used from {ip_count} different IPs',
                'data': {'device_fingerprint': device_obj.fingerprint, 'ip_count': ip_count}
            })
            result['risk_score'] += 20
        
        # Generate statistics
        result['statistics'] = {
            'total_associations': associations.count(),
            'unique_devices': associations.values('device_fingerprint').distinct().count(),
            'unique_users': associations.values('user').distinct().count(),
            'unique_ips': associations.values('ip_address').distinct().count()
        }
        
        # Generate recommendations based on risk score
        if result['risk_score'] > 70:
            result['recommendations'].append('Immediate device investigation required')
            result['recommendations'].append('Consider blocking device for high-value operations')
        elif result['risk_score'] > 40:
            result['recommendations'].append('Enhanced device monitoring required')
            result['recommendations'].append('Require additional verification on this device')
        elif result['risk_score'] > 20:
            result['recommendations'].append('Monitor device usage patterns')
        
        # Cap risk score at 100
        result['risk_score'] = min(result['risk_score'], 100)
        
    except Exception as e:
        logger.error(f"Error analyzing device fraud patterns: {e}")
        result['error'] = str(e)
    
    return result


def get_user_fraud_patterns(user_id: int, days: int = 30) -> Dict:
    """
    Analyze user patterns across all IPs and devices for fraud detection
    Returns comprehensive fraud assessment
    """
    from .models import IPDeviceUser, SuspiciousActivity
    from django.db.models import Count, Q
    
    result = {
        'patterns': [],
        'risk_score': 0,
        'statistics': {},
        'recommendations': []
    }
    
    try:
        # Get user's associations
        since_date = timezone.now() - timedelta(days=days)
        associations = IPDeviceUser.objects.filter(
            user_id=user_id,
            last_seen__gte=since_date
        ).select_related('ip_address', 'device_fingerprint')
        
        if not associations.exists():
            return result
        
        # Pattern 1: User using too many devices
        device_count = associations.values('device_fingerprint').distinct().count()
        if device_count > 5:
            result['patterns'].append({
                'type': 'excessive_device_usage',
                'severity': 'high',
                'description': f'User uses {device_count} different devices',
                'data': {'device_count': device_count}
            })
            result['risk_score'] += 40
        elif device_count > 3:
            result['patterns'].append({
                'type': 'moderate_device_usage',
                'severity': 'medium',
                'description': f'User uses {device_count} different devices',
                'data': {'device_count': device_count}
            })
            result['risk_score'] += 20
        
        # Pattern 2: User connecting from too many IPs
        ip_count = associations.values('ip_address').distinct().count()
        if ip_count > 10:
            result['patterns'].append({
                'type': 'excessive_ip_usage',
                'severity': 'high',
                'description': f'User connects from {ip_count} different IPs',
                'data': {'ip_count': ip_count}
            })
            result['risk_score'] += 35
        elif ip_count > 5:
            result['patterns'].append({
                'type': 'moderate_ip_usage',
                'severity': 'medium',
                'description': f'User connects from {ip_count} different IPs',
                'data': {'ip_count': ip_count}
            })
            result['risk_score'] += 15
        
        # Pattern 3: Check for existing suspicious activities
        suspicious_activities = SuspiciousActivity.objects.filter(
            user_id=user_id,
            created_at__gte=since_date,
            status__in=['pending', 'investigating', 'confirmed']
        ).count()
        
        if suspicious_activities > 0:
            result['patterns'].append({
                'type': 'existing_suspicious_activities',
                'severity': 'high',
                'description': f'{suspicious_activities} suspicious activities in {days} days',
                'data': {'activity_count': suspicious_activities}
            })
            result['risk_score'] += 30
        
        # Pattern 4: Shared devices with other users
        shared_devices = associations.filter(
            device_fingerprint__total_users__gt=1
        ).count()
        
        if shared_devices > 0:
            result['patterns'].append({
                'type': 'shared_device_usage',
                'severity': 'medium',
                'description': f'User uses {shared_devices} devices shared with other users',
                'data': {'shared_device_count': shared_devices}
            })
            result['risk_score'] += 25
        
        # Generate statistics
        result['statistics'] = {
            'total_associations': associations.count(),
            'unique_devices': device_count,
            'unique_ips': ip_count,
            'shared_devices': shared_devices,
            'suspicious_activities': suspicious_activities,
            'total_sessions': sum(a.total_sessions for a in associations)
        }
        
        # Generate recommendations
        if result['risk_score'] > 80:
            result['recommendations'].append('Immediate account review required')
            result['recommendations'].append('Restrict high-value operations')
            result['recommendations'].append('Require enhanced verification')
        elif result['risk_score'] > 50:
            result['recommendations'].append('Enhanced monitoring required')
            result['recommendations'].append('Additional verification for sensitive operations')
        elif result['risk_score'] > 25:
            result['recommendations'].append('Monitor account activity closely')
        
        # Cap risk score at 100
        result['risk_score'] = min(result['risk_score'], 100)
        
    except Exception as e:
        logger.error(f"Error analyzing user fraud patterns: {e}")
        result['error'] = str(e)
    
    return result