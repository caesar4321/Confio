import graphene
from graphene_django import DjangoObjectType
from django.db import transaction
from django.db.models import Q
from .models_employee import BusinessEmployee
from .models import Business, User
from .graphql_auth import get_account_from_context


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
    
    business = graphene.Field('users.graphql_types.BusinessType')
    employee_record = graphene.Field(BusinessEmployeeType)
    role = graphene.String()
    permissions = graphene.JSONString()
    

class AddBusinessEmployeeInput(graphene.InputObjectType):
    business_id = graphene.ID(required=True)
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
        
        # Get account context to ensure user is operating as business owner
        account_data = get_account_from_context(info.context)
        if not account_data or account_data.get('account_type') != 'business':
            return cls(success=False, errors=["Must be operating as business account"])
        
        try:
            # Get the business
            business = Business.objects.get(
                id=input.business_id,
                accounts__user=user,
                accounts__account_type='business',
                is_deleted=False
            )
            
            # Check if user is owner (has account associated with this business)
            if not business.accounts.filter(user=user).exists():
                return cls(success=False, errors=["You don't have permission to manage this business"])
            
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
                is_deleted=False
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
        account_data = get_account_from_context(info.context)
        if not account_data or account_data.get('account_type') != 'business':
            return cls(success=False, errors=["Must be operating as business account"])
        
        try:
            # Get employee record
            employee = BusinessEmployee.objects.select_related('business').get(
                id=input.employee_id,
                is_deleted=False
            )
            
            # Check permission
            if not employee.business.accounts.filter(user=user).exists():
                return cls(success=False, errors=["You don't have permission to manage this employee"])
            
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
        account_data = get_account_from_context(info.context)
        if not account_data or account_data.get('account_type') != 'business':
            return cls(success=False, errors=["Must be operating as business account"])
        
        try:
            # Get employee record
            employee = BusinessEmployee.objects.select_related('business').get(
                id=input.employee_id,
                is_deleted=False
            )
            
            # Check permission
            if not employee.business.accounts.filter(user=user).exists():
                return cls(success=False, errors=["You don't have permission to remove this employee"])
            
            # Soft delete
            with transaction.atomic():
                employee.soft_delete()
                
                # TODO: Send notification to employee about removal
                
                return cls(success=True)
                
        except BusinessEmployee.DoesNotExist:
            return cls(success=False, errors=["Employee not found"])
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
    
    def resolve_my_employer_businesses(self, info):
        """Get businesses where user is employed"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Get active employment records
        employment_records = BusinessEmployee.objects.filter(
            user=user,
            is_active=True,
            is_deleted=False
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
                is_deleted=False
            )
        except Business.DoesNotExist:
            return []
        
        # Get employees
        queryset = BusinessEmployee.objects.filter(
            business=business,
            is_deleted=False
        ).select_related('user', 'hired_by', 'deactivated_by')
        
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        
        return queryset


class EmployeeMutations(graphene.ObjectType):
    """Employee-related mutations"""
    
    add_business_employee = AddBusinessEmployee.Field()
    update_business_employee = UpdateBusinessEmployee.Field()
    remove_business_employee = RemoveBusinessEmployee.Field()