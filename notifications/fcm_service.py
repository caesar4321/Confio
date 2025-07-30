"""
Firebase Cloud Messaging service for push notifications
"""
import os
import json
import logging
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.utils import timezone

import firebase_admin
from firebase_admin import credentials, messaging
from firebase_admin.exceptions import FirebaseError

from .models import FCMDeviceToken, NotificationPreference
from django.db import models

logger = logging.getLogger(__name__)

# Check Firebase initialization
def check_firebase_initialized():
    """Check if Firebase Admin SDK is already initialized"""
    try:
        # Check if already initialized
        firebase_admin.get_app()
        logger.info("Firebase Admin SDK already initialized")
        return True
    except ValueError:
        # Not initialized
        logger.error("Firebase Admin SDK not initialized. Please check config/settings.py")
        return False


# Check on module load
FIREBASE_INITIALIZED = check_firebase_initialized()


def send_push_notification(
    notification,
    additional_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send push notification for a Notification model instance
    
    Args:
        notification: Notification model instance
        additional_data: Additional data to include in the push
    
    Returns:
        Dict with send results
    """
    if not FIREBASE_INITIALIZED:
        logger.warning("Firebase not initialized. Skipping push notification.")
        return {'success': False, 'error': 'Firebase not initialized'}
    
    if notification.is_broadcast:
        return send_broadcast_push(notification, additional_data)
    else:
        return send_user_push(notification, additional_data)


def send_user_push(
    notification,
    additional_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Send push notification to a specific user using batch send"""
    user = notification.user
    if not user:
        return {'success': False, 'error': 'No user specified'}
    
    # Check user preferences
    try:
        prefs = user.notification_preferences
        if not prefs.push_enabled:
            logger.info(f"Push notifications disabled for user {user.id}")
            return {'success': False, 'error': 'Push notifications disabled by user'}
        
        # Check category-specific preferences
        if not should_send_push(prefs, notification.notification_type):
            logger.info(f"Push notifications disabled for type {notification.notification_type}")
            return {'success': False, 'error': 'Push notifications disabled for this type'}
    
    except NotificationPreference.DoesNotExist:
        # No preferences = send by default
        pass
    
    # Get active FCM tokens for user with their IDs
    token_data = list(FCMDeviceToken.objects.filter(
        user=user,
        is_active=True
    ).values_list('token', 'id'))
    
    if not token_data:
        logger.info(f"No active FCM tokens for user {user.id}")
        return {'success': False, 'error': 'No active FCM tokens'}
    
    # Prepare notification data
    push_data = prepare_push_data(notification, additional_data)
    
    # Get unread count for badge
    unread_count = user.notifications.filter(is_read=False).count()
    
    # Use batch send for all tokens (even if just 1)
    return send_batch_notifications(
        tokens=token_data,
        title=notification.title,
        body=notification.message,
        data=push_data,
        badge_count=unread_count,
        notification=notification
    )


def send_broadcast_push(
    notification,
    additional_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Send broadcast push notification to multiple users using batch send"""
    tokens_query = FCMDeviceToken.objects.filter(is_active=True)
    
    # Filter by target audience
    if notification.broadcast_target == 'verified':
        tokens_query = tokens_query.filter(user__is_verified=True)
    elif notification.broadcast_target == 'business':
        tokens_query = tokens_query.filter(
            user__business_accounts__isnull=False
        ).distinct()
    
    # Check preferences for each user
    valid_tokens = []
    for token in tokens_query.select_related('user'):
        try:
            prefs = token.user.notification_preferences
            if prefs.push_enabled and prefs.push_announcements:
                valid_tokens.append((token.token, token.id))
        except NotificationPreference.DoesNotExist:
            # No preferences = send by default
            valid_tokens.append((token.token, token.id))
    
    if not valid_tokens:
        return {'success': False, 'error': 'No valid tokens for broadcast'}
    
    # Prepare notification data
    push_data = prepare_push_data(notification, additional_data)
    
    # Use batch send for all tokens
    return send_batch_notifications(
        tokens=valid_tokens,
        title=notification.title,
        body=notification.message,
        data=push_data,
        badge_count=None,  # No badge for broadcasts
        notification=notification,
        channel_id='announcements'
    )


def send_batch_notifications(
    tokens: List[tuple],
    title: str,
    body: str,
    data: Dict[str, str],
    badge_count: Optional[int] = None,
    notification = None,
    channel_id: str = 'default'
) -> Dict[str, Any]:
    """
    Send notifications using FCM batch send (multicast)
    
    Args:
        tokens: List of (token, token_id) tuples
        title: Notification title
        body: Notification body
        data: Notification data payload
        badge_count: Badge count for iOS/Android
        notification: Notification model instance (optional)
        channel_id: Android notification channel
    
    Returns:
        Dict with send results
    """
    results = {
        'success': False,
        'sent': 0,
        'failed': 0,
        'errors': [],
        'invalid_tokens': []
    }
    
    # Split tokens into batches of 500 (FCM limit)
    for i in range(0, len(tokens), 500):
        batch_tokens = tokens[i:i+500]
        tokens_only = [t[0] for t in batch_tokens]
        
        # Build Android config
        android_notification = messaging.AndroidNotification(
            title=title,
            body=body,
            sound='default',
            channel_id=channel_id
        )
        
        if badge_count is not None:
            android_notification.notification_count = badge_count
        
        android_config = messaging.AndroidConfig(
            priority='high',
            notification=android_notification,
            data=data
        )
        
        # Build iOS config
        aps = messaging.Aps(
            alert=messaging.ApsAlert(
                title=title,
                body=body
            ),
            sound='default',
            content_available=True
        )
        
        if badge_count is not None:
            aps.badge = badge_count
        
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(aps=aps),
            headers={
                'apns-priority': '10',
                'apns-push-type': 'alert'
            }
        )
        
        # Create multicast message
        multicast_message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=data,
            tokens=tokens_only,
            android=android_config,
            apns=apns_config
        )
        
        try:
            batch_response = messaging.send_multicast(multicast_message)
            results['sent'] += batch_response.success_count
            results['failed'] += batch_response.failure_count
            results['success'] = results['sent'] > 0
            
            # Handle individual response errors
            for idx, response in enumerate(batch_response.responses):
                if not response.success:
                    token_id = batch_tokens[idx][1]
                    handle_fcm_error(response, token_id, results)
            
            logger.info(f"Batch send completed: {batch_response.success_count} sent, {batch_response.failure_count} failed")
            
        except FirebaseError as e:
            logger.error(f"Firebase error in batch send: {e}")
            results['errors'].append(str(e))
            results['failed'] += len(batch_tokens)
        
        except Exception as e:
            logger.error(f"Unexpected error in batch send: {e}")
            results['errors'].append(str(e))
            results['failed'] += len(batch_tokens)
    
    # Mark notification as sent if any succeeded
    if notification and results['sent'] > 0:
        notification.push_sent = True
        notification.push_sent_at = timezone.now()
        notification.save(update_fields=['push_sent', 'push_sent_at'])
    
    return results


def handle_fcm_error(response, token_id: int, results: Dict[str, Any]):
    """
    Handle FCM send response errors and update token status
    
    Args:
        response: FCM send response
        token_id: Database ID of the FCM token
        results: Results dict to update
    """
    if not response.exception:
        return
    
    error = response.exception
    error_code = getattr(error, 'code', None)
    
    # Determine if token should be removed based on error type
    should_remove = False
    reason = str(error)
    
    if isinstance(error, messaging.UnregisteredError):
        # Device token is no longer registered
        should_remove = True
        reason = "Device token unregistered"
        logger.warning(f"Unregistered token ID {token_id}: {error}")
    
    elif isinstance(error, messaging.SenderIdMismatchError):
        # Wrong sender ID - token belongs to different app
        should_remove = True
        reason = "Sender ID mismatch"
        logger.error(f"Sender ID mismatch for token ID {token_id}: {error}")
    
    elif error_code in ['invalid-registration-token', 'registration-token-not-registered']:
        # Invalid token format or not registered
        should_remove = True
        reason = f"Invalid token: {error_code}"
        logger.warning(f"Invalid token ID {token_id}: {error}")
    
    elif error_code == 'invalid-argument':
        # Bad token format
        should_remove = True
        reason = "Invalid token format"
        logger.error(f"Invalid argument for token ID {token_id}: {error}")
    
    elif error_code in ['authentication-error', 'invalid-apns-credentials']:
        # Server configuration issue, not token issue
        logger.error(f"Server configuration error: {error}")
        reason = f"Server error: {error_code}"
    
    elif error_code == 'quota-exceeded':
        # Rate limit hit
        logger.warning(f"Quota exceeded: {error}")
        reason = "Rate limit exceeded"
    
    elif error_code == 'unavailable':
        # Temporary server error
        logger.warning(f"FCM temporarily unavailable: {error}")
        reason = "Service temporarily unavailable"
    
    else:
        # Other errors - increment failure count but don't remove
        logger.error(f"FCM error for token ID {token_id}: {error}")
    
    if should_remove:
        # Immediately deactivate invalid tokens
        FCMDeviceToken.objects.filter(id=token_id).update(
            is_active=False,
            last_failure=timezone.now(),
            last_failure_reason=reason
        )
        results['invalid_tokens'].append(token_id)
        logger.info(f"Deactivated invalid token ID {token_id}: {reason}")
    else:
        # Increment failure count for temporary errors
        token = FCMDeviceToken.objects.get(id=token_id)
        token.mark_failure(reason)
        
        # If token has too many failures, it will be auto-deactivated
        if not token.is_active:
            results['invalid_tokens'].append(token_id)


def prepare_push_data(notification, additional_data: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Prepare data payload for push notification"""
    # FCM data payload must have string values
    data = {
        'notification_id': str(notification.id),
        'notification_type': notification.notification_type,
        'created_at': notification.created_at.isoformat(),
    }
    
    # Add notification data if it exists
    if notification.data:
        for key, value in notification.data.items():
            data[f'data_{key}'] = str(value)
    
    # Add related object info
    if notification.related_object_type:
        data['related_type'] = notification.related_object_type
    if notification.related_object_id:
        data['related_id'] = str(notification.related_object_id)
    
    # Add action URL
    if notification.action_url:
        data['action_url'] = notification.action_url
    
    # Add additional data
    if additional_data:
        for key, value in additional_data.items():
            data[f'extra_{key}'] = str(value)
    
    return data


def should_send_push(prefs: NotificationPreference, notification_type: str) -> bool:
    """Check if push should be sent based on preferences and notification type"""
    if not prefs.push_enabled:
        return False
    
    # Map notification types to preference fields
    category_map = {
        'SEND': 'push_transactions',
        'PAYMENT': 'push_transactions',
        'P2P': 'push_p2p',
        'CONVERSION': 'push_transactions',
        'USDC': 'push_transactions',
        'SECURITY': 'push_security',
        'PROMOTION': 'push_promotions',
        'ANNOUNCEMENT': 'push_announcements',
        'BUSINESS': 'push_transactions',
    }
    
    for prefix, pref_field in category_map.items():
        if notification_type.startswith(prefix):
            return getattr(prefs, pref_field, True)
    
    # Default to True for unknown types
    return True


def register_device_token(
    user,
    token: str,
    device_type: str,
    device_id: str,
    device_name: Optional[str] = None,
    app_version: Optional[str] = None
) -> FCMDeviceToken:
    """
    Register or update an FCM device token
    
    Args:
        user: User instance
        token: FCM token
        device_type: 'ios', 'android', or 'web'
        device_id: Unique device identifier
        device_name: Device model/name
        app_version: App version
    
    Returns:
        FCMDeviceToken instance
    """
    # Update or create token
    device_token, created = FCMDeviceToken.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            'token': token,
            'device_type': device_type,
            'device_name': device_name or '',
            'app_version': app_version or '',
            'is_active': True,
            'last_used': timezone.now(),
            'failure_count': 0,
            'last_failure': None,
            'last_failure_reason': ''
        }
    )
    
    if not created and device_token.token != token:
        # Token changed for same device, update it
        device_token.token = token
        device_token.is_active = True
        device_token.failure_count = 0
        device_token.last_failure = None
        device_token.last_failure_reason = ''
        device_token.save()
    
    logger.info(f"FCM token {'created' if created else 'updated'} for user {user.id}, device {device_id}")
    
    return device_token


def unregister_device_token(user, device_id: str) -> bool:
    """
    Unregister an FCM device token
    
    Args:
        user: User instance
        device_id: Device identifier
    
    Returns:
        True if token was found and deactivated
    """
    updated = FCMDeviceToken.objects.filter(
        user=user,
        device_id=device_id
    ).update(
        is_active=False,
        updated_at=timezone.now()
    )
    
    return updated > 0


def send_test_push(user) -> Dict[str, Any]:
    """Send a test push notification to user"""
    from .models import NotificationType as NotificationTypeChoices
    from .utils import create_notification
    
    # Create a test notification
    notification = create_notification(
        user=user,
        notification_type=NotificationTypeChoices.SYSTEM,
        title="Test Notification",
        message="This is a test push notification from Confío",
        data={'test': True, 'timestamp': timezone.now().isoformat()},
        send_push=False  # We'll send it manually
    )
    
    # Send push
    result = send_push_notification(notification)
    
    return result