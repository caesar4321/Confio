import graphene
from graphene_django import DjangoObjectType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from .models_employee import BusinessEmployee, EmployeeInvitation, EmployeeActivityLog
from .models import Business, User, Account
from .jwt_context import require_business_context, get_jwt_business_context_with_validation


def get_account_from_context(context, user=None):
    """Extract account information from request context"""
    if not user:
        user = context.user
    if not user or not user.is_authenticated:
        return None
    
    # Create a fake info object to use with JWT context extraction
    class FakeInfo:
        def __init__(self, context):
            self.context = context
    
    jwt_context = get_jwt_business_context_with_validation(FakeInfo(context), required_permission=None)
    if not jwt_context:
        # Fall back to personal account if no JWT context
        account_type = 'personal'
        account_index = 0
        business_id = None
    else:
        # Get account type and index from JWT context
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
    
    print(f"get_account_from_context - User: {user.id}, JWT Type: {account_type}, JWT Index: {account_index}, JWT Business: {business_id}")
    
    try:
        # Get the specific account
        if account_type == 'business' and business_id:
            # For business accounts, find by business_id
            account = Account.objects.get(
                business_id=business_id,
                account_type='business',
                account_index=account_index
            )
        else:
            # For personal accounts or own business accounts
            account = Account.objects.get(
                user=user,
                account_type=account_type,
                account_index=account_index
            )
        print(f"get_account_from_context - Found account: {account.id}, Business: {account.business_id if account.business else 'None'}")
        return account
    except Account.DoesNotExist:
        print(f"get_account_from_context - No account found for user={user.id}, type={account_type}, index={account_index}")
        # List available accounts for debugging
        available_accounts = Account.objects.filter(user=user)
        for acc in available_accounts:
            print(f"  Available: type={acc.account_type}, index={acc.account_index}, business={acc.business_id if acc.business else 'None'}")
        return None


class BusinessEmployeeType(DjangoObjectType):
    """GraphQL type for business employees"""
    
    permissions = graphene.JSONString()
    effective_permissions = graphene.JSONString()
    is_within_shift = graphene.Boolean()
    
    class Meta:
        model = BusinessEmployee
        fields = [
            'id', 'business', 'user', 'role', 'is_active',
            'hired_at', 'hired_by', 'deactivated_at', 'deactivated_by',
            'shift_start_time', 'shift_end_time', 'daily_transaction_limit',
            'notes'
        ]
    
    def resolve_effective_permissions(self, info):
        """Return the effective permissions for this employee"""
        return self.get_effective_permissions()
    
    def resolve_is_within_shift(self, info):
        """Check if employee is currently within their shift"""
        return self.is_within_shift()


class EmployerBusinessType(graphene.ObjectType):
    """Represents a business where user is employed"""
    
    business = graphene.Field('users.schema.BusinessType')
    employee_record = graphene.Field(BusinessEmployeeType)
    role = graphene.String()
    permissions = graphene.JSONString()


class EmployeeInvitationType(DjangoObjectType):
    """GraphQL type for employee invitations"""
    
    is_expired = graphene.Boolean()
    permissions = graphene.JSONString()
    
    class Meta:
        model = EmployeeInvitation
        fields = [
            'id', 'business', 'invitation_code', 'employee_phone',
            'employee_phone_country', 'employee_name', 'role',
            'status', 'expires_at', 'invited_by', 'accepted_by',
            'accepted_at', 'message', 'created_at'
        ]
    
    def resolve_is_expired(self, info):
        return self.is_expired


class EmployeeActivityLogType(DjangoObjectType):
    """GraphQL type for employee activity logs"""
    
    details = graphene.JSONString()
    
    class Meta:
        model = EmployeeActivityLog
        fields = [
            'id', 'business', 'employee', 'action', 'timestamp',
            'invoice_id', 'transaction_id', 'amount', 'ip_address'
        ]
    

class AddBusinessEmployeeInput(graphene.InputObjectType):
    user_phone = graphene.String(required=True, description="Phone number of employee to add")
    role = graphene.String(default_value='cashier')
    custom_permissions = graphene.JSONString(description="Custom permissions overriding role defaults")
    shift_start_time = graphene.String(description="Daily shift start time (HH:MM)")
    shift_end_time = graphene.String(description="Daily shift end time (HH:MM)")
    daily_transaction_limit = graphene.Decimal(description="Maximum daily transaction amount")
    notes = graphene.String()


class UpdateBusinessEmployeeInput(graphene.InputObjectType):
    employee_id = graphene.ID(required=True)
    role = graphene.String()
    custom_permissions = graphene.JSONString()
    shift_start_time = graphene.String()
    shift_end_time = graphene.String()
    daily_transaction_limit = graphene.Decimal()
    notes = graphene.String()
    is_active = graphene.Boolean()


class RemoveBusinessEmployeeInput(graphene.InputObjectType):
    employee_id = graphene.ID(required=True)


class AddBusinessEmployee(graphene.Mutation):
    class Arguments:
        input = AddBusinessEmployeeInput(required=True)
    
    employee = graphene.Field(BusinessEmployeeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        try:
            # Use JWT context to get the current business
            jwt_context = require_business_context(info)
            business_id = jwt_context['business_id']
            
            # Get the business and verify access
            business = Business.objects.get(
                id=business_id,
                accounts__user=user,
                accounts__account_type='business',
                deleted_at__isnull=True
            )
            
            # Find employee user by phone
            employee_user = User.objects.filter(
                phone_number=input.user_phone,
                is_active=True
            ).first()
            
            if not employee_user:
                return cls(success=False, errors=["User with this phone number not found"])
            
            if employee_user == user:
                return cls(success=False, errors=["Cannot add yourself as an employee"])
            
            # Check if already an employee
            if BusinessEmployee.objects.filter(
                business=business,
                user=employee_user,
                deleted_at__isnull=True
            ).exists():
                return cls(success=False, errors=["User is already an employee of this business"])
            
            # Create employee record
            with transaction.atomic():
                employee = BusinessEmployee.objects.create(
                    business=business,
                    user=employee_user,
                    role=input.role or 'cashier',
                    hired_by=user,
                    permissions=input.custom_permissions or {},
                    notes=input.notes or ''
                )
                
                # Set optional fields
                if input.shift_start_time:
                    employee.shift_start_time = input.shift_start_time
                if input.shift_end_time:
                    employee.shift_end_time = input.shift_end_time
                if input.daily_transaction_limit is not None:
                    employee.daily_transaction_limit = input.daily_transaction_limit
                
                employee.save()
                
                # TODO: Send notification to employee about being added
                
                return cls(employee=employee, success=True)
                
        except Business.DoesNotExist:
            return cls(success=False, errors=["Business not found or access denied"])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class UpdateBusinessEmployee(graphene.Mutation):
    class Arguments:
        input = UpdateBusinessEmployeeInput(required=True)
    
    employee = graphene.Field(BusinessEmployeeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        # Get account context
        account = get_account_from_context(info.context)
        if not account or account.account_type != 'business':
            return cls(success=False, errors=["Must be operating as business account"])
        
        try:
            # Get employee record
            employee = BusinessEmployee.objects.select_related('business').get(
                id=input.employee_id,
                deleted_at__isnull=True
            )
            
            # Check permission
            if not employee.business.accounts.filter(user=user).exists():
                return cls(success=False, errors=["You don't have permission to manage this employee"])
            
            # Prevent business owner from deactivating themselves
            if employee.user == user and input.is_active is False:
                return cls(success=False, errors=["Business owners cannot deactivate themselves. Transfer ownership first if needed."])
            
            # Update fields
            with transaction.atomic():
                if input.role is not None:
                    employee.role = input.role
                if input.custom_permissions is not None:
                    employee.permissions = input.custom_permissions
                if input.shift_start_time is not None:
                    employee.shift_start_time = input.shift_start_time if input.shift_start_time else None
                if input.shift_end_time is not None:
                    employee.shift_end_time = input.shift_end_time if input.shift_end_time else None
                if input.daily_transaction_limit is not None:
                    employee.daily_transaction_limit = input.daily_transaction_limit
                if input.notes is not None:
                    employee.notes = input.notes
                if input.is_active is not None:
                    if input.is_active:
                        employee.reactivate()
                    else:
                        employee.deactivate(user)
                
                employee.save()
                
                return cls(employee=employee, success=True)
                
        except BusinessEmployee.DoesNotExist:
            return cls(success=False, errors=["Employee not found"])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class RemoveBusinessEmployee(graphene.Mutation):
    class Arguments:
        input = RemoveBusinessEmployeeInput(required=True)
    
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        # Get account context
        account = get_account_from_context(info.context)
        if not account or account.account_type != 'business':
            return cls(success=False, errors=["Must be operating as business account"])
        
        try:
            # Get employee record
            employee = BusinessEmployee.objects.select_related('business').get(
                id=input.employee_id,
                deleted_at__isnull=True
            )
            
            # Check permission
            if not employee.business.accounts.filter(user=user).exists():
                return cls(success=False, errors=["You don't have permission to remove this employee"])
            
            # Prevent business owner from removing themselves
            if employee.user == user:
                return cls(success=False, errors=["Business owners cannot remove themselves. Transfer ownership first if needed."])
            
            # Soft delete
            with transaction.atomic():
                employee.soft_delete()
                
                # TODO: Send notification to employee about removal
                
                return cls(success=True)
                
        except BusinessEmployee.DoesNotExist:
            return cls(success=False, errors=["Employee not found"])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class InviteEmployeeInput(graphene.InputObjectType):
    employee_phone = graphene.String(required=True)
    employee_phone_country = graphene.String(required=True)
    employee_name = graphene.String()
    role = graphene.String(default_value='cashier')
    custom_permissions = graphene.JSONString()
    message = graphene.String()
    expires_in_days = graphene.Int(default_value=7)


class InviteEmployee(graphene.Mutation):
    class Arguments:
        input = InviteEmployeeInput(required=True)
    
    invitation = graphene.Field(EmployeeInvitationType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        try:
            # Use JWT context to get the current business
            jwt_context = require_business_context(info)
            business_id = jwt_context['business_id']
            
            # Get the business and verify access
            business = Business.objects.get(
                id=business_id,
                accounts__user=user,
                accounts__account_type='business',
                deleted_at__isnull=True
            )
            
            # Check if trying to invite themselves
            if (user.phone_number == input.employee_phone and 
                user.phone_country == input.employee_phone_country):
                return cls(success=False, errors=["You cannot invite yourself as an employee. You are already the owner."])
            
            # Check if user already exists with this phone number
            existing_user = User.objects.filter(
                phone_number=input.employee_phone,
                phone_country=input.employee_phone_country
            ).first()
            
            if existing_user:
                # Check if already an active employee
                existing_employee = BusinessEmployee.objects.filter(
                    business=business, 
                    user=existing_user,
                    deleted_at__isnull=True
                ).first()
                
                if existing_employee:
                    if existing_employee.is_active:
                        return cls(success=False, errors=["This user is already an active employee of your business"])
                    else:
                        return cls(success=False, errors=["This user is an inactive employee. Please reactivate them instead of sending a new invitation"])
            
            # Check for pending invitations
            pending_invitation = EmployeeInvitation.objects.filter(
                business=business,
                employee_phone=input.employee_phone,
                employee_phone_country=input.employee_phone_country,
                status='pending'
            ).first()
            
            if pending_invitation and not pending_invitation.is_expired:
                return cls(success=False, errors=["An invitation is already pending for this phone number"])
            
            # Create invitation
            invitation = EmployeeInvitation.objects.create(
                business=business,
                employee_phone=input.employee_phone,
                employee_phone_country=input.employee_phone_country,
                employee_name=input.employee_name or '',
                role=input.role,
                permissions=input.custom_permissions or {},  # Default to empty dict if None
                invited_by=user,
                expires_at=timezone.now() + timedelta(days=input.expires_in_days),
                message=input.message or ''
            )
            
            # TODO: Send SMS or notification to the employee
            
            return cls(invitation=invitation, success=True)
            
        except Business.DoesNotExist:
            return cls(success=False, errors=["Business not found or access denied"])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class AcceptInvitation(graphene.Mutation):
    class Arguments:
        invitation_code = graphene.String(required=True)
    
    employee = graphene.Field(BusinessEmployeeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, invitation_code):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        try:
            invitation = EmployeeInvitation.objects.get(
                invitation_code=invitation_code
            )
            
            # Verify phone number matches
            if (invitation.employee_phone != user.phone_number or 
                invitation.employee_phone_country != user.phone_country):
                return cls(success=False, errors=["This invitation is not for your phone number"])
            
            # Accept the invitation
            employee = invitation.accept(user)
            
            return cls(employee=employee, success=True)
            
        except EmployeeInvitation.DoesNotExist:
            return cls(success=False, errors=["Invalid invitation code"])
        except ValueError as e:
            return cls(success=False, errors=[str(e)])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class CancelInvitation(graphene.Mutation):
    class Arguments:
        invitation_id = graphene.ID(required=True)
    
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, invitation_id):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, errors=["Authentication required"])
        
        try:
            invitation = EmployeeInvitation.objects.get(id=invitation_id)
            
            # Verify user has permission (business owner or admin)
            account = get_account_from_context(info.context, user)
            if not account or account.business != invitation.business:
                return cls(success=False, errors=["You don't have permission to cancel this invitation"])
            
            invitation.cancel()
            
            return cls(success=True)
            
        except EmployeeInvitation.DoesNotExist:
            return cls(success=False, errors=["Invitation not found"])
        except ValueError as e:
            return cls(success=False, errors=[str(e)])
        except Exception as e:
            return cls(success=False, errors=[str(e)])


class EmployeeQueries(graphene.ObjectType):
    """Employee-related queries"""
    
    my_employer_businesses = graphene.List(
        EmployerBusinessType,
        description="Get businesses where current user is an employee"
    )
    
    business_employees = graphene.List(
        BusinessEmployeeType,
        business_id=graphene.ID(required=True),
        include_inactive=graphene.Boolean(default_value=False),
        description="Get employees of a business (owner only)"
    )
    
    business_invitations = graphene.List(
        EmployeeInvitationType,
        business_id=graphene.ID(required=True),
        status=graphene.String(),
        description="Get employee invitations for a business"
    )
    
    # New JWT-context-aware queries that don't require businessId parameters
    current_business_employees = graphene.List(
        BusinessEmployeeType,
        include_inactive=graphene.Boolean(default_value=False),
        first=graphene.Int(description="Number of employees to fetch"),
        after=graphene.String(description="Cursor for pagination"),
        description="Get employees of current business (uses JWT context)"
    )
    
    current_business_invitations = graphene.List(
        EmployeeInvitationType,
        status=graphene.String(),
        description="Get invitations for current business (uses JWT context)"
    )
    
    my_invitations = graphene.List(
        EmployeeInvitationType,
        description="Get pending invitations for current user"
    )
    
    employee_activity_logs = graphene.List(
        EmployeeActivityLogType,
        business_id=graphene.ID(required=True),
        employee_id=graphene.ID(),
        action=graphene.String(),
        limit=graphene.Int(default_value=100),
        description="Get employee activity logs for a business"
    )
    
    def resolve_my_employer_businesses(self, info):
        """Get businesses where user is employed"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Get active employment records
        employment_records = BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            deleted_at__isnull=True
        ).select_related('business')
        
        results = []
        for record in employment_records:
            results.append({
                'business': record.business,
                'employee_record': record,
                'role': record.role,
                'permissions': record.get_effective_permissions()
            })
        
        return results
    
    def resolve_business_employees(self, info, business_id, include_inactive=False):
        """Get employees of a business"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Check if user owns the business
        try:
            business = Business.objects.get(
                id=business_id,
                accounts__user=user,
                accounts__account_type='business',
                deleted_at__isnull=True
            )
        except Business.DoesNotExist:
            return []
        
        # Get employees - exclude the business owner
        queryset = BusinessEmployee.objects.filter(
            business=business,
            deleted_at__isnull=True
        ).exclude(
            user=user  # Exclude the business owner from the employees list
        ).select_related('user', 'hired_by', 'deactivated_by')
        
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        
        return queryset
    
    def resolve_business_invitations(self, info, business_id, status=None):
        """Get invitations for a business"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Verify user owns the business
        try:
            business = Business.objects.get(id=business_id)
            account = get_account_from_context(info.context, user)
            if not account or account.business != business:
                return []
        except Business.DoesNotExist:
            return []
        
        queryset = EmployeeInvitation.objects.filter(
            business=business,
            deleted_at__isnull=True
        )
        
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.select_related('invited_by', 'accepted_by')
    
    def resolve_my_invitations(self, info):
        """Get pending invitations for current user"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        return EmployeeInvitation.objects.filter(
            employee_phone=user.phone_number,
            employee_phone_country=user.phone_country,
            status='pending',
            expires_at__gt=timezone.now(),
            deleted_at__isnull=True
        ).select_related('business', 'invited_by')
    
    def resolve_employee_activity_logs(self, info, business_id, employee_id=None, action=None, limit=100):
        """Get activity logs for a business"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Verify user has permission to view logs
        try:
            business = Business.objects.get(id=business_id)
            account = get_account_from_context(info.context, user)
            
            # Check if user is owner or has permission to view logs
            if account and account.business == business:
                # Owner can see all logs
                pass
            else:
                # Check if user is an employee with appropriate permissions
                employee = BusinessEmployee.objects.filter(
                    business=business,
                    user=user,
                    is_active=True
                ).first()
                
                if not employee or not employee.has_permission('view_analytics'):
                    return []
        except Business.DoesNotExist:
            return []
        
        queryset = EmployeeActivityLog.objects.filter(business=business)
        
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        
        if action:
            queryset = queryset.filter(action=action)
        
        return queryset.select_related('employee')[:limit]
    
    # New JWT-context-aware resolvers
    def resolve_current_business_employees(self, info, include_inactive=False, first=None, after=None):
        """Get employees of current business using JWT context with pagination"""
        try:
            # Require business context from JWT
            jwt_context = require_business_context(info)
            business_id = jwt_context['business_id']
            user = info.context.user
            
            # Get the business and validate access
            business = Business.objects.get(
                id=business_id,
                accounts__user=user,
                accounts__account_type='business',
                deleted_at__isnull=True
            )
            
            # Get employees - exclude the business owner
            queryset = BusinessEmployee.objects.filter(
                business=business,
                deleted_at__isnull=True
            ).exclude(
                user=user  # Exclude the business owner from the employees list
            ).select_related('user').order_by('id')  # Consistent ordering for pagination
            
            if not include_inactive:
                queryset = queryset.filter(is_active=True)
            
            # Handle pagination
            if after:
                # Decode cursor - for simplicity, using ID as cursor
                try:
                    cursor_id = int(after)
                    queryset = queryset.filter(id__gt=cursor_id)
                except (ValueError, TypeError):
                    pass  # Invalid cursor, ignore
            
            if first:
                queryset = queryset[:first]
                
            return queryset
            
        except Exception as e:
            return []
    
    def resolve_current_business_invitations(self, info, status=None):
        """Get invitations for current business using JWT context"""
        try:
            # Require business context from JWT
            jwt_context = require_business_context(info)
            business_id = jwt_context['business_id']
            user = info.context.user
            
            # Get the business and validate access
            business = Business.objects.get(
                id=business_id,
                accounts__user=user,
                accounts__account_type='business',
                deleted_at__isnull=True
            )
            
            # Get invitations
            queryset = EmployeeInvitation.objects.filter(
                business=business,
                deleted_at__isnull=True
            )
            
            if status:
                queryset = queryset.filter(status=status)
                
            return queryset.select_related('invited_by', 'accepted_by')
            
        except Exception as e:
            return []


class EmployeeMutations(graphene.ObjectType):
    """Employee-related mutations"""
    
    add_business_employee = AddBusinessEmployee.Field()
    update_business_employee = UpdateBusinessEmployee.Field()
    remove_business_employee = RemoveBusinessEmployee.Field()
    invite_employee = InviteEmployee.Field()
    accept_invitation = AcceptInvitation.Field()
    cancel_invitation = CancelInvitation.Field()