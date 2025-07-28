from django.db import models
from django.conf import settings
from .models import SoftDeleteModel, Business
from django.utils import timezone
import secrets
import string


class BusinessEmployee(SoftDeleteModel):
    """Represents an employee relationship with a business"""
    
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('cashier', 'Cashier'),
    ]
    
    # Default permissions for each role
    DEFAULT_PERMISSIONS = {
        'owner': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': True,
            'send_funds': True,
            'manage_employees': True,
            'view_business_address': True,
            'view_analytics': True,
            'delete_business': True,
            'edit_business_info': True,
            'manage_bank_accounts': True,
        },
        'admin': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': True,
            'send_funds': True,
            'manage_employees': True,
            'view_business_address': True,
            'view_analytics': True,
            'delete_business': False,
            'edit_business_info': True,
            'manage_bank_accounts': True,
        },
        'manager': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': True,
            'send_funds': False,
            'manage_employees': True,
            'view_business_address': False,
            'view_analytics': True,
            'delete_business': False,
            'edit_business_info': False,
            'manage_bank_accounts': False,
        },
        'cashier': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': False,
            'send_funds': False,
            'manage_employees': False,
            'view_business_address': False,
            'view_analytics': False,
            'delete_business': False,
            'edit_business_info': False,
            'manage_bank_accounts': False,
        }
    }
    
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name='employees',
        help_text="The business this employee works for"
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='employment_records',
        help_text="The user who is an employee"
    )
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='cashier',
        help_text="Employee role determining base permissions"
    )
    
    permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom permissions overriding role defaults"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this employee is currently active"
    )
    
    # Employment tracking
    hired_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the employee was added"
    )
    
    hired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees_hired',
        help_text="User who added this employee"
    )
    
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the employee was deactivated"
    )
    
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees_deactivated',
        help_text="User who deactivated this employee"
    )
    
    # Optional fields for shift-based permissions (future enhancement)
    shift_start_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Daily shift start time"
    )
    
    shift_end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Daily shift end time"
    )
    
    # Transaction limits (future enhancement)
    daily_transaction_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum daily transaction amount"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this employee"
    )
    
    class Meta:
        ordering = ['-hired_at']
        indexes = [
            models.Index(fields=['business', 'is_active']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['business', 'user', 'deleted_at'], name='idx_business_user_deleted'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['business', 'user'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_business_employee'
            ),
        ]
        # Note: Additional database-level constraints are enforced via triggers:
        # - prevent_self_employment: Prevents business owners from being employees of their own business
    
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.get_role_display()} at {self.business.name}"
    
    def get_effective_permissions(self):
        """Get the effective permissions combining role defaults and custom overrides"""
        # Start with role defaults
        perms = self.DEFAULT_PERMISSIONS.get(self.role, {}).copy()
        
        # Apply custom overrides
        if self.permissions:
            perms.update(self.permissions)
        
        return perms
    
    def has_permission(self, permission_name):
        """Check if employee has a specific permission"""
        perms = self.get_effective_permissions()
        return perms.get(permission_name, False)
    
    def deactivate(self, deactivated_by_user):
        """Deactivate this employee"""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.deactivated_by = deactivated_by_user
        self.save()
    
    def reactivate(self):
        """Reactivate this employee"""
        self.is_active = True
        self.deactivated_at = None
        self.deactivated_by = None
        self.save()
    
    def is_within_shift(self):
        """Check if current time is within employee's shift (if shift times are set)"""
        if not self.shift_start_time or not self.shift_end_time:
            return True  # No shift restrictions
        
        current_time = timezone.now().time()
        
        # Handle overnight shifts
        if self.shift_start_time <= self.shift_end_time:
            return self.shift_start_time <= current_time <= self.shift_end_time
        else:
            return current_time >= self.shift_start_time or current_time <= self.shift_end_time
    
    def can_process_amount(self, amount):
        """Check if employee can process this transaction amount"""
        if not self.daily_transaction_limit:
            return True  # No limit set
        
        # TODO: Implement daily transaction sum check
        # This would need to query today's transactions processed by this employee
        return True  # Placeholder
    
    @classmethod
    def get_businesses_for_user(cls, user):
        """Get all businesses where user is an employee"""
        return cls.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).select_related('business')


def generate_invitation_code():
    """Generate a unique invitation code"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


class EmployeeInvitation(SoftDeleteModel):
    """Invitation for a user to become an employee of a business"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name='employee_invitations'
    )
    
    invitation_code = models.CharField(
        max_length=32,
        unique=True,
        default=generate_invitation_code,
        editable=False
    )
    
    # Employee details
    employee_phone = models.CharField(
        max_length=20,
        help_text="Phone number of the invited employee"
    )
    
    employee_phone_country = models.CharField(
        max_length=2,
        help_text="ISO country code for the phone number"
    )
    
    employee_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the invited employee (optional)"
    )
    
    role = models.CharField(
        max_length=20,
        choices=BusinessEmployee.ROLE_CHOICES,
        default='cashier'
    )
    
    # Custom permissions override (optional)
    permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom permissions that override role defaults"
    )
    
    # Invitation metadata
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='employee_invitations_sent'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    expires_at = models.DateTimeField(
        help_text="When the invitation expires"
    )
    
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_invitations_accepted'
    )
    
    accepted_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    message = models.TextField(
        blank=True,
        help_text="Optional message to include with the invitation"
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invitation_code']),
            models.Index(fields=['business', 'status']),
            models.Index(fields=['employee_phone', 'status']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['employee_phone', 'employee_phone_country', 'status'], name='idx_invitation_phone_status'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['business', 'employee_phone', 'employee_phone_country'],
                condition=models.Q(status='pending') & models.Q(deleted_at__isnull=True),
                name='unique_pending_invitation_per_phone'
            ),
        ]
        # Note: Additional database-level constraints are enforced via triggers:
        # - prevent_invalid_invitation: Prevents inviting business owners and existing employees
    
    def __str__(self):
        return f"Invitation {self.invitation_code} for {self.employee_phone} to join {self.business.name}"
    
    @property
    def is_expired(self):
        """Check if the invitation has expired"""
        return timezone.now() > self.expires_at
    
    def accept(self, user):
        """Accept the invitation and create employee relationship"""
        if self.status != 'pending':
            raise ValueError(f"Cannot accept invitation with status: {self.status}")
        
        if self.is_expired:
            self.status = 'expired'
            self.save()
            raise ValueError("Invitation has expired")
        
        # Check if user is already an employee (including owner)
        if BusinessEmployee.objects.filter(business=self.business, user=user, deleted_at__isnull=True).exists():
            raise ValueError("User is already an employee of this business")
        
        # Check if user owns this business
        if self.business.accounts.filter(user=user).exists():
            raise ValueError("You cannot accept an invitation to your own business")
        
        # Create employee relationship
        # Use permissions from invitation or default to empty dict
        employee_permissions = self.permissions if self.permissions is not None else {}
        
        employee = BusinessEmployee.objects.create(
            business=self.business,
            user=user,
            role=self.role,
            permissions=employee_permissions,
            hired_by=self.invited_by,
            is_active=True
        )
        
        # Update invitation
        self.status = 'accepted'
        self.accepted_by = user
        self.accepted_at = timezone.now()
        self.save()
        
        return employee
    
    def cancel(self):
        """Cancel the invitation"""
        if self.status != 'pending':
            raise ValueError(f"Cannot cancel invitation with status: {self.status}")
        
        self.status = 'cancelled'
        self.save()
    
    @classmethod
    def cleanup_expired(cls):
        """Mark expired invitations as expired"""
        cls.objects.filter(
            status='pending',
            expires_at__lt=timezone.now()
        ).update(status='expired')


class EmployeeActivityLog(models.Model):
    """Log of employee activities for audit purposes"""
    
    ACTION_CHOICES = [
        ('payment_accepted', 'Payment Accepted'),
        ('invoice_created', 'Invoice Created'),
        ('invoice_cancelled', 'Invoice Cancelled'),
        ('account_accessed', 'Account Accessed'),
        ('balance_viewed', 'Balance Viewed'),
        ('transaction_viewed', 'Transaction Viewed'),
        ('settings_changed', 'Settings Changed'),
    ]
    
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name='employee_activity_logs'
    )
    
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='employee_activities'
    )
    
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES
    )
    
    timestamp = models.DateTimeField(
        auto_now_add=True
    )
    
    # Additional context about the action
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional details about the action"
    )
    
    # Related objects
    invoice_id = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Related invoice ID if applicable"
    )
    
    transaction_id = models.CharField(
        max_length=66,
        blank=True,
        null=True,
        help_text="Related transaction hash if applicable"
    )
    
    amount = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Transaction amount if applicable"
    )
    
    # IP and device info for security
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    
    user_agent = models.TextField(
        blank=True
    )
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['business', 'timestamp']),
            models.Index(fields=['employee', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['invoice_id']),
            models.Index(fields=['transaction_id']),
        ]
    
    def __str__(self):
        return f"{self.employee.username} - {self.get_action_display()} at {self.timestamp}"
    
    @classmethod
    def log_activity(cls, business, employee, action, request=None, **kwargs):
        """Helper method to log an activity"""
        log_entry = cls(
            business=business,
            employee=employee,
            action=action,
            details=kwargs.get('details', {}),
            invoice_id=kwargs.get('invoice_id'),
            transaction_id=kwargs.get('transaction_id'),
            amount=kwargs.get('amount')
        )
        
        # Extract IP and user agent from request if provided
        if request:
            log_entry.ip_address = cls._get_client_ip(request)
            log_entry.user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        log_entry.save()
        return log_entry
    
    @staticmethod
    def _get_client_ip(request):
        """Extract client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip