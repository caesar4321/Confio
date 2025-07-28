from django.db import models
from django.conf import settings
from .models import SoftDeleteModel, Business
from django.utils import timezone


class BusinessEmployee(SoftDeleteModel):
    """Represents an employee relationship with a business"""
    
    ROLE_CHOICES = [
        ('cashier', 'Cashier'),
        ('manager', 'Manager'),
        ('admin', 'Administrator'),
    ]
    
    # Default permissions for each role
    DEFAULT_PERMISSIONS = {
        'cashier': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': False,
            'send_funds': False,
            'manage_employees': False,
            'view_business_address': False,
            'view_analytics': False,
        },
        'manager': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': True,
            'send_funds': False,
            'manage_employees': True,
            'view_business_address': False,
            'view_analytics': True,
        },
        'admin': {
            'accept_payments': True,
            'view_transactions': True,
            'view_balance': True,
            'send_funds': True,
            'manage_employees': True,
            'view_business_address': True,
            'view_analytics': True,
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
        unique_together = [['business', 'user']]
        ordering = ['-hired_at']
        indexes = [
            models.Index(fields=['business', 'is_active']),
            models.Index(fields=['user', 'is_active']),
        ]
    
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
            is_deleted=False
        ).select_related('business')