"""
Abuse prevention mechanisms for achievement and referral systems
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class AbusePreventionService:
    """Central service for detecting and preventing abuse in the achievement system"""
    
    # Rate limiting constants
    RATE_LIMITS = {
        'referral_submit': {'window': 3600, 'max_attempts': 5},  # 5 referrals per hour
        'achievement_claim': {'window': 86400, 'max_attempts': 50},  # 50 achievements per day
        'tiktok_share': {'window': 3600, 'max_attempts': 10},  # 10 shares per hour
        'reward_claim': {'window': 86400, 'max_attempts': 100},  # 100 rewards per day
    }
    
    # Suspicious activity thresholds
    SUSPICIOUS_THRESHOLDS = {
        'rapid_referrals': {'window': 300, 'max_count': 3},  # 3 referrals in 5 minutes
        'duplicate_devices': {'window': 86400, 'max_count': 3},  # 3 accounts per device per day
        'similar_usernames': {'threshold': 0.8},  # 80% similarity
        'transaction_velocity': {'window': 3600, 'min_amount': 100},  # $100/hour
    }
    
    @classmethod
    def check_rate_limit(cls, user_id: int, action: str) -> Tuple[bool, Optional[int]]:
        """
        Check if user has exceeded rate limit for an action
        Returns: (is_allowed, seconds_until_reset)
        """
        if action not in cls.RATE_LIMITS:
            return True, None
            
        config = cls.RATE_LIMITS[action]
        cache_key = f"rate_limit:{action}:{user_id}"
        
        # Get current count
        current_data = cache.get(cache_key, {'count': 0, 'window_start': timezone.now()})
        
        # Check if window has expired
        window_start = current_data['window_start']
        if isinstance(window_start, str):
            window_start = datetime.fromisoformat(window_start)
        
        if timezone.now() - window_start > timedelta(seconds=config['window']):
            # Reset window
            current_data = {'count': 0, 'window_start': timezone.now()}
        
        # Check limit
        if current_data['count'] >= config['max_attempts']:
            seconds_until_reset = config['window'] - (timezone.now() - window_start).total_seconds()
            return False, int(seconds_until_reset)
        
        # Increment count
        current_data['count'] += 1
        cache.set(cache_key, current_data, config['window'])
        
        return True, None
    
    @classmethod
    def get_device_fingerprint(cls, request_data: Dict) -> str:
        """Generate a device fingerprint from request data"""
        # Combine various device attributes
        fingerprint_data = {
            'user_agent': request_data.get('user_agent', ''),
            'ip_address': request_data.get('ip_address', ''),
            'screen_resolution': request_data.get('screen_resolution', ''),
            'timezone': request_data.get('timezone', ''),
            'language': request_data.get('language', ''),
            'platform': request_data.get('platform', ''),
        }
        
        # Create hash of device data
        fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()
    
    @classmethod
    def check_device_limit(cls, device_fingerprint: str, user_id: int) -> bool:
        """Check if device has too many associated accounts"""
        if not device_fingerprint:
            return True

        # First, consult persistent device usage to catch lifetime device sharing
        try:
            from security.models import DeviceFingerprint
            threshold = cls.SUSPICIOUS_THRESHOLDS['duplicate_devices']
            device = DeviceFingerprint.objects.filter(
                fingerprint=device_fingerprint
            ).only('total_users').first()
            if device and device.total_users > threshold['max_count']:
                return False
        except Exception:
            # If DB lookup fails, fall back to cache-only behavior
            logger.warning("Device limit DB lookup failed", exc_info=True)

        cache_key = f"device_accounts:{device_fingerprint}"
        
        # Get current accounts for this device
        device_data = cache.get(cache_key, {'accounts': set(), 'timestamp': timezone.now()})
        
        # Check if data is expired (24 hours)
        if timezone.now() - device_data['timestamp'] > timedelta(days=1):
            device_data = {'accounts': set(), 'timestamp': timezone.now()}
        
        # Add current user
        device_data['accounts'].add(user_id)
        
        # Check threshold
        threshold = cls.SUSPICIOUS_THRESHOLDS['duplicate_devices']
        if len(device_data['accounts']) > threshold['max_count']:
            return False
        
        # Update cache
        cache.set(cache_key, device_data, 86400)  # 24 hours
        return True
    
    @classmethod
    def check_referral_velocity(cls, user_id: int) -> bool:
        """Check if user is submitting referrals too quickly"""
        cache_key = f"referral_velocity:{user_id}"
        
        # Get recent referrals
        recent_referrals = cache.get(cache_key, [])
        current_time = timezone.now()
        
        # Filter referrals within window
        threshold = cls.SUSPICIOUS_THRESHOLDS['rapid_referrals']
        window_start = current_time - timedelta(seconds=threshold['window'])
        recent_referrals = [r for r in recent_referrals if r > window_start]
        
        # Check threshold
        if len(recent_referrals) >= threshold['max_count']:
            return False
        
        # Add current referral
        recent_referrals.append(current_time)
        cache.set(cache_key, recent_referrals, threshold['window'])
        
        return True
    
    @classmethod
    def check_username_similarity(cls, username1: str, username2: str) -> float:
        """Calculate similarity between two usernames using Levenshtein distance"""
        if not username1 or not username2:
            return 0.0
            
        # Convert to lowercase for comparison
        username1 = username1.lower()
        username2 = username2.lower()
        
        # Calculate Levenshtein distance
        if len(username1) < len(username2):
            username1, username2 = username2, username1
        
        if len(username2) == 0:
            return 0.0
        
        previous_row = range(len(username2) + 1)
        for i, c1 in enumerate(username1):
            current_row = [i + 1]
            for j, c2 in enumerate(username2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        # Calculate similarity score
        max_len = max(len(username1), len(username2))
        similarity = 1 - (previous_row[-1] / max_len)
        
        return similarity
    
    @classmethod
    def check_suspicious_patterns(cls, user, action: str, metadata: Dict) -> List[str]:
        """Check for various suspicious patterns and return list of flags"""
        flags = []

        # Check device limits (prefer stored device fingerprint if none provided)
        device_fingerprint = metadata.get('device_fingerprint')
        if not device_fingerprint:
            device_fingerprint = cls.get_latest_device_fingerprint_for_user(user)
            if device_fingerprint:
                metadata['device_fingerprint'] = device_fingerprint

        if device_fingerprint:
            if not cls.check_device_limit(device_fingerprint, user.id):
                flags.append('multiple_accounts_per_device')
        
        # Check referral velocity
        if action == 'referral_submit':
            if not cls.check_referral_velocity(user.id):
                flags.append('rapid_referral_submission')
        
        # Check for similar usernames in recent referrals
        if action == 'referral_submit' and 'referred_username' in metadata:
            # Get recent referrals from cache
            cache_key = f"recent_referrals:{user.id}"
            recent_referrals = cache.get(cache_key, [])
            
            for ref_username in recent_referrals:
                similarity = cls.check_username_similarity(
                    metadata['referred_username'], 
                    ref_username
                )
                if similarity > cls.SUSPICIOUS_THRESHOLDS['similar_usernames']['threshold']:
                    flags.append('similar_usernames_detected')
                    break
            
            # Update cache
            recent_referrals.append(metadata['referred_username'])
            recent_referrals = recent_referrals[-10:]  # Keep last 10
            cache.set(cache_key, recent_referrals, 86400)
        
        # Check transaction velocity for high-value activities
        if 'transaction_amount' in metadata:
            cache_key = f"transaction_velocity:{user.id}"
            hourly_total = cache.get(cache_key, 0)
            
            threshold = cls.SUSPICIOUS_THRESHOLDS['transaction_velocity']
            if hourly_total + metadata['transaction_amount'] > threshold['min_amount']:
                flags.append('high_transaction_velocity')
            
            # Update cache
            cache.set(cache_key, hourly_total + metadata['transaction_amount'], 3600)
        
        return flags

    @classmethod
    def get_latest_device_fingerprint_for_user(cls, user) -> Optional[str]:
        """Fetch the most recently used device fingerprint hash for a user"""
        try:
            from security.models import UserDevice
            user_device = (
                UserDevice.objects.filter(user=user)
                .select_related('device')
                .order_by('-last_used', '-first_used')
                .first()
            )
            if user_device and user_device.device:
                return user_device.device.fingerprint
        except Exception:
            logger.warning("Could not fetch latest device fingerprint for user %s", getattr(user, 'id', None), exc_info=True)
        return None
    
    @classmethod
    def log_suspicious_activity(cls, user, action: str, flags: List[str], metadata: Dict):
        """Log suspicious activity for review"""
        from security.models import SuspiciousActivity
        # Map generic flags/actions to SuspiciousActivity fields
        # Choose a primary activity_type based on known flags
        activity_type = 'unusual_pattern'
        if 'multiple_accounts_per_device' in flags:
            activity_type = 'duplicate_device'
        elif 'rapid_referral_submission' in flags:
            activity_type = 'rapid_referrals'

        # Build detection payload with rich context
        detection_payload = {
            'action': action,
            'flags': flags,
            'metadata': metadata,
            'ip_address': metadata.get('ip_address'),
            'device_fingerprint': metadata.get('device_fingerprint'),
        }

        try:
            SuspiciousActivity.objects.create(
                user=user,
                activity_type=activity_type,
                detection_data=detection_payload,
                severity_score=max(1, min(10, len(flags) or 1)),
                related_ips=[metadata.get('ip_address')] if metadata.get('ip_address') else [],
            )
        except Exception:
            # Never block business logic due to logging errors
            logger = logging.getLogger(__name__)
            logger.warning('Failed to log suspicious activity', exc_info=True)
        
        # Alert admins if critical flags
        critical_flags = ['multiple_accounts_per_device', 'high_transaction_velocity']
        if any(flag in critical_flags for flag in flags):
            logger.warning(
                f"Critical suspicious activity detected for user {user.id}: "
                f"action={action}, flags={flags}"
            )
    
    @classmethod
    def check_activity_requirements(cls, user) -> Dict[str, bool]:
        """Check if user meets minimum activity requirements"""
        from .models import Account
        from p2p_exchange.models import P2PTrade
        from send.models import SendTransaction
        
        requirements = {
            'account_age': False,
            'email_verified': False,
            'phone_verified': False,
            'has_transactions': False,
            'kyc_verified': False,
        }
        
        # Check account age (minimum 7 days)
        if user.created_at <= timezone.now() - timedelta(days=7):
            requirements['account_age'] = True
        
        # Check verifications
        requirements['email_verified'] = bool(user.email)
        requirements['phone_verified'] = bool(user.phone_number)
        
        # Check for real transactions
        has_p2p = P2PTrade.objects.filter(
            models.Q(buyer=user) | models.Q(seller=user),
            status='completed'
        ).exists()
        
        has_send = SendTransaction.objects.filter(
            sender_user=user,
            status='CONFIRMED'
        ).exists()
        
        requirements['has_transactions'] = has_p2p or has_send
        
        # Check KYC
        requirements['kyc_verified'] = user.security_verifications.filter(
            status='verified'
        ).exists()
        
        return requirements
    
    @classmethod
    def calculate_trust_score(cls, user) -> int:
        """Calculate user trust score (0-100)"""
        score = 0
        
        # Get activity requirements
        requirements = cls.check_activity_requirements(user)
        
        # Account age (20 points)
        if requirements['account_age']:
            account_days = (timezone.now() - user.created_at).days
            score += min(20, account_days // 7)  # Max 20 points
        
        # Verifications (30 points total)
        if requirements['email_verified']:
            score += 10
        if requirements['phone_verified']:
            score += 10
        if requirements['kyc_verified']:
            score += 10
        
        # Transaction history (30 points)
        if requirements['has_transactions']:
            from p2p_exchange.models import P2PTrade
            
            # Count completed trades
            trade_count = P2PTrade.objects.filter(
                models.Q(buyer=user) | models.Q(seller=user),
                status='completed'
            ).count()
            
            score += min(30, trade_count * 3)  # 3 points per trade, max 30
        
        # No suspicious activity (20 points)
        from security.models import SuspiciousActivity
        
        suspicious_count = SuspiciousActivity.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        if suspicious_count == 0:
            score += 20
        elif suspicious_count < 3:
            score += 10
        
        return min(100, score)
