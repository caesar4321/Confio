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
    # Sort keys to ensure consistent hashing
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
    from .models import DeviceFingerprint, UserDevice, IPAddress
    
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
        
        # Track IP if available from request
        if request and hasattr(request, 'META'):
            ip_str = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip_str:
                ip_str = request.META.get('REMOTE_ADDR', '')
            
            if ip_str:
                ip_obj, _ = IPAddress.objects.get_or_create(
                    ip_address=ip_str,
                    defaults={
                        'first_seen': timezone.now(),
                        'last_seen': timezone.now()
                    }
                )
                ip_obj.last_seen = timezone.now()
                ip_obj.save(update_fields=['last_seen'])
        
        logger.info(f"Device tracked for user {user.id}: fingerprint={fingerprint_hash[:10]}..., new_device={created}")
        
        return {
            'device': device,
            'user_device': user_device,
            'is_new_device': created,
            'is_trusted': user_device.is_trusted
        }
        
    except Exception as e:
        logger.error(f"Error tracking user device: {e}")
        raise