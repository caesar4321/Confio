import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from .models import Conversion
from send.validators import validate_transaction_amount


class ConversionType(DjangoObjectType):
    """GraphQL type for Conversion model"""
    class Meta:
        model = Conversion
        fields = (
            'id',
            'conversion_id',
            'actor_user',
            'actor_business',
            'actor_type',
            'actor_display_name',
            'actor_address',
            'conversion_type',
            'from_amount',
            'to_amount',
            'exchange_rate',
            'fee_amount',
            'from_transaction_hash',
            'to_transaction_hash',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at',
        )
    
    # Add custom fields
    from_token = graphene.String()
    to_token = graphene.String()
    
    def resolve_from_token(self, info):
        """Resolve the source token based on conversion type"""
        return 'USDC' if self.conversion_type == 'usdc_to_cusd' else 'cUSD'
    
    def resolve_to_token(self, info):
        """Resolve the destination token based on conversion type"""
        return 'cUSD' if self.conversion_type == 'usdc_to_cusd' else 'USDC'


class ConvertUSDCToCUSD(graphene.Mutation):
    """Mutation to convert USDC to cUSD"""
    class Arguments:
        amount = graphene.String(required=True, description="Amount of USDC to convert")
    
    conversion = graphene.Field(ConversionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, amount):
        # Log to a file to ensure we see the output
        import datetime
        with open('/tmp/conversion_debug.log', 'a') as f:
            f.write(f"\n[{datetime.datetime.now()}] ConvertUSDCToCUSD called - amount: {amount}\n")
            
        user = getattr(info.context, 'user', None)
        
        with open('/tmp/conversion_debug.log', 'a') as f:
            f.write(f"  User: {user}, Authenticated: {user and getattr(user, 'is_authenticated', False)}\n")
        import sys
        print(f"[CONVERSION] ConvertUSDCToCUSD called - amount: {amount}, user: {user}", file=sys.stderr)
        
        if not (user and getattr(user, 'is_authenticated', False)):
            return ConvertUSDCToCUSD(
                conversion=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Validate amount
            validate_transaction_amount(amount)
            amount_decimal = Decimal(amount)
            
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not jwt_context:
                return ConvertUSDCToCUSD(
                    conversion=None,
                    success=False,
                    errors=["No access or permission to perform conversions"]
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            print(f"[CONVERSION] JWT context: type={account_type}, index={account_index}, business_id={business_id}")
            
            # Get the user's active account using JWT context
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT
                # This will find the business account regardless of who owns it
                from users.models import Account
                active_account = Account.objects.filter(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                ).first()
            else:
                # For personal accounts
                active_account = user.accounts.filter(
                    account_type=account_type,
                    account_index=account_index
                ).first()
            
            print(f"[CONVERSION] Active account found: {active_account}")
            
            if not active_account:
                return ConvertUSDCToCUSD(
                    conversion=None,
                    success=False,
                    errors=["Active account not found"]
                )
            
            # Check if account has Sui address
            if not active_account.sui_address:
                return ConvertUSDCToCUSD(
                    conversion=None,
                    success=False,
                    errors=["Account not initialized with Sui address"]
                )
            
            # Determine actor fields
            if active_account.account_type == 'business':
                actor_type = 'business'
                actor_user = None
                actor_business = active_account.business
                actor_display_name = active_account.business.name if active_account.business else ''
            else:
                actor_type = 'user'
                actor_user = user
                actor_business = None
                actor_display_name = user.username
            
            # TODO: Check USDC balance on blockchain
            # For now, we'll create the conversion record
            
            # Calculate conversion (1:1 for now, no fees)
            exchange_rate = Decimal('1.000000')
            fee_amount = Decimal('0')
            to_amount = amount_decimal * exchange_rate - fee_amount
            
            # Create conversion record
            print(f"[CONVERSION] Creating conversion: actor_type={actor_type}, actor_user={actor_user}, actor_business={actor_business}")
            
            with transaction.atomic():
                conversion = Conversion.objects.create(
                    # Actor fields
                    actor_type=actor_type,
                    actor_user=actor_user,
                    actor_business=actor_business,
                    actor_display_name=actor_display_name,
                    actor_address=active_account.sui_address,
                    # Conversion details
                    conversion_type='usdc_to_cusd',
                    from_amount=amount_decimal,
                    to_amount=to_amount,
                    exchange_rate=exchange_rate,
                    fee_amount=fee_amount,
                    status='PENDING'
                )
                
                # TODO: Implement blockchain conversion logic
                # For now, we'll simulate completion
                # In production, this would be handled by a background task
                import time
                import uuid
                time.sleep(0.1)  # Simulate processing
                
                # Generate mock transaction hashes
                conversion.from_transaction_hash = f"0x{uuid.uuid4().hex}"
                conversion.to_transaction_hash = f"0x{uuid.uuid4().hex}"
                conversion.mark_completed()
                
                # Create notification for conversion completion
                from notifications.utils import create_transaction_notification
                notification_user = actor_user if actor_user else (actor_business.accounts.first().user if actor_business else None)
                if notification_user:
                    create_transaction_notification(
                        transaction_type='conversion',
                        sender_user=notification_user,
                        amount=str(amount_decimal),
                        token_type='USDC',
                        transaction_id=str(conversion.id),
                        transaction_model='Conversion',
                        additional_data={
                            'from_amount': str(amount_decimal),
                            'from_token': 'USDC',
                            'to_amount': str(to_amount),
                            'to_token': 'cUSD',
                            'conversion_type': 'usdc_to_cusd',
                            'exchange_rate': str(exchange_rate),
                            'fee_amount': str(fee_amount)
                        }
                    )
            
            print(f"[CONVERSION] Conversion created successfully: {conversion.id}")
            
            # Verify the conversion was actually saved
            saved_conversion = Conversion.objects.filter(id=conversion.id).first()
            if not saved_conversion:
                print(f"[CONVERSION] ERROR: Conversion {conversion.id} not found in database after save!")
                return ConvertUSDCToCUSD(
                    conversion=None,
                    success=False,
                    errors=["Conversion not saved to database"]
                )
            
            return ConvertUSDCToCUSD(
                conversion=conversion,
                success=True,
                errors=None
            )
        
        except ValidationError as e:
            print(f"[CONVERSION] Validation error: {e}")
            return ConvertUSDCToCUSD(
                conversion=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            print(f"[CONVERSION] Exception during conversion: {e}")
            import traceback
            traceback.print_exc()
            return ConvertUSDCToCUSD(
                conversion=None,
                success=False,
                errors=[str(e)]
            )


class ConvertCUSDToUSDC(graphene.Mutation):
    """Mutation to convert cUSD to USDC"""
    class Arguments:
        amount = graphene.String(required=True, description="Amount of cUSD to convert")
    
    conversion = graphene.Field(ConversionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, amount):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ConvertCUSDToUSDC(
                conversion=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Validate amount
            validate_transaction_amount(amount)
            amount_decimal = Decimal(amount)
            
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not jwt_context:
                return ConvertCUSDToUSDC(
                    conversion=None,
                    success=False,
                    errors=["No access or permission to perform conversions"]
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            print(f"[CONVERSION] JWT context: type={account_type}, index={account_index}, business_id={business_id}")
            
            # Get the user's active account using JWT context
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT
                # This will find the business account regardless of who owns it
                from users.models import Account
                active_account = Account.objects.filter(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                ).first()
            else:
                # For personal accounts
                active_account = user.accounts.filter(
                    account_type=account_type,
                    account_index=account_index
                ).first()
            
            print(f"[CONVERSION] Active account found: {active_account}")
            
            if not active_account:
                return ConvertCUSDToUSDC(
                    conversion=None,
                    success=False,
                    errors=["Active account not found"]
                )
            
            # Check if account has Sui address
            if not active_account.sui_address:
                return ConvertCUSDToUSDC(
                    conversion=None,
                    success=False,
                    errors=["Account not initialized with Sui address"]
                )
            
            # Determine actor fields
            if active_account.account_type == 'business':
                actor_type = 'business'
                actor_user = None
                actor_business = active_account.business
                actor_display_name = active_account.business.name if active_account.business else ''
            else:
                actor_type = 'user'
                actor_user = user
                actor_business = None
                actor_display_name = user.username
            
            # TODO: Check cUSD balance on blockchain
            # For now, we'll create the conversion record
            
            # Calculate conversion (1:1 for now, no fees)
            exchange_rate = Decimal('1.000000')
            fee_amount = Decimal('0')
            to_amount = amount_decimal * exchange_rate - fee_amount
            
            # Create conversion record
            print(f"[CONVERSION] Creating conversion: actor_type={actor_type}, actor_user={actor_user}, actor_business={actor_business}")
            
            with transaction.atomic():
                conversion = Conversion.objects.create(
                    # Actor fields
                    actor_type=actor_type,
                    actor_user=actor_user,
                    actor_business=actor_business,
                    actor_display_name=actor_display_name,
                    actor_address=active_account.sui_address,
                    # Conversion details
                    conversion_type='cusd_to_usdc',
                    from_amount=amount_decimal,
                    to_amount=to_amount,
                    exchange_rate=exchange_rate,
                    fee_amount=fee_amount,
                    status='PENDING'
                )
                
                # TODO: Implement blockchain conversion logic
                # For now, we'll simulate completion
                import time
                import uuid
                time.sleep(0.1)  # Simulate processing
                
                # Generate mock transaction hashes
                conversion.from_transaction_hash = f"0x{uuid.uuid4().hex}"
                conversion.to_transaction_hash = f"0x{uuid.uuid4().hex}"
                conversion.mark_completed()
                
                # Create notification for conversion completion
                from notifications.utils import create_transaction_notification
                notification_user = actor_user if actor_user else (actor_business.accounts.first().user if actor_business else None)
                if notification_user:
                    create_transaction_notification(
                        transaction_type='conversion',
                        sender_user=notification_user,
                        amount=str(amount_decimal),
                        token_type='cUSD',
                        transaction_id=str(conversion.id),
                        transaction_model='Conversion',
                        additional_data={
                            'from_amount': str(amount_decimal),
                            'from_token': 'cUSD',
                            'to_amount': str(to_amount),
                            'to_token': 'USDC',
                            'conversion_type': 'cusd_to_usdc',
                            'exchange_rate': str(exchange_rate),
                            'fee_amount': str(fee_amount)
                        }
                    )
            
            return ConvertCUSDToUSDC(
                conversion=conversion,
                success=True,
                errors=None
            )
        
        except ValidationError as e:
            return ConvertCUSDToUSDC(
                conversion=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return ConvertCUSDToUSDC(
                conversion=None,
                success=False,
                errors=[str(e)]
            )


class Query(graphene.ObjectType):
    """Query definitions for conversions"""
    conversions = graphene.List(
        ConversionType,
        limit=graphene.Int(),
        status=graphene.String(),
        conversion_type=graphene.String()
    )
    conversion = graphene.Field(ConversionType, conversion_id=graphene.String())
    
    def resolve_conversions(self, info, limit=None, status=None, conversion_type=None):
        """Resolve user's conversions for active account"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        # Get JWT context with validation and permission check
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_transactions')
        if not jwt_context:
            return []
            
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Get active account using JWT context
        if account_type == 'business' and business_id:
            # For business accounts, find by business_id from JWT
            from users.models import Account
            active_account = Account.objects.filter(
                account_type='business',
                account_index=account_index,
                business_id=business_id
            ).first()
        else:
            # For personal accounts
            active_account = user.accounts.filter(
                account_type=account_type,
                account_index=account_index
            ).first()
        
        if not active_account:
            return []
        
        # Filter conversions based on actor
        if active_account.account_type == 'business':
            conversions = Conversion.objects.filter(
                actor_business=active_account.business,
                is_deleted=False
            )
        else:
            conversions = Conversion.objects.filter(
                actor_user=user,
                is_deleted=False
            )
        
        if status:
            conversions = conversions.filter(status=status)
        
        if conversion_type:
            conversions = conversions.filter(conversion_type=conversion_type)
        
        if limit:
            conversions = conversions[:limit]
        
        return conversions
    
    def resolve_conversion(self, info, conversion_id):
        """Resolve a specific conversion by ID"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        try:
            # Get user's conversions from both personal and business accounts
            from django.db.models import Q
            return Conversion.objects.get(
                Q(actor_user=user) | Q(actor_business__user=user),
                conversion_id=conversion_id,
                is_deleted=False
            )
        except Conversion.DoesNotExist:
            return None


class TestConversion(graphene.Mutation):
    """Simple test mutation"""
    success = graphene.Boolean()
    message = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        import logging
        logger = logging.getLogger(__name__)
        logger.error("[TEST] TestConversion mutation called!")
        return TestConversion(success=True, message="Test conversion mutation works!")

class Mutation(graphene.ObjectType):
    """Mutation definitions for conversions"""
    convert_usdc_to_cusd = ConvertUSDCToCUSD.Field()
    convert_cusd_to_usdc = ConvertCUSDToUSDC.Field()
    test_conversion = TestConversion.Field()