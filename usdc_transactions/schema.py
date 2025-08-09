import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models, transaction as db_transaction
from .models import USDCDeposit, USDCWithdrawal
from .models_unified import UnifiedUSDCTransactionTable
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class USDCDepositType(DjangoObjectType):
    """GraphQL type for USDCDeposit model"""
    class Meta:
        model = USDCDeposit
        fields = (
            'id',
            'deposit_id',
            'actor_user',
            'actor_business',
            'actor_type',
            'actor_display_name',
            'actor_address',
            'amount',
            'source_address',
            'network',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at'
        )


class USDCWithdrawalType(DjangoObjectType):
    """GraphQL type for USDCWithdrawal model"""
    class Meta:
        model = USDCWithdrawal
        fields = (
            'id',
            'withdrawal_id',
            'actor_user',
            'actor_business',
            'actor_type',
            'actor_display_name',
            'actor_address',
            'amount',
            'destination_address',
            'network',
            'service_fee',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at'
        )


class UnifiedUSDCTransactionType(DjangoObjectType):
    """GraphQL type for UnifiedUSDCTransactionTable"""
    class Meta:
        model = UnifiedUSDCTransactionTable
        fields = (
            'transaction_id',
            'transaction_type',
            'actor_user',
            'actor_business',
            'actor_type',
            'actor_display_name',
            'actor_address',
            'amount',
            'currency',
            'secondary_amount',
            'secondary_currency',
            'exchange_rate',
            'network_fee',
            'service_fee',
            'source_address',
            'destination_address',
            'network',
            'status',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at'
        )
    
    # Add custom fields
    formatted_title = graphene.String()
    icon_name = graphene.String()
    icon_color = graphene.String()
    
    def resolve_formatted_title(self, info):
        return self.formatted_title
    
    def resolve_icon_name(self, info):
        return self.icon_name
    
    def resolve_icon_color(self, info):
        return self.icon_color


class USDCDepositInput(graphene.InputObjectType):
    """Input type for creating a USDC deposit"""
    amount = graphene.String(required=True, description="Amount of USDC deposited (e.g., '100.50')")
    source_address = graphene.String(required=True, description="External wallet address that sent the USDC")


class USDCWithdrawalInput(graphene.InputObjectType):
    """Input type for creating a USDC withdrawal"""
    amount = graphene.String(required=True, description="Amount of USDC to withdraw (e.g., '100.50')")
    destinationAddress = graphene.String(required=True, description="External wallet address to receive the USDC")
    serviceFee = graphene.String(description="Confío service fee")


class CreateUSDCDeposit(graphene.Mutation):
    """Mutation for creating a new USDC deposit"""
    class Arguments:
        input = USDCDepositInput(required=True)

    deposit = graphene.Field(USDCDepositType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateUSDCDeposit(
                deposit=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='accept_payments')
            if not jwt_context:
                return CreateUSDCDeposit(
                    deposit=None,
                    success=False,
                    errors=["No access or permission to create deposits"]
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
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
            
            if not active_account:
                return CreateUSDCDeposit(
                    deposit=None,
                    success=False,
                    errors=["Active account not found"]
                )

            # Determine actor type and details
            actor_business = None
            actor_type = 'user'
            actor_display_name = f"{user.first_name} {user.last_name}".strip()
            if not actor_display_name:
                actor_display_name = user.username or f"User {user.id}"
            
            if active_account.account_type == 'business' and active_account.business:
                actor_business = active_account.business
                actor_type = 'business'
                actor_display_name = active_account.business.name

            # Use database transaction to ensure atomicity
            with db_transaction.atomic():
                # Create the deposit
                deposit = USDCDeposit.objects.create(
                    actor_user=user,
                    actor_business=actor_business,
                    actor_type=actor_type,
                    actor_display_name=actor_display_name,
                    actor_address=active_account.algorand_address or '',
                    amount=Decimal(input.amount),
                    source_address=input.source_address,
                    status='PENDING'
                )
                
                # Since KYC is disabled, automatically complete the deposit
                deposit.mark_completed()
                
                # Create notification for deposit - moved inside transaction
                from notifications.utils import create_notification
                from notifications.models import NotificationType as NotificationTypeChoices
                
                logger.info(f"Creating notification for deposit {deposit.deposit_id}")
                notification = create_notification(
                    user=user,
                    business=actor_business,  # Add business context for business accounts
                    notification_type=NotificationTypeChoices.USDC_DEPOSIT_COMPLETED,
                    title="Depósito USDC completado",
                    message=f"Tu depósito de {input.amount} USDC se ha completado exitosamente",
                    data={
                        'transaction_id': str(deposit.deposit_id),
                        'transaction_type': 'deposit',
                        'type': 'deposit',  # Add this for TransactionDetailScreen
                        'amount': str(input.amount),
                        'currency': 'USDC',
                        'status': 'completed',
                        'notification_type': 'USDC_DEPOSIT_COMPLETED',
                        'timestamp': deposit.completed_at.isoformat() if deposit.completed_at else deposit.created_at.isoformat(),
                        'created_at': deposit.created_at.isoformat(),
                    },
                    related_object_type='USDCDeposit',
                    related_object_id=str(deposit.id),
                    action_url=f"confio://transaction/{deposit.deposit_id}"
                )
                
                logger.info(f"Notification created with ID: {notification.id}")

            return CreateUSDCDeposit(
                deposit=deposit,
                success=True,
                errors=None
            )

        except ValidationError as e:
            return CreateUSDCDeposit(
                deposit=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return CreateUSDCDeposit(
                deposit=None,
                success=False,
                errors=[str(e)]
            )


class CreateUSDCWithdrawal(graphene.Mutation):
    """Mutation for creating a new USDC withdrawal"""
    class Arguments:
        input = USDCWithdrawalInput(required=True)

    withdrawal = graphene.Field(USDCWithdrawalType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        logger.info(f"CreateUSDCWithdrawal mutation called with input: {input}")
        
        user = getattr(info.context, 'user', None)
        logger.info(f"User: {user}, Authenticated: {getattr(user, 'is_authenticated', False) if user else False}")
        
        if not (user and getattr(user, 'is_authenticated', False)):
            logger.warning("Authentication failed - no user or not authenticated")
            return CreateUSDCWithdrawal(
                withdrawal=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
            if not jwt_context:
                return CreateUSDCWithdrawal(
                    withdrawal=None,
                    success=False,
                    errors=["No access or permission to create withdrawals"]
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            logger.info(f"Looking for account - Type: {account_type}, Index: {account_index}, Business ID: {business_id}")
            
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
            
            if not active_account:
                logger.error(f"Active account not found for user {user.id} with type={account_type}, index={account_index}")
                # List all accounts for debugging
                all_accounts = list(user.accounts.all().values('account_type', 'account_index', 'id'))
                logger.info(f"User's accounts: {all_accounts}")
                return CreateUSDCWithdrawal(
                    withdrawal=None,
                    success=False,
                    errors=["Active account not found"]
                )

            # Determine actor type and details
            actor_business = None
            actor_type = 'user'
            actor_display_name = f"{user.first_name} {user.last_name}".strip()
            if not actor_display_name:
                actor_display_name = user.username or f"User {user.id}"
            
            if active_account.account_type == 'business' and active_account.business:
                actor_business = active_account.business
                actor_type = 'business'
                actor_display_name = active_account.business.name

            # Log withdrawal details before creation
            logger.info(f"Creating withdrawal with:")
            logger.info(f"  actor_user: {user.id}")
            logger.info(f"  actor_business: {actor_business.id if actor_business else None}")
            logger.info(f"  actor_type: {actor_type}")
            logger.info(f"  actor_display_name: {actor_display_name}")
            logger.info(f"  actor_address: {active_account.algorand_address or ''}")
            logger.info(f"  amount: {input.amount}")
            logger.info(f"  destination_address: {input.destinationAddress}")
            logger.info(f"  service_fee: {input.serviceFee or '0'}")
            
            # Use database transaction to ensure atomicity
            with db_transaction.atomic():
                # Create the withdrawal
                withdrawal = USDCWithdrawal.objects.create(
                    actor_user=user,
                    actor_business=actor_business,
                    actor_type=actor_type,
                    actor_display_name=actor_display_name,
                    actor_address=active_account.algorand_address or '',
                    amount=Decimal(input.amount),
                    destination_address=input.destinationAddress,
                    service_fee=Decimal(input.serviceFee or '0'),
                    status='PENDING'
                )
                
                logger.info(f"Withdrawal created successfully with ID: {withdrawal.id}, withdrawal_id: {withdrawal.withdrawal_id}")
                
                # Since KYC is disabled and we only do AML checks,
                # automatically complete the withdrawal (simulating instant processing)
                # In production, this would be handled by a background task after AML checks
                withdrawal.mark_completed()
                logger.info(f"Withdrawal {withdrawal.id} marked as completed")
                
                # Create notification for withdrawal - moved inside transaction
                from notifications.utils import create_notification
                from notifications.models import NotificationType as NotificationTypeChoices
                
                logger.info(f"Creating notification for withdrawal {withdrawal.withdrawal_id}")
                notification = create_notification(
                    user=user,
                    business=actor_business,  # Add business context for business accounts
                    notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_COMPLETED,
                    title="Retiro USDC completado",
                    message=f"Tu retiro de {input.amount} USDC se ha completado exitosamente",
                    data={
                        'transaction_id': str(withdrawal.withdrawal_id),
                        'transaction_type': 'withdrawal',
                        'type': 'withdrawal',  # Add this for TransactionDetailScreen
                        'amount': str(input.amount),
                        'currency': 'USDC',
                        'destination_address': input.destinationAddress,
                        'status': 'completed',
                        'notification_type': 'USDC_WITHDRAWAL_COMPLETED',
                        'timestamp': withdrawal.completed_at.isoformat() if withdrawal.completed_at else withdrawal.created_at.isoformat(),
                        'created_at': withdrawal.created_at.isoformat(),
                    },
                    related_object_type='USDCWithdrawal',
                    related_object_id=str(withdrawal.id),
                    action_url=f"confio://transaction/{withdrawal.withdrawal_id}"
                )
                
                logger.info(f"Notification created with ID: {notification.id}")

            return CreateUSDCWithdrawal(
                withdrawal=withdrawal,
                success=True,
                errors=None
            )

        except ValidationError as e:
            logger.error(f"ValidationError in CreateUSDCWithdrawal: {str(e)}")
            return CreateUSDCWithdrawal(
                withdrawal=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            logger.error(f"Exception in CreateUSDCWithdrawal: {str(e)}", exc_info=True)
            return CreateUSDCWithdrawal(
                withdrawal=None,
                success=False,
                errors=[str(e)]
            )


class Query(graphene.ObjectType):
    """GraphQL queries for USDC transactions"""
    
    # Individual transaction queries
    usdc_deposits = graphene.List(USDCDepositType, limit=graphene.Int())
    usdc_withdrawals = graphene.List(USDCWithdrawalType, limit=graphene.Int())
    
    # Unified transactions query
    unified_usdc_transactions = graphene.List(
        UnifiedUSDCTransactionType, 
        limit=graphene.Int(),
        offset=graphene.Int(),
        transaction_type=graphene.String()
    )

    def resolve_usdc_deposits(self, info, limit=None):
        """Resolve USDC deposits for the authenticated user's active account"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Filter by user and account context
        queryset = USDCDeposit.objects.filter(
            actor_user=user,
            is_deleted=False
        )
        
        # Filter by business if active account is business
        if account_type == 'business' and business_id:
            try:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                queryset = queryset.filter(actor_business=business)
            except:
                return []
        else:
            # For personal accounts, exclude business deposits
            queryset = queryset.filter(actor_business__isnull=True)
        
        queryset = queryset.order_by('-created_at')
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

    def resolve_usdc_withdrawals(self, info, limit=None):
        """Resolve USDC withdrawals for the authenticated user's active account"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Filter by user and account context
        queryset = USDCWithdrawal.objects.filter(
            actor_user=user,
            is_deleted=False
        )
        
        # Filter by business if active account is business
        if account_type == 'business' and business_id:
            try:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                queryset = queryset.filter(actor_business=business)
            except:
                return []
        else:
            # For personal accounts, exclude business withdrawals
            queryset = queryset.filter(actor_business__isnull=True)
        
        queryset = queryset.order_by('-created_at')
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

    def resolve_unified_usdc_transactions(self, info, limit=None, offset=None, transaction_type=None):
        """Resolve unified USDC transactions (deposits, withdrawals, conversions) for the authenticated user's active account"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Filter by account context
        if account_type == 'business' and business_id:
            try:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                # For business accounts, filter by business
                queryset = UnifiedUSDCTransactionTable.objects.filter(actor_business=business)
            except:
                return []
        else:
            # For personal accounts, filter by user and exclude business transactions
            queryset = UnifiedUSDCTransactionTable.objects.filter(
                actor_user=user,
                actor_business__isnull=True
            )
        
        # Filter by transaction type if specified
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination
        if offset:
            queryset = queryset[offset:]
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset


class Mutation(graphene.ObjectType):
    """GraphQL mutations for USDC transactions"""
    create_usdc_deposit = CreateUSDCDeposit.Field()
    create_usdc_withdrawal = CreateUSDCWithdrawal.Field()