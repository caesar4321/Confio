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
    transactions_to_sign = graphene.List(graphene.JSONString, description="Unsigned transactions for client to sign")
    sponsor_transactions = graphene.List(graphene.JSONString, description="Sponsor transactions (pre-signed)")
    group_id = graphene.String(description="Transaction group ID")
    requires_app_optin = graphene.Boolean(description="Whether user needs to opt into the app")
    app_id = graphene.String(description="Application ID for opt-in")
    
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
            
            # Check if account has Algorand address (not Sui for this operation)
            if not active_account.algorand_address:
                return ConvertUSDCToCUSD(
                    conversion=None,
                    success=False,
                    errors=["Account not initialized with Algorand address"]
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
                    actor_address=active_account.algorand_address,
                    # Conversion details
                    conversion_type='usdc_to_cusd',
                    from_amount=amount_decimal,
                    to_amount=to_amount,
                    exchange_rate=exchange_rate,
                    fee_amount=fee_amount,
                    status='PENDING'
                )
                
                # Build blockchain transactions
                from blockchain.cusd_service import CUSDService
                from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
                from blockchain.algorand_client import AlgorandClient
                import asyncio
                
                cusd_service = CUSDService()
                tx_builder = CUSDTransactionBuilder()
                algod_client = AlgorandClient().algod
                
                # Check if user has Algorand address
                if not active_account.algorand_address:
                    conversion.status = 'FAILED'
                    conversion.save()
                    return ConvertUSDCToCUSD(
                        conversion=None,
                        success=False,
                        errors=["Account not initialized with Algorand address"]
                    )
                
                try:
                    # First check opt-in status
                    opt_in_status = asyncio.run(cusd_service.check_opt_in_status(active_account.algorand_address))
                    
                    if not opt_in_status.get('usdc_opted_in') or not opt_in_status.get('cusd_opted_in'):
                        conversion.status = 'FAILED'
                        conversion.save()
                        return ConvertUSDCToCUSD(
                            conversion=None,
                            success=False,
                            errors=["Please opt-in to USDC and cUSD assets first"]
                        )
                    
                    # Build the transaction group with sponsored fees
                    tx_result = tx_builder.build_mint_transactions(
                        user_address=active_account.algorand_address,
                        usdc_amount=amount_decimal,
                        algod_client=algod_client
                    )
                    
                    if not tx_result.get('success'):
                        # Check if it's an app opt-in issue
                        if tx_result.get('requires_app_optin'):
                            # Don't save as failed - frontend will handle opt-in automatically
                            # No need to show error message since it's handled automatically
                            return ConvertUSDCToCUSD(
                                conversion=None,
                                success=False,
                                errors=[],  # Empty errors - frontend handles this
                                requires_app_optin=True,
                                app_id=str(tx_result.get('app_id')) if tx_result.get('app_id') is not None else None
                            )
                        conversion.status = 'FAILED'
                        conversion.save()
                        return ConvertUSDCToCUSD(
                            conversion=None,
                            success=False,
                            errors=[tx_result.get('error', 'Failed to build transactions')]
                        )
                    
                    # Mark conversion as pending signature
                    conversion.status = 'PENDING_SIG'
                    conversion.save()
                    
                    print(f"[CONVERSION] Conversion {conversion.id} transactions built, awaiting client signature")
                    
                    # Return the transactions for client to sign
                    import sys
                    
                    # Handle new structure with sponsor_transactions array
                    sponsor_txns = tx_result.get('sponsor_transactions', [])
                    
                    # For backward compatibility, also support old sponsor_transaction field
                    if not sponsor_txns and tx_result.get('sponsor_transaction'):
                        sponsor_txns = [tx_result.get('sponsor_transaction')]
                    
                    print(f"[CONVERSION] Returning {len(sponsor_txns)} sponsor transactions", file=sys.stderr)
                    
                    return ConvertUSDCToCUSD(
                        conversion=conversion,
                        success=True,
                        errors=None,
                        transactions_to_sign=tx_result.get('transactions_to_sign'),
                        sponsor_transactions=sponsor_txns,  # Array of sponsor transactions
                        group_id=tx_result.get('group_id')
                    )
                    
                except Exception as e:
                    logger.error(f"Error during transaction building: {e}")
                    conversion.status = 'FAILED'
                    conversion.save()
                    return ConvertUSDCToCUSD(
                        conversion=None,
                        success=False,
                        errors=[f"Transaction building error: {str(e)}"]
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
    transactions_to_sign = graphene.List(graphene.JSONString, description="Unsigned transactions for client to sign")
    sponsor_transactions = graphene.List(graphene.JSONString, description="Sponsor transactions (pre-signed)")
    group_id = graphene.String(description="Transaction group ID")
    requires_app_optin = graphene.Boolean(description="Whether user needs to opt into the app")
    app_id = graphene.String(description="Application ID for opt-in")
    
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
            
            # Check if account has Algorand address (not Sui for this operation)
            if not active_account.algorand_address:
                return ConvertCUSDToUSDC(
                    conversion=None,
                    success=False,
                    errors=["Account not initialized with Algorand address"]
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
                    actor_address=active_account.algorand_address,
                    # Conversion details
                    conversion_type='cusd_to_usdc',
                    from_amount=amount_decimal,
                    to_amount=to_amount,
                    exchange_rate=exchange_rate,
                    fee_amount=fee_amount,
                    status='PENDING'
                )
                
                # Build blockchain transactions
                from blockchain.cusd_service import CUSDService
                from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
                from blockchain.algorand_client import AlgorandClient
                import asyncio
                
                cusd_service = CUSDService()
                tx_builder = CUSDTransactionBuilder()
                algod_client = AlgorandClient().algod
                
                # Check if user has Algorand address
                if not active_account.algorand_address:
                    conversion.status = 'FAILED'
                    conversion.save()
                    return ConvertCUSDToUSDC(
                        conversion=None,
                        success=False,
                        errors=["Account not initialized with Algorand address"]
                    )
                
                try:
                    # First check opt-in status
                    opt_in_status = asyncio.run(cusd_service.check_opt_in_status(active_account.algorand_address))
                    
                    if not opt_in_status.get('usdc_opted_in') or not opt_in_status.get('cusd_opted_in'):
                        conversion.status = 'FAILED'
                        conversion.save()
                        return ConvertCUSDToUSDC(
                            conversion=None,
                            success=False,
                            errors=["Please opt-in to USDC and cUSD assets first"]
                        )
                    
                    # Build the transaction group with sponsored fees
                    tx_result = tx_builder.build_burn_transactions(
                        user_address=active_account.algorand_address,
                        cusd_amount=amount_decimal,
                        algod_client=algod_client
                    )
                    
                    if not tx_result.get('success'):
                        # Check if it's an app opt-in issue
                        if tx_result.get('requires_app_optin'):
                            # Don't save as failed - frontend will handle opt-in automatically
                            # No need to show error message since it's handled automatically
                            return ConvertCUSDToUSDC(
                                conversion=None,
                                success=False,
                                errors=[],  # Empty errors - frontend handles this
                                requires_app_optin=True,
                                app_id=str(tx_result.get('app_id')) if tx_result.get('app_id') is not None else None
                            )
                        conversion.status = 'FAILED'
                        conversion.save()
                        return ConvertCUSDToUSDC(
                            conversion=None,
                            success=False,
                            errors=[tx_result.get('error', 'Failed to build transactions')]
                        )
                    
                    # Mark conversion as pending signature
                    conversion.status = 'PENDING_SIG'
                    conversion.save()
                    
                    print(f"[CONVERSION] Conversion {conversion.id} transactions built, awaiting client signature")
                    
                    # Return the transactions for client to sign
                    # Handle new structure with sponsor_transactions array
                    sponsor_txns = tx_result.get('sponsor_transactions', [])
                    
                    # For backward compatibility, also support old sponsor_transaction field
                    if not sponsor_txns and tx_result.get('sponsor_transaction'):
                        sponsor_txns = [tx_result.get('sponsor_transaction')]
                    
                    return ConvertCUSDToUSDC(
                        conversion=conversion,
                        success=True,
                        errors=None,
                        transactions_to_sign=tx_result.get('transactions_to_sign'),
                        sponsor_transactions=sponsor_txns,  # Array of sponsor transactions
                        group_id=tx_result.get('group_id')
                    )
                    
                except Exception as e:
                    logger.error(f"Error during transaction building: {e}")
                    conversion.status = 'FAILED'
                    conversion.save()
                    return ConvertCUSDToUSDC(
                        conversion=None,
                        success=False,
                        errors=[f"Transaction building error: {str(e)}"]
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

class ExecutePendingConversion(graphene.Mutation):
    """Execute a pending conversion with user signature"""
    class Arguments:
        conversion_id = graphene.ID(required=True, description="ID of the pending conversion")
        signed_transactions = graphene.String(required=True, description="Base64 encoded signed transactions")
    
    success = graphene.Boolean()
    conversion = graphene.Field(ConversionType)
    transaction_id = graphene.String()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, conversion_id, signed_transactions):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ExecutePendingConversion(
                success=False,
                conversion=None,
                transaction_id=None,
                errors=["Authentication required"]
            )
        
        try:
            # Get the conversion (can be PENDING or PENDING_SIG)
            conversion = Conversion.objects.get(
                id=conversion_id,
                status__in=['PENDING', 'PENDING_SIG']
            )
            
            # Verify user owns this conversion
            if conversion.actor_user != user:
                if not (conversion.actor_business and 
                       conversion.actor_business.accounts.filter(user=user).exists()):
                    return ExecutePendingConversion(
                        success=False,
                        conversion=None,
                        transaction_id=None,
                        errors=["Not authorized to execute this conversion"]
                    )
            
            # Import executor
            from blockchain.conversion_executor import execute_signed_conversion_sync
            
            # Execute the conversion with signed transactions
            result = execute_signed_conversion_sync(
                conversion_id=conversion_id,
                signed_transactions=signed_transactions
            )
            
            if result.get('success'):
                # Refresh the conversion from DB
                conversion.refresh_from_db()
                
                # Create notification for successful conversion
                try:
                    from notifications.utils import create_transaction_notification
                    
                    # Determine the conversion direction for the notification
                    if conversion.conversion_type == 'usdc_to_cusd':
                        from_token = 'USDC'
                        to_token = 'cUSD'
                    else:
                        from_token = 'cUSD'
                        to_token = 'USDC'
                    
                    create_transaction_notification(
                        transaction_type='conversion',
                        sender_user=conversion.actor_user,
                        business=conversion.actor_business,
                        amount=str(conversion.to_amount),
                        token_type=to_token,
                        transaction_id=str(conversion.id),
                        transaction_model='Conversion',
                        additional_data={
                            'from_amount': str(conversion.from_amount),
                            'from_token': from_token,
                            'to_amount': str(conversion.to_amount),
                            'to_token': to_token,
                            'transaction_hash': result.get('transaction_id', ''),
                            'conversion_type': conversion.conversion_type
                        }
                    )
                    print(f"[CONVERSION] Notification created for conversion {conversion.id}")
                except Exception as e:
                    logger.error(f"Failed to create conversion notification: {e}")
                    import traceback
                    traceback.print_exc()
                
                return ExecutePendingConversion(
                    success=True,
                    conversion=conversion,
                    transaction_id=result.get('transaction_id'),
                    errors=None
                )
            else:
                return ExecutePendingConversion(
                    success=False,
                    conversion=None,
                    transaction_id=None,
                    errors=[result.get('error', 'Execution failed')]
                )
                
        except Conversion.DoesNotExist:
            return ExecutePendingConversion(
                success=False,
                conversion=None,
                transaction_id=None,
                errors=["Conversion not found or not pending"]
            )
        except Exception as e:
            logger.error(f"Error executing conversion: {e}")
            return ExecutePendingConversion(
                success=False,
                conversion=None,
                transaction_id=None,
                errors=[str(e)]
            )


class GetConversionTransactions(graphene.Mutation):
    """Get unsigned transactions for a pending conversion (for client-side signing)"""
    class Arguments:
        conversion_id = graphene.ID(required=True, description="ID of the pending conversion")
    
    success = graphene.Boolean()
    transactions = graphene.List(graphene.String, description="Base64 encoded unsigned transactions")
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, conversion_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return GetConversionTransactions(
                success=False,
                transactions=None,
                errors=["Authentication required"]
            )
        
        try:
            # Get the conversion (can be PENDING or PENDING_SIG)
            conversion = Conversion.objects.get(
                id=conversion_id,
                status__in=['PENDING', 'PENDING_SIG']
            )
            
            # Verify user owns this conversion
            if conversion.actor_user != user:
                if not (conversion.actor_business and 
                       conversion.actor_business.accounts.filter(user=user).exists()):
                    return GetConversionTransactions(
                        success=False,
                        transactions=None,
                        errors=["Not authorized to access this conversion"]
                    )
            
            # TODO: Generate unsigned transactions for the conversion
            # This would create the actual Algorand transactions
            # that the client can sign with their private key
            
            # For now, return placeholder
            return GetConversionTransactions(
                success=True,
                transactions=[],  # Would contain base64 encoded transactions
                errors=None
            )
            
        except Conversion.DoesNotExist:
            return GetConversionTransactions(
                success=False,
                transactions=None,
                errors=["Conversion not found or not pending"]
            )
        except Exception as e:
            logger.error(f"Error getting conversion transactions: {e}")
            return GetConversionTransactions(
                success=False,
                transactions=None,
                errors=[str(e)]
            )


class OptInToCUSDApp(graphene.Mutation):
    """Mutation to opt into the cUSD application with sponsorship"""
    
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    transaction_to_sign = graphene.JSONString(description="Unsigned transaction for client to sign")
    transactions_to_sign = graphene.List(graphene.JSONString, description="User transactions to sign")
    sponsor_transactions = graphene.List(graphene.JSONString, description="Sponsor transactions (pre-signed)")
    group_id = graphene.String(description="Transaction group ID")
    total_fee = graphene.String(description="Total fees being sponsored")
    funding_amount = graphene.String(description="Amount being funded to user")
    
    @classmethod
    def mutate(cls, root, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return OptInToCUSDApp(
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Get JWT context with validation
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                return OptInToCUSDApp(
                    success=False,
                    errors=["No active account"]
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            # Get the user's active account
            if account_type == 'business' and business_id:
                from users.models import Account
                active_account = Account.objects.filter(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                ).first()
            else:
                active_account = user.accounts.filter(
                    account_type=account_type,
                    account_index=account_index
                ).first()
            
            if not active_account or not active_account.algorand_address:
                return OptInToCUSDApp(
                    success=False,
                    errors=["Active account not found or not initialized"]
                )
            
            # Check if account needs funding first
            import logging
            from blockchain.account_funding_service import account_funding_service
            from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
            from blockchain.algorand_client import AlgorandClient
            
            logger = logging.getLogger(__name__)
            algod_client = AlgorandClient().algod
            
            # Calculate and provide funding if needed
            funding_result = account_funding_service.fund_account_for_optin(
                active_account.algorand_address
            )
            
            if not funding_result.get('success') and not funding_result.get('already_funded'):
                # Funding failed
                logger.error(f"Failed to fund account: {funding_result.get('error')}")
                # Continue anyway - maybe user has just enough balance
            elif funding_result.get('transaction_id'):
                logger.info(f"Funded account with {funding_result.get('amount_funded_algo')} ALGO")
            
            # Build app opt-in transaction
            tx_builder = CUSDTransactionBuilder()
            
            tx_result = tx_builder.build_app_optin_transaction(
                user_address=active_account.algorand_address,
                algod_client=algod_client
            )
            
            if not tx_result.get('success'):
                return OptInToCUSDApp(
                    success=False,
                    errors=[tx_result.get('error', 'Failed to build opt-in transaction')]
                )
            
            # Handle both old and new formats
            if 'transactions_to_sign' in tx_result:
                # New sponsored format
                return OptInToCUSDApp(
                    success=True,
                    transactions_to_sign=tx_result.get('transactions_to_sign'),
                    sponsor_transactions=tx_result.get('sponsor_transactions'),
                    group_id=tx_result.get('group_id'),
                    total_fee=tx_result.get('total_fee'),
                    funding_amount=tx_result.get('funding_amount')
                )
            else:
                # Old format (backwards compatibility)
                return OptInToCUSDApp(
                    success=True,
                    transaction_to_sign=tx_result.get('transaction')
                )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error during app opt-in: {e}")
            return OptInToCUSDApp(
                success=False,
                errors=[str(e)]
            )


class ExecuteCUSDAppOptIn(graphene.Mutation):
    """Execute a signed cUSD app opt-in transaction"""
    
    class Arguments:
        signed_transaction = graphene.String(required=True, description="Base64 encoded signed transaction")
    
    success = graphene.Boolean()
    transaction_id = graphene.String()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, signed_transaction):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ExecuteCUSDAppOptIn(
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            import base64
            import logging
            from blockchain.algorand_client import AlgorandClient
            from algosdk.transaction import wait_for_confirmation
            
            logger = logging.getLogger(__name__)
            
            # Decode the signed transaction
            signed_txn_bytes = base64.b64decode(signed_transaction)
            
            # Submit to network
            algod_client = AlgorandClient().algod
            tx_id = algod_client.send_raw_transaction(base64.b64encode(signed_txn_bytes).decode('utf-8'))
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            
            logger.info(f"App opt-in transaction {tx_id} confirmed in round {confirmed_txn.get('confirmed-round', 0)}")
            
            return ExecuteCUSDAppOptIn(
                success=True,
                transaction_id=tx_id,
                errors=None
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error executing app opt-in: {e}")
            return ExecuteCUSDAppOptIn(
                success=False,
                transaction_id=None,
                errors=[str(e)]
            )


class Mutation(graphene.ObjectType):
    """Mutation definitions for conversions"""
    convert_usdc_to_cusd = ConvertUSDCToCUSD.Field()
    convert_cusd_to_usdc = ConvertCUSDToUSDC.Field()
    execute_pending_conversion = ExecutePendingConversion.Field()
    get_conversion_transactions = GetConversionTransactions.Field()
    test_conversion = TestConversion.Field()
    opt_in_to_cusd_app = OptInToCUSDApp.Field()
    execute_cusd_app_opt_in = ExecuteCUSDAppOptIn.Field()
