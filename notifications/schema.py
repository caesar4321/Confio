import graphene
from graphene_django import DjangoObjectType
from graphql import GraphQLError
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from datetime import timedelta

from .models import Notification, NotificationRead, NotificationPreference, NotificationType
from users.models import User, Account
from graphql_jwt.decorators import login_required
from users.jwt_context import get_jwt_business_context_with_validation


class NotificationTypeEnum(graphene.Enum):
    """GraphQL enum for notification types"""
    # Send transactions
    SEND_RECEIVED = 'SEND_RECEIVED'
    SEND_SENT = 'SEND_SENT'
    SEND_INVITATION_SENT = 'SEND_INVITATION_SENT'
    SEND_INVITATION_CLAIMED = 'SEND_INVITATION_CLAIMED'
    SEND_INVITATION_EXPIRED = 'SEND_INVITATION_EXPIRED'
    SEND_FROM_EXTERNAL = 'SEND_FROM_EXTERNAL'
    
    # Payment transactions
    PAYMENT_RECEIVED = 'PAYMENT_RECEIVED'
    PAYMENT_SENT = 'PAYMENT_SENT'
    INVOICE_PAID = 'INVOICE_PAID'
    
    # P2P Trade transactions
    P2P_OFFER_RECEIVED = 'P2P_OFFER_RECEIVED'
    P2P_OFFER_ACCEPTED = 'P2P_OFFER_ACCEPTED'
    P2P_OFFER_REJECTED = 'P2P_OFFER_REJECTED'
    P2P_TRADE_STARTED = 'P2P_TRADE_STARTED'
    P2P_PAYMENT_CONFIRMED = 'P2P_PAYMENT_CONFIRMED'
    P2P_CRYPTO_RELEASED = 'P2P_CRYPTO_RELEASED'
    P2P_TRADE_COMPLETED = 'P2P_TRADE_COMPLETED'
    P2P_TRADE_CANCELLED = 'P2P_TRADE_CANCELLED'
    P2P_TRADE_DISPUTED = 'P2P_TRADE_DISPUTED'
    
    # Conversion transactions
    CONVERSION_COMPLETED = 'CONVERSION_COMPLETED'
    CONVERSION_FAILED = 'CONVERSION_FAILED'
    
    # USDC Deposit/Withdrawal
    USDC_DEPOSIT_PENDING = 'USDC_DEPOSIT_PENDING'
    USDC_DEPOSIT_COMPLETED = 'USDC_DEPOSIT_COMPLETED'
    USDC_DEPOSIT_FAILED = 'USDC_DEPOSIT_FAILED'
    USDC_WITHDRAWAL_PENDING = 'USDC_WITHDRAWAL_PENDING'
    USDC_WITHDRAWAL_COMPLETED = 'USDC_WITHDRAWAL_COMPLETED'
    USDC_WITHDRAWAL_FAILED = 'USDC_WITHDRAWAL_FAILED'
    
    # Account related
    ACCOUNT_VERIFIED = 'ACCOUNT_VERIFIED'
    SECURITY_ALERT = 'SECURITY_ALERT'
    NEW_LOGIN = 'NEW_LOGIN'
    
    # Business related
    BUSINESS_EMPLOYEE_ADDED = 'BUSINESS_EMPLOYEE_ADDED'
    BUSINESS_EMPLOYEE_REMOVED = 'BUSINESS_EMPLOYEE_REMOVED'
    BUSINESS_PERMISSION_CHANGED = 'BUSINESS_PERMISSION_CHANGED'
    
    # General
    PROMOTION = 'PROMOTION'
    SYSTEM = 'SYSTEM'
    ANNOUNCEMENT = 'ANNOUNCEMENT'


class NotificationType(DjangoObjectType):
    """GraphQL type for Notification model"""
    is_read = graphene.Boolean()
    notification_type = NotificationTypeEnum()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'account', 'business', 'is_broadcast', 'broadcast_target',
            'notification_type', 'title', 'message', 'data', 'related_object_type',
            'related_object_id', 'action_url', 'created_at', 'updated_at',
            'push_sent', 'push_sent_at'
        ]
    
    def resolve_is_read(self, info):
        """For broadcast notifications, check if current user has read it"""
        if self.is_broadcast and hasattr(info.context, 'user') and info.context.user.is_authenticated:
            return NotificationRead.objects.filter(
                notification=self,
                user=info.context.user
            ).exists()
        # For personal notifications, use the is_read field from database
        return getattr(self, 'is_read', False)


class NotificationPreferenceType(DjangoObjectType):
    """GraphQL type for NotificationPreference model"""
    class Meta:
        model = NotificationPreference
        fields = [
            'push_enabled', 'push_transactions', 'push_p2p', 'push_security',
            'push_promotions', 'push_announcements', 'in_app_enabled',
            'in_app_transactions', 'in_app_p2p', 'in_app_security',
            'in_app_promotions', 'in_app_announcements', 'created_at', 'updated_at'
        ]


class NotificationConnection(graphene.Connection):
    """Pagination connection for notifications"""
    class Meta:
        node = NotificationType
    
    total_count = graphene.Int()
    unread_count = graphene.Int()
    
    def resolve_total_count(self, info):
        return len(self.edges) if hasattr(self, 'edges') else 0
    
    def resolve_unread_count(self, info):
        if hasattr(info.context, 'user') and info.context.user.is_authenticated:
            user = info.context.user
            # Count unread personal notifications
            personal_unread = Notification.objects.filter(
                user=user,
                is_broadcast=False
            ).exclude(
                id__in=NotificationRead.objects.filter(user=user).values('notification_id')
            ).count()
            
            # Count unread broadcast notifications
            broadcast_unread = Notification.objects.filter(
                is_broadcast=True
            ).exclude(
                id__in=NotificationRead.objects.filter(user=user).values('notification_id')
            ).count()
            
            return personal_unread + broadcast_unread
        return 0


class Query(graphene.ObjectType):
    """Notification queries"""
    
    notifications = graphene.relay.ConnectionField(
        NotificationConnection,
        notification_type=NotificationTypeEnum(required=False),
        is_read=graphene.Boolean(required=False),
        account_id=graphene.String(required=False),
        business_id=graphene.String(required=False)
    )
    
    notification = graphene.Field(
        NotificationType,
        id=graphene.ID(required=True)
    )
    
    notification_preferences = graphene.Field(NotificationPreferenceType)
    
    unread_notification_count = graphene.Int()
    
    @login_required
    def resolve_notifications(self, info, **kwargs):
        """Get user's notifications with filters"""
        user = info.context.user
        
        # Get JWT context to determine current account
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            # No valid JWT context, return empty
            return Notification.objects.none()
        
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Build the query based on account context
        personal_notifications = Q(user=user, is_broadcast=False)
        
        # Filter by account context from JWT
        if account_type == 'business' and business_id:
            # Show business-specific notifications
            personal_notifications &= Q(business_id=business_id)
        else:
            # Show personal account notifications
            # Find the user's account
            try:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
                personal_notifications &= Q(account=account)
            except Account.DoesNotExist:
                # If account not found, show general notifications
                personal_notifications &= Q(account__isnull=True, business__isnull=True)
        
        # Include broadcast notifications
        broadcast_notifications = Q(is_broadcast=True)
        
        qs = Notification.objects.filter(
            personal_notifications | broadcast_notifications
        )
        
        # Apply additional filters if provided
        if 'notification_type' in kwargs:
            qs = qs.filter(notification_type=kwargs['notification_type'])
        
        # Handle is_read filter
        if 'is_read' in kwargs:
            read_notification_ids = NotificationRead.objects.filter(
                user=user
            ).values_list('notification_id', flat=True)
            
            if kwargs['is_read']:
                # Show read notifications
                qs = qs.filter(
                    Q(id__in=read_notification_ids) |  # Broadcast notifications marked as read
                    Q(is_broadcast=False, id__in=read_notification_ids)  # Personal notifications marked as read
                )
            else:
                # Show unread notifications
                qs = qs.exclude(id__in=read_notification_ids)
        
        # Annotate with is_read status for the current user
        qs = qs.annotate(
            is_read=Exists(
                NotificationRead.objects.filter(
                    notification_id=OuterRef('id'),
                    user=user
                )
            )
        )
        
        return qs.order_by('-created_at')
    
    @login_required
    def resolve_notification(self, info, id):
        """Get a specific notification"""
        user = info.context.user
        
        try:
            notification = Notification.objects.get(id=id)
            
            # Check access: user must own the notification or it must be a broadcast
            if notification.is_broadcast or notification.user == user:
                # Annotate with is_read status
                is_read = NotificationRead.objects.filter(
                    notification=notification,
                    user=user
                ).exists()
                notification.is_read = is_read
                return notification
            else:
                raise GraphQLError("You don't have permission to view this notification")
                
        except Notification.DoesNotExist:
            raise GraphQLError("Notification not found")
    
    @login_required
    def resolve_notification_preferences(self, info):
        """Get user's notification preferences"""
        user = info.context.user
        
        # Get or create preferences
        preferences, created = NotificationPreference.objects.get_or_create(
            user=user,
            defaults={
                'push_enabled': True,
                'in_app_enabled': True
            }
        )
        
        return preferences
    
    @login_required
    def resolve_unread_notification_count(self, info):
        """Get count of unread notifications based on JWT context"""
        user = info.context.user
        
        # Get JWT context to determine current account
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            # No valid JWT context, return 0
            return 0
        
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Build query based on account context
        personal_query = Q(user=user, is_broadcast=False)
        
        # Filter by account context from JWT
        if account_type == 'business' and business_id:
            # Count business-specific notifications
            personal_query &= Q(business_id=business_id)
        else:
            # Count personal account notifications
            try:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
                personal_query &= Q(account=account)
            except Account.DoesNotExist:
                # If account not found, count general notifications
                personal_query &= Q(account__isnull=True, business__isnull=True)
        
        # Get read notification IDs for this user
        read_notification_ids = NotificationRead.objects.filter(
            user=user
        ).values_list('notification_id', flat=True)
        
        # Count unread personal notifications
        personal_unread = Notification.objects.filter(
            personal_query
        ).exclude(
            id__in=read_notification_ids
        ).count()
        
        # Count unread broadcast notifications
        broadcast_unread = Notification.objects.filter(
            is_broadcast=True
        ).exclude(
            id__in=read_notification_ids
        ).count()
        
        return personal_unread + broadcast_unread


class MarkNotificationRead(graphene.Mutation):
    """Mark a notification as read"""
    class Arguments:
        notification_id = graphene.ID(required=True)
    
    success = graphene.Boolean()
    notification = graphene.Field(NotificationType)
    
    @login_required
    def mutate(self, info, notification_id):
        user = info.context.user
        
        try:
            notification = Notification.objects.get(id=notification_id)
            
            # Check access
            if not (notification.is_broadcast or notification.user == user):
                raise GraphQLError("You don't have permission to mark this notification as read")
            
            # Create or update read record
            NotificationRead.objects.get_or_create(
                notification=notification,
                user=user
            )
            
            # Set is_read for response
            notification.is_read = True
            
            return MarkNotificationRead(success=True, notification=notification)
            
        except Notification.DoesNotExist:
            raise GraphQLError("Notification not found")


class MarkAllNotificationsRead(graphene.Mutation):
    """Mark all notifications as read for the user"""
    success = graphene.Boolean()
    marked_count = graphene.Int()
    
    @login_required
    def mutate(self, info):
        user = info.context.user
        
        # Get all unread notifications for the user
        read_notification_ids = NotificationRead.objects.filter(
            user=user
        ).values_list('notification_id', flat=True)
        
        # Get personal unread notifications
        personal_unread = Notification.objects.filter(
            user=user,
            is_broadcast=False
        ).exclude(id__in=read_notification_ids)
        
        # Get broadcast unread notifications
        broadcast_unread = Notification.objects.filter(
            is_broadcast=True
        ).exclude(id__in=read_notification_ids)
        
        # Create read records for all unread notifications
        marked_count = 0
        
        for notification in personal_unread:
            NotificationRead.objects.get_or_create(
                notification=notification,
                user=user
            )
            marked_count += 1
        
        for notification in broadcast_unread:
            NotificationRead.objects.get_or_create(
                notification=notification,
                user=user
            )
            marked_count += 1
        
        return MarkAllNotificationsRead(success=True, marked_count=marked_count)


class UpdateNotificationPreferences(graphene.Mutation):
    """Update user's notification preferences"""
    class Arguments:
        push_enabled = graphene.Boolean(required=False)
        push_transactions = graphene.Boolean(required=False)
        push_p2p = graphene.Boolean(required=False)
        push_security = graphene.Boolean(required=False)
        push_promotions = graphene.Boolean(required=False)
        push_announcements = graphene.Boolean(required=False)
        in_app_enabled = graphene.Boolean(required=False)
        in_app_transactions = graphene.Boolean(required=False)
        in_app_p2p = graphene.Boolean(required=False)
        in_app_security = graphene.Boolean(required=False)
        in_app_promotions = graphene.Boolean(required=False)
        in_app_announcements = graphene.Boolean(required=False)
    
    success = graphene.Boolean()
    preferences = graphene.Field(NotificationPreferenceType)
    
    @login_required
    def mutate(self, info, **kwargs):
        user = info.context.user
        
        # Get or create preferences
        preferences, created = NotificationPreference.objects.get_or_create(
            user=user
        )
        
        # Update only provided fields
        for field, value in kwargs.items():
            if hasattr(preferences, field):
                setattr(preferences, field, value)
        
        preferences.save()
        
        return UpdateNotificationPreferences(
            success=True,
            preferences=preferences
        )


class CreateTestNotification(graphene.Mutation):
    """Create a test notification (for development/testing)"""
    class Arguments:
        notification_type = NotificationTypeEnum(required=True)
        title = graphene.String(required=True)
        message = graphene.String(required=True)
        is_broadcast = graphene.Boolean(required=False)
        broadcast_target = graphene.String(required=False)
    
    success = graphene.Boolean()
    notification = graphene.Field(NotificationType)
    
    @login_required
    def mutate(self, info, notification_type, title, message, is_broadcast=False, broadcast_target=None):
        user = info.context.user
        
        # Create notification
        notification_data = {
            'notification_type': notification_type,
            'title': title,
            'message': message,
            'is_broadcast': is_broadcast,
        }
        
        if is_broadcast:
            notification_data['broadcast_target'] = broadcast_target or 'all'
        else:
            notification_data['user'] = user
        
        notification = Notification.objects.create(**notification_data)
        
        return CreateTestNotification(
            success=True,
            notification=notification
        )


class Mutation(graphene.ObjectType):
    """Notification mutations"""
    mark_notification_read = MarkNotificationRead.Field()
    mark_all_notifications_read = MarkAllNotificationsRead.Field()
    update_notification_preferences = UpdateNotificationPreferences.Field()
    create_test_notification = CreateTestNotification.Field()


# Schema to be included in main schema
schema = graphene.Schema(query=Query, mutation=Mutation)