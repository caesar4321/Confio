from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import Account, Business

User = get_user_model()


class NotificationType(models.TextChoices):
    # Send transactions
    SEND_RECEIVED = 'SEND_RECEIVED', 'Send Received'
    SEND_SENT = 'SEND_SENT', 'Send Sent'
    INVITE_RECEIVED = 'INVITE_RECEIVED', 'Invite Received'
    SEND_INVITATION_SENT = 'SEND_INVITATION_SENT', 'Send Invitation Sent'
    SEND_INVITATION_CLAIMED = 'SEND_INVITATION_CLAIMED', 'Send Invitation Claimed'
    SEND_INVITATION_EXPIRED = 'SEND_INVITATION_EXPIRED', 'Send Invitation Expired'
    SEND_FROM_EXTERNAL = 'SEND_FROM_EXTERNAL', 'Send from External Wallet'
    
    # Payment transactions
    PAYMENT_RECEIVED = 'PAYMENT_RECEIVED', 'Payment Received'
    PAYMENT_SENT = 'PAYMENT_SENT', 'Payment Sent'
    INVOICE_PAID = 'INVOICE_PAID', 'Invoice Paid'
    
    # P2P Trade transactions
    P2P_OFFER_RECEIVED = 'P2P_OFFER_RECEIVED', 'P2P Offer Received'
    P2P_OFFER_ACCEPTED = 'P2P_OFFER_ACCEPTED', 'P2P Offer Accepted'
    P2P_OFFER_REJECTED = 'P2P_OFFER_REJECTED', 'P2P Offer Rejected'
    P2P_TRADE_STARTED = 'P2P_TRADE_STARTED', 'P2P Trade Started'
    P2P_PAYMENT_CONFIRMED = 'P2P_PAYMENT_CONFIRMED', 'P2P Payment Confirmed'
    P2P_CRYPTO_RELEASED = 'P2P_CRYPTO_RELEASED', 'P2P Crypto Released'
    P2P_TRADE_COMPLETED = 'P2P_TRADE_COMPLETED', 'P2P Trade Completed'
    P2P_TRADE_CANCELLED = 'P2P_TRADE_CANCELLED', 'P2P Trade Cancelled'
    P2P_TRADE_DISPUTED = 'P2P_TRADE_DISPUTED', 'P2P Trade Disputed'
    P2P_DISPUTE_RESOLVED = 'P2P_DISPUTE_RESOLVED', 'P2P Dispute Resolved'
    
    # Conversion transactions
    CONVERSION_COMPLETED = 'CONVERSION_COMPLETED', 'Conversion Completed'
    CONVERSION_FAILED = 'CONVERSION_FAILED', 'Conversion Failed'
    
    # USDC Deposit/Withdrawal
    USDC_DEPOSIT_PENDING = 'USDC_DEPOSIT_PENDING', 'USDC Deposit Pending'
    USDC_DEPOSIT_COMPLETED = 'USDC_DEPOSIT_COMPLETED', 'USDC Deposit Completed'
    USDC_DEPOSIT_FAILED = 'USDC_DEPOSIT_FAILED', 'USDC Deposit Failed'
    USDC_WITHDRAWAL_PENDING = 'USDC_WITHDRAWAL_PENDING', 'USDC Withdrawal Pending'
    USDC_WITHDRAWAL_COMPLETED = 'USDC_WITHDRAWAL_COMPLETED', 'USDC Withdrawal Completed'
    USDC_WITHDRAWAL_FAILED = 'USDC_WITHDRAWAL_FAILED', 'USDC Withdrawal Failed'
    
    # Account related
    ACCOUNT_VERIFIED = 'ACCOUNT_VERIFIED', 'Account Verified'
    SECURITY_ALERT = 'SECURITY_ALERT', 'Security Alert'
    NEW_LOGIN = 'NEW_LOGIN', 'New Login Detected'
    
    # Business related
    BUSINESS_EMPLOYEE_ADDED = 'BUSINESS_EMPLOYEE_ADDED', 'Added as Business Employee'
    BUSINESS_EMPLOYEE_REMOVED = 'BUSINESS_EMPLOYEE_REMOVED', 'Removed from Business'
    BUSINESS_PERMISSION_CHANGED = 'BUSINESS_PERMISSION_CHANGED', 'Business Permissions Changed'
    
    # Achievements
    ACHIEVEMENT_EARNED = 'ACHIEVEMENT_EARNED', 'Achievement Earned'
    
    # General
    PROMOTION = 'PROMOTION', 'Promotion'
    SYSTEM = 'SYSTEM', 'System Notification'
    ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'
    
    # Presale
    PRESALE_PURCHASE_CONFIRMED = 'PRESALE_PURCHASE_CONFIRMED', 'Presale Purchase Confirmed'


class Notification(models.Model):
    # For personalized notifications (1:1)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    
    # For broadcast notifications (announcements)
    is_broadcast = models.BooleanField(default=False)
    broadcast_target = models.CharField(max_length=50, null=True, blank=True, help_text="Target audience: 'all', 'verified', 'business', etc.")
    
    notification_type = models.CharField(max_length=50, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Additional data as JSON for flexibility
    data = models.JSONField(default=dict, blank=True)
    
    # For linking to specific objects
    related_object_type = models.CharField(max_length=50, null=True, blank=True)
    related_object_id = models.CharField(max_length=100, null=True, blank=True)
    
    # Action URL for deep linking
    action_url = models.CharField(max_length=200, null=True, blank=True, help_text="Deep link for notification action")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # For push notifications
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_broadcast', '-created_at']),
            models.Index(fields=['account', '-created_at']),
            models.Index(fields=['business', '-created_at']),
        ]
    
    def __str__(self):
        if self.is_broadcast:
            return f"BROADCAST: {self.notification_type} - {self.title}"
        return f"{self.notification_type} - {self.title} - {self.user.email if self.user else 'No user'}"


class NotificationRead(models.Model):
    """Track which users have read notifications in specific account contexts"""
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_reads')
    
    # Account context - to track reads per account (personal vs business)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='notification_reads')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='notification_reads')
    
    read_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['notification', 'user', 'account', 'business'],
                name='unique_notification_read_per_context'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'notification']),
            models.Index(fields=['user', 'account', 'business'], name='notif_user_acc_bus_idx'),
        ]


class NotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')
    
    # Push notification preferences
    push_enabled = models.BooleanField(default=True)
    push_transactions = models.BooleanField(default=True)
    push_p2p = models.BooleanField(default=True)
    push_security = models.BooleanField(default=True)
    push_promotions = models.BooleanField(default=True)
    push_announcements = models.BooleanField(default=True)
    
    # In-app notification preferences (always enabled for important notifications)
    in_app_enabled = models.BooleanField(default=True)
    in_app_transactions = models.BooleanField(default=True)
    in_app_p2p = models.BooleanField(default=True)
    in_app_security = models.BooleanField(default=True)
    in_app_promotions = models.BooleanField(default=True)
    in_app_announcements = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Notification Preferences - {self.user.email}"


class FCMDeviceToken(models.Model):
    """Store FCM device tokens for push notifications
    
    A single device token can be associated with multiple users,
    allowing the same device to receive notifications for different accounts.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fcm_tokens')
    token = models.TextField(help_text='FCM token - can be shared by multiple users')
    
    # Device information
    device_type = models.CharField(max_length=20, choices=[
        ('ios', 'iOS'),
        ('android', 'Android'),
        ('web', 'Web')
    ])
    device_id = models.CharField(max_length=255, blank=True, help_text="Unique device identifier")
    device_name = models.CharField(max_length=255, blank=True, help_text="Device model/name")
    app_version = models.CharField(max_length=50, blank=True)
    
    # Token status
    is_active = models.BooleanField(default=True)
    last_used = models.DateTimeField(default=timezone.now)
    
    # Error tracking
    failure_count = models.IntegerField(default=0)
    last_failure = models.DateTimeField(null=True, blank=True)
    last_failure_reason = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_active'], name='fcm_user_active_idx'),
            models.Index(fields=['token', 'is_active'], name='fcm_token_active_idx'),
            models.Index(fields=['device_id']),
        ]
        unique_together = ['user', 'token']
    
    def __str__(self):
        return f"FCM Token - {self.user.email} - {self.device_type} - {'Active' if self.is_active else 'Inactive'}"
    
    def mark_failure(self, reason=""):
        """Mark token as failed and increment failure count"""
        self.failure_count += 1
        self.last_failure = timezone.now()
        self.last_failure_reason = reason
        
        # Deactivate token after 5 failures
        if self.failure_count >= 5:
            self.is_active = False
        
        self.save()
    
    def mark_success(self):
        """Reset failure count on successful send"""
        if self.failure_count > 0:
            self.failure_count = 0
            self.last_failure = None
            self.last_failure_reason = ""
            self.save()
        
        # Update last used
        self.last_used = timezone.now()
        self.save(update_fields=['last_used'])
