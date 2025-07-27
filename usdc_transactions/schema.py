import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models
from .models import USDCDeposit, USDCWithdrawal
from .models_views import UnifiedUSDCTransaction
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


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
    """GraphQL type for UnifiedUSDCTransaction view"""
    class Meta:
        model = UnifiedUSDCTransaction
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
            # Get the user's active account
            active_account = user.accounts.filter(
                account_type=info.context.active_account_type,
                account_index=info.context.active_account_index
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

            # Create the deposit
            deposit = USDCDeposit.objects.create(
                actor_user=user,
                actor_business=actor_business,
                actor_type=actor_type,
                actor_display_name=actor_display_name,
                actor_address=active_account.sui_address or '',
                amount=Decimal(input.amount),
                source_address=input.source_address,
                status='PENDING'
            )

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
        import logging
        logger = logging.getLogger(__name__)
        
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
            # Log context info
            account_type = getattr(info.context, 'active_account_type', 'personal')
            account_index = getattr(info.context, 'active_account_index', 0)
            logger.info(f"Looking for account - Type: {account_type}, Index: {account_index}")
            
            # Get the user's active account
            accounts = user.accounts.all()
            logger.info(f"User has {accounts.count()} accounts")
            
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
            logger.info(f"  actor_address: {active_account.sui_address or ''}")
            logger.info(f"  amount: {input.amount}")
            logger.info(f"  destination_address: {input.destinationAddress}")
            logger.info(f"  service_fee: {input.serviceFee or '0'}")
            
            # Create the withdrawal
            withdrawal = USDCWithdrawal.objects.create(
                actor_user=user,
                actor_business=actor_business,
                actor_type=actor_type,
                actor_display_name=actor_display_name,
                actor_address=active_account.sui_address or '',
                amount=Decimal(input.amount),
                destination_address=input.destinationAddress,
                service_fee=Decimal(input.serviceFee or '0'),
                status='PENDING'
            )
            
            logger.info(f"Withdrawal created successfully with ID: {withdrawal.id}, withdrawal_id: {withdrawal.withdrawal_id}")

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
        
        # Get active account context
        account_type = getattr(info.context, 'active_account_type', 'personal')
        account_index = getattr(info.context, 'active_account_index', 0)
        
        # Filter by user and account context
        queryset = USDCDeposit.objects.filter(
            actor_user=user,
            is_deleted=False
        )
        
        # Filter by business if active account is business
        if account_type == 'business':
            try:
                account = user.accounts.get(
                    account_type=account_type,
                    account_index=account_index
                )
                if account.business:
                    queryset = queryset.filter(actor_business=account.business)
                else:
                    return []
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
        
        # Get active account context
        account_type = getattr(info.context, 'active_account_type', 'personal')
        account_index = getattr(info.context, 'active_account_index', 0)
        
        # Filter by user and account context
        queryset = USDCWithdrawal.objects.filter(
            actor_user=user,
            is_deleted=False
        )
        
        # Filter by business if active account is business
        if account_type == 'business':
            try:
                account = user.accounts.get(
                    account_type=account_type,
                    account_index=account_index
                )
                if account.business:
                    queryset = queryset.filter(actor_business=account.business)
                else:
                    return []
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
        
        # Get active account context
        account_type = getattr(info.context, 'active_account_type', 'personal')
        account_index = getattr(info.context, 'active_account_index', 0)
        
        # Filter by user and account context
        queryset = UnifiedUSDCTransaction.objects.filter(actor_user=user)
        
        # Filter by business if active account is business
        if account_type == 'business':
            try:
                account = user.accounts.get(
                    account_type=account_type,
                    account_index=account_index
                )
                if account.business:
                    queryset = queryset.filter(actor_business=account.business)
                else:
                    return []
            except:
                return []
        else:
            # For personal accounts, exclude business transactions
            queryset = queryset.filter(actor_business__isnull=True)
        
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