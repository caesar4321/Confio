"""
Decorators for abuse prevention and rate limiting
"""
from functools import wraps
from typing import Dict, Any
from graphql import GraphQLError
from .abuse_prevention import AbusePreventionService
import logging

logger = logging.getLogger(__name__)


def rate_limit(action: str):
    """
    Decorator to apply rate limiting to GraphQL mutations
    
    Usage:
        @rate_limit('referral_submit')
        def mutate(cls, root, info, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract info object (usually 3rd argument)
            info = args[2] if len(args) > 2 else kwargs.get('info')
            if not info:
                raise GraphQLError("Missing context information")
            
            # Get user from context
            user = getattr(info.context, 'user', None)
            if not user or not getattr(user, 'is_authenticated', False):
                raise GraphQLError("Authentication required")
            
            # Check rate limit
            is_allowed, seconds_until_reset = AbusePreventionService.check_rate_limit(
                user.id, action
            )
            
            if not is_allowed:
                minutes = seconds_until_reset // 60
                raise GraphQLError(
                    f"Rate limit exceeded. Please try again in {minutes} minutes."
                )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def check_suspicious_activity(action: str):
    """
    Decorator to check for suspicious patterns in GraphQL mutations
    
    Usage:
        @check_suspicious_activity('referral_submit')
        def mutate(cls, root, info, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract info object
            info = args[2] if len(args) > 2 else kwargs.get('info')
            if not info:
                raise GraphQLError("Missing context information")
            
            # Get user from context
            user = getattr(info.context, 'user', None)
            if not user or not getattr(user, 'is_authenticated', False):
                raise GraphQLError("Authentication required")
            
            # Build metadata from request
            metadata = {
                'ip_address': getattr(info.context, 'META', {}).get('REMOTE_ADDR'),
                'user_agent': getattr(info.context, 'META', {}).get('HTTP_USER_AGENT'),
            }
            
            # Add device fingerprint if available
            if hasattr(info.context, 'device_fingerprint'):
                metadata['device_fingerprint'] = info.context.device_fingerprint
            
            # Add action-specific metadata
            if action == 'referral_submit' and 'tiktok_username' in kwargs:
                metadata['referred_username'] = kwargs['tiktok_username']
            
            # Check for suspicious patterns
            flags = AbusePreventionService.check_suspicious_patterns(
                user, action, metadata
            )
            
            # Log if suspicious
            if flags:
                AbusePreventionService.log_suspicious_activity(
                    user, action, flags, metadata
                )
                
                # Block certain critical flags
                critical_flags = ['multiple_accounts_per_device']
                if any(flag in critical_flags for flag in flags):
                    raise GraphQLError(
                        "Suspicious activity detected. Please contact support."
                    )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_trust_score(minimum_score: int = 30):
    """
    Decorator to require minimum trust score for sensitive operations
    
    Usage:
        @require_trust_score(50)
        def mutate(cls, root, info, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract info object
            info = args[2] if len(args) > 2 else kwargs.get('info')
            if not info:
                raise GraphQLError("Missing context information")
            
            # Get user from context
            user = getattr(info.context, 'user', None)
            if not user or not getattr(user, 'is_authenticated', False):
                raise GraphQLError("Authentication required")
            
            # Calculate trust score
            trust_score = AbusePreventionService.calculate_trust_score(user)
            
            if trust_score < minimum_score:
                requirements = AbusePreventionService.check_activity_requirements(user)
                missing = [k for k, v in requirements.items() if not v]
                
                message = f"Your account trust score ({trust_score}) is below the required minimum ({minimum_score}). "
                if missing:
                    message += f"Missing requirements: {', '.join(missing)}"
                
                raise GraphQLError(message)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def check_activity_requirements(*required_fields):
    """
    Decorator to check specific activity requirements
    
    Usage:
        @check_activity_requirements('email_verified', 'has_transactions')
        def mutate(cls, root, info, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract info object
            info = args[2] if len(args) > 2 else kwargs.get('info')
            if not info:
                raise GraphQLError("Missing context information")
            
            # Get user from context
            user = getattr(info.context, 'user', None)
            if not user or not getattr(user, 'is_authenticated', False):
                raise GraphQLError("Authentication required")
            
            # Check requirements
            requirements = AbusePreventionService.check_activity_requirements(user)
            
            missing = []
            for field in required_fields:
                if field in requirements and not requirements[field]:
                    missing.append(field)
            
            if missing:
                friendly_names = {
                    'account_age': 'Account must be at least 7 days old',
                    'email_verified': 'Email verification required',
                    'phone_verified': 'Phone verification required',
                    'has_transactions': 'Previous transaction history required',
                    'kyc_verified': 'KYC verification required',
                }
                
                missing_friendly = [friendly_names.get(f, f) for f in missing]
                raise GraphQLError(
                    f"Requirements not met: {', '.join(missing_friendly)}"
                )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def log_achievement_activity(achievement_type: str):
    """
    Decorator to log achievement-related activities
    
    Usage:
        @log_achievement_activity('referral')
        def mutate(cls, root, info, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Extract info object
            info = args[2] if len(args) > 2 else kwargs.get('info')
            if info:
                user = getattr(info.context, 'user', None)
                if user and getattr(user, 'is_authenticated', False):
                    logger.info(
                        f"Achievement activity: user={user.id}, "
                        f"type={achievement_type}, "
                        f"ip={getattr(info.context, 'META', {}).get('REMOTE_ADDR')}"
                    )
            
            return result
        
        return wrapper
    return decorator