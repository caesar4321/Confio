"""
Utility functions for creating and managing notifications
"""
from typing import Optional, Dict, Any
from django.db import transaction
from django.utils import timezone
from .models import Notification, NotificationType as NotificationTypeChoices
from users.models import User, Account, Business
from .fcm_service import send_push_notification
import logging

logger = logging.getLogger(__name__)


def create_notification(
    user: Optional[User] = None,
    account: Optional[Account] = None,
    business: Optional[Business] = None,
    notification_type: str = None,
    title: str = None,
    message: str = None,
    data: Optional[Dict[str, Any]] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[str] = None,
    action_url: Optional[str] = None,
    is_broadcast: bool = False,
    broadcast_target: Optional[str] = None,
    send_push: bool = True
) -> Notification:
    """
    Create a notification with proper validation
    
    Args:
        user: Target user for personal notifications
        account: Related account (optional)
        business: Related business (optional)
        notification_type: Type from NotificationType choices
        title: Notification title
        message: Notification message
        data: Additional data as dict
        related_object_type: Type of related object (e.g., 'SendTransaction')
        related_object_id: ID of related object
        action_url: Deep link for notification action
        is_broadcast: Whether this is a broadcast notification
        broadcast_target: Target audience for broadcast ('all', 'verified', etc.)
        send_push: Whether to send push notification (TODO: implement push service)
    
    Returns:
        Created Notification instance
    """
    if not is_broadcast and not user:
        raise ValueError("User is required for personal notifications")
    
    if is_broadcast and user:
        raise ValueError("User should not be set for broadcast notifications")
    
    notification = Notification.objects.create(
        user=user,
        account=account,
        business=business,
        notification_type=notification_type,
        title=title,
        message=message,
        data=data or {},
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        action_url=action_url,
        is_broadcast=is_broadcast,
        broadcast_target=broadcast_target
    )
    
    # Send push notification if enabled
    if send_push:
        try:
            logger.info(f"Attempting to send push notification for notification {notification.id}, user {user.id if user else 'broadcast'}")
            result = send_push_notification(notification)
            logger.info(f"Push notification result for notification {notification.id}: {result}")
            if result.get('success'):
                logger.info(f"Push notification sent successfully for notification {notification.id}: {result.get('sent')} sent, {result.get('failed')} failed")
            else:
                logger.warning(f"Failed to send push notification for notification {notification.id}: {result.get('error')}, details: {result}")
        except Exception as e:
            logger.error(f"Error sending push notification for notification {notification.id}: {e}", exc_info=True)
    
    return notification


def create_transaction_notification(
    transaction_type: str,
    sender_user: Optional[User] = None,
    recipient_user: Optional[User] = None,
    amount: str = None,
    token_type: str = None,
    transaction_id: str = None,
    transaction_model: str = None,
    additional_data: Optional[Dict[str, Any]] = None
) -> Optional[Notification]:
    """
    Create notifications for transaction events
    
    Args:
        transaction_type: 'send', 'payment', 'p2p', 'conversion', 'deposit', 'withdrawal'
        sender_user: User who sent the transaction
        recipient_user: User who received the transaction
        amount: Transaction amount
        token_type: Token type (cUSD, CONFIO, USDC)
        transaction_id: ID of the transaction
        transaction_model: Model name (e.g., 'SendTransaction')
        additional_data: Additional transaction data
    
    Returns:
        Created Notification instance or None
    """
    data = {
        'amount': amount,
        'token_type': token_type,
        'transaction_id': transaction_id,
    }
    if additional_data:
        data.update(additional_data)
    
    # Send notifications based on transaction type
    if transaction_type == 'send' and recipient_user:
        title = f"Payment Received"
        message = f"You received {amount} {token_type}"
        if sender_user:
            sender_name = sender_user.get_display_name()
            message = f"You received {amount} {token_type} from {sender_name}"
        
        return create_notification(
            user=recipient_user,
            notification_type=NotificationTypeChoices.SEND_RECEIVED,
            title=title,
            message=message,
            data=data,
            related_object_type=transaction_model,
            related_object_id=transaction_id,
            action_url=f"confio://transaction/{transaction_id}"
        )
    
    elif transaction_type == 'send_sent' and sender_user:
        recipient_name = data.get('recipient_name', 'someone')
        return create_notification(
            user=sender_user,
            notification_type=NotificationTypeChoices.SEND_SENT,
            title="Payment Sent",
            message=f"You sent {amount} {token_type} to {recipient_name}",
            data=data,
            related_object_type=transaction_model,
            related_object_id=transaction_id,
            action_url=f"confio://transaction/{transaction_id}"
        )
    
    elif transaction_type == 'payment' and sender_user:
        return create_notification(
            user=sender_user,
            notification_type=NotificationTypeChoices.PAYMENT_SENT,
            title="Payment Completed",
            message=f"Your payment of {amount} {token_type} was successful",
            data=data,
            related_object_type=transaction_model,
            related_object_id=transaction_id,
            action_url=f"confio://transaction/{transaction_id}"
        )
    
    elif transaction_type == 'conversion' and sender_user:
        from_amount = data.get('from_amount', amount)
        from_token = data.get('from_token', token_type)
        to_amount = data.get('to_amount', amount)
        to_token = data.get('to_token', token_type)
        
        return create_notification(
            user=sender_user,
            notification_type=NotificationTypeChoices.CONVERSION_COMPLETED,
            title="Conversion Completed",
            message=f"Converted {from_amount} {from_token} to {to_amount} {to_token}",
            data=data,
            related_object_type=transaction_model,
            related_object_id=transaction_id,
            action_url=f"confio://transaction/{transaction_id}"
        )
    
    return None


def create_p2p_notification(
    notification_type: str,
    user: User,
    trade_id: Optional[str] = None,
    offer_id: Optional[str] = None,
    amount: Optional[str] = None,
    token_type: Optional[str] = None,
    counterparty_name: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None
) -> Notification:
    """
    Create P2P trading notifications
    """
    data = {
        'trade_id': trade_id,
        'offer_id': offer_id,
        'amount': amount,
        'token_type': token_type,
        'counterparty_name': counterparty_name,
    }
    if additional_data:
        data.update(additional_data)
    
    # Map notification types to titles and messages
    notification_configs = {
        NotificationTypeChoices.P2P_OFFER_RECEIVED: {
            'title': 'New P2P Offer',
            'message': f'You have a new offer for {amount} {token_type}',
            'action_url': f'confio://p2p/offer/{offer_id}'
        },
        NotificationTypeChoices.P2P_OFFER_ACCEPTED: {
            'title': 'Offer Accepted',
            'message': f'Your offer for {amount} {token_type} was accepted',
            'action_url': f'confio://p2p/trade/{trade_id}'
        },
        NotificationTypeChoices.P2P_TRADE_STARTED: {
            'title': 'Trade Started',
            'message': f'Your P2P trade for {amount} {token_type} has started',
            'action_url': f'confio://p2p/trade/{trade_id}'
        },
        NotificationTypeChoices.P2P_PAYMENT_CONFIRMED: {
            'title': 'Payment Confirmed',
            'message': f'{counterparty_name} confirmed payment for your trade',
            'action_url': f'confio://p2p/trade/{trade_id}'
        },
        NotificationTypeChoices.P2P_CRYPTO_RELEASED: {
            'title': 'Crypto Released',
            'message': f'{amount} {token_type} has been released to {counterparty_name}',
            'action_url': f'confio://p2p/trade/{trade_id}'
        },
        NotificationTypeChoices.P2P_TRADE_COMPLETED: {
            'title': 'Trade Completed',
            'message': f'Your P2P trade for {amount} {token_type} is complete',
            'action_url': f'confio://p2p/trade/{trade_id}'
        },
    }
    
    config = notification_configs.get(notification_type, {})
    
    return create_notification(
        user=user,
        notification_type=notification_type,
        title=config.get('title', 'P2P Notification'),
        message=config.get('message', 'P2P trade update'),
        data=data,
        related_object_type='P2PTrade' if trade_id else 'P2POffer',
        related_object_id=trade_id or offer_id,
        action_url=config.get('action_url')
    )


def create_business_notification(
    notification_type: str,
    user: User,
    business: Business,
    additional_data: Optional[Dict[str, Any]] = None
) -> Notification:
    """
    Create business-related notifications
    """
    data = {
        'business_id': str(business.id),
        'business_name': business.name,
    }
    if additional_data:
        data.update(additional_data)
    
    notification_configs = {
        NotificationTypeChoices.BUSINESS_EMPLOYEE_ADDED: {
            'title': 'Added to Business',
            'message': f'You have been added as an employee to {business.name}',
            'action_url': f'confio://business/{business.id}'
        },
        NotificationTypeChoices.BUSINESS_EMPLOYEE_REMOVED: {
            'title': 'Removed from Business',
            'message': f'You have been removed from {business.name}',
            'action_url': 'confio://businesses'
        },
        NotificationTypeChoices.BUSINESS_PERMISSION_CHANGED: {
            'title': 'Permissions Updated',
            'message': f'Your permissions at {business.name} have been updated',
            'action_url': f'confio://business/{business.id}/settings'
        },
    }
    
    config = notification_configs.get(notification_type, {})
    
    return create_notification(
        user=user,
        business=business,
        notification_type=notification_type,
        title=config.get('title', 'Business Update'),
        message=config.get('message', 'Business notification'),
        data=data,
        related_object_type='Business',
        related_object_id=str(business.id),
        action_url=config.get('action_url')
    )


def create_security_notification(
    user: User,
    notification_type: str,
    title: str,
    message: str,
    additional_data: Optional[Dict[str, Any]] = None
) -> Notification:
    """
    Create security-related notifications
    """
    return create_notification(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        data=additional_data or {},
        action_url='confio://settings/security'
    )


def create_broadcast_announcement(
    title: str,
    message: str,
    target_audience: str = 'all',
    additional_data: Optional[Dict[str, Any]] = None,
    action_url: Optional[str] = None
) -> Notification:
    """
    Create a broadcast announcement for multiple users
    
    Args:
        title: Announcement title
        message: Announcement message
        target_audience: 'all', 'verified', 'business', etc.
        additional_data: Additional data
        action_url: Deep link for action
    
    Returns:
        Created broadcast Notification
    """
    return create_notification(
        notification_type=NotificationTypeChoices.ANNOUNCEMENT,
        title=title,
        message=message,
        data=additional_data or {},
        is_broadcast=True,
        broadcast_target=target_audience,
        action_url=action_url
    )


def should_send_notification(user: User, notification_type: str) -> bool:
    """
    Check if a notification should be sent based on user preferences
    """
    from .models import NotificationPreference
    
    try:
        prefs = user.notification_preferences
    except NotificationPreference.DoesNotExist:
        # Default to sending if no preferences exist
        return True
    
    # Check if notifications are enabled at all
    if not prefs.in_app_enabled:
        return False
    
    # Check specific category preferences
    category_map = {
        'SEND': 'in_app_transactions',
        'PAYMENT': 'in_app_transactions',
        'P2P': 'in_app_p2p',
        'CONVERSION': 'in_app_transactions',
        'USDC': 'in_app_transactions',
        'SECURITY': 'in_app_security',
        'PROMOTION': 'in_app_promotions',
        'ANNOUNCEMENT': 'in_app_announcements',
        'BUSINESS': 'in_app_transactions',  # Business notifications under transactions
    }
    
    for prefix, pref_field in category_map.items():
        if notification_type.startswith(prefix):
            return getattr(prefs, pref_field, True)
    
    # Default to True for unknown types
    return True