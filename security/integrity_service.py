"""
Firebase App Check Token Verification Service

Verifies App Check tokens from both Android (Play Integrity) and iOS (App Attest)
using Firebase Admin SDK for unified backend verification.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import timedelta

from django.utils import timezone
from django.conf import settings

from firebase_admin import app_check, initialize_app as firebase_init, get_app
from firebase_admin.credentials import Certificate

from .models import IntegrityVerdict

logger = logging.getLogger(__name__)


def get_firebase_app():
    """Get or initialize Firebase Admin app."""
    try:
        return get_app()
    except ValueError:
        # App not initialized, initialize it
        creds_path = getattr(settings, 'GOOGLE_APPLICATION_CREDENTIALS', None)
        if creds_path:
            cred = Certificate(creds_path)
            return firebase_init(credential=cred)
        else:
            # Try default credentials
            return firebase_init()


class AppCheckService:
    """
    Service for verifying Firebase App Check tokens.
    
    Unified verification for both Android and iOS:
    - Android: Tokens come from Play Integrity provider
    - iOS: Tokens come from App Attest provider
    """
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a Firebase App Check token.
        
        Returns:
            dict with 'valid', 'app_id', and 'error' fields
        """
        try:
            # Ensure Firebase is initialized
            get_firebase_app()
            
            # Verify the token
            claims = app_check.verify_token(token)
            
            app_id = claims.get('app_id', claims.get('sub'))
            
            return {
                'valid': True,
                'app_id': app_id,
                'claims': claims,
            }
            
        except app_check.InvalidTokenError as e:
            logger.warning(f"[AppCheck] Invalid token: {e}")
            return {
                'valid': False,
                'error': 'INVALID_TOKEN',
            }
        except Exception as e:
            logger.error(f"[AppCheck] Verification error: {e}")
            return {
                'valid': False,
                'error': str(e),
            }

    def verify_and_record(
        self,
        user,
        token: str,
        action: str,
        device_fingerprint: str = '',
        should_enforce: bool = False
    ) -> Dict[str, Any]:
        """
        Full verification flow:
        1. Verify the App Check token
        2. Record the result in database
        3. Check historical violations
        
        Args:
            should_enforce: If True, returns success=False when check fails (Blocking Mode).
                          If False, returns success=True even if check fails (Warning Mode).
        
        Returns dict with verification result.
        """
        if not token:
             # If no token provided
            verdict = IntegrityVerdict.objects.create(
                user=user,
                device_fingerprint=device_fingerprint,
                app_recognition='FIREBASE_APP_CHECK',
                app_licensing='MISSING_TOKEN',
                passed=False,
                trigger_action=action,
                error_message='Token not provided'
            )
            passed = False
            has_historical_violation = IntegrityVerdict.has_historical_violation(user)
            
            is_blocked = should_enforce
            
            logger.warning(f"[AppCheck] User {user.id} - Action: {action} - Missing Token - Blocked: {is_blocked}")
            
            return {
                'success': not is_blocked,
                'passed': False,
                'is_blocked': is_blocked,
                'has_historical_violation': has_historical_violation,
                'verdict_id': verdict.id,
                'error': 'Missing App Check Token'
            }

        # Verify token
        verification = self.verify_token(token)
        passed = verification.get('valid', False)
        
        # Record the verdict
        verdict = IntegrityVerdict.objects.create(
            user=user,
            device_fingerprint=device_fingerprint,
            app_recognition='FIREBASE_APP_CHECK',
            device_integrity=[], 
            app_licensing='VERIFIED' if passed else 'UNVERIFIED',
            is_emulator=False,
            is_rooted=False,
            passed=passed,
            trigger_action=action,
            raw_response=verification,
            error_message=verification.get('error', '') or '',
        )
        
        # Check historical violations
        has_historical_violation = IntegrityVerdict.has_historical_violation(user)
        
        # Determine blocking
        # Logic: If enforcement is ON, block if check failed.
        # Historical violations could also trigger blocking if desired, but for now strict token check.
        is_blocked = should_enforce and (not passed)
        
        result = {
            'success': not is_blocked,
            'passed': passed,
            'is_blocked': is_blocked,
            'has_historical_violation': has_historical_violation,
            'verdict_id': verdict.id,
            'error': verification.get('error') if not passed else None
        }
        
        # Log result
        if not passed:
            logger.warning(
                f"[AppCheck] User {user.id} - Action: {action} - "
                f"Passed: {passed}, Blocked: {is_blocked}"
            )
        else:
            logger.info(f"[AppCheck] User {user.id} - Action: {action} - Passed")
        
        return result

    def verify_request_header(self, request, action: str, should_enforce: bool = False):
        """
        Helper to verify App Check token from Django request header X-Firebase-AppCheck.
        """
        # Allow bypassing check if already verified upstream (e.g. WebSocket connect)
        if getattr(request, '_app_check_verified', False):
            return {'success': True, 'passed': True}

        token = request.headers.get('X-Firebase-AppCheck', '')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            # Anonymous verification (limited utility but possible)
            # For now return success to avoid breaking anon flows unless we want to enforce
            return {'success': True, 'passed': False}
            
        return self.verify_and_record(
            user=user,
            token=token,
            action=action,
            should_enforce=should_enforce
        )

    def can_claim_reward(self, user) -> Tuple[bool, Optional[str]]:
        """
        Check if a user can claim rewards based on their integrity history.
        
        Returns:
            (can_claim, error_message)
        """
        # Check for historical violations
        if IntegrityVerdict.has_historical_violation(user):
            logger.warning(
                f"[AppCheck] User {user.id} has integrity violation history "
                "but allowing reward claim (monitoring mode)"
            )
            return True, None  # Change to (False, error_message) when enabling blocking
        
        return True, None


# Singleton instance
app_check_service = AppCheckService()
