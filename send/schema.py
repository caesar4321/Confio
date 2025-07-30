import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import models, transaction
from .models import SendTransaction
from .validators import validate_transaction_amount, validate_recipient
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import Account
from security.utils import graphql_require_kyc, graphql_require_aml

User = get_user_model()

class SendTransactionInput(graphene.InputObjectType):
    """Input type for creating a send transaction"""
    # Recipient identification - use ONE of these
    recipient_user_id = graphene.ID(description="User ID of the recipient (for Confío users)")
    recipient_phone = graphene.String(description="Phone number of the recipient (for any user)")
    recipient_address = graphene.String(description="Sui address of the recipient (DEPRECATED - use phone or user ID)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")
    idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate sends")
    
    # Display info (for UI purposes only)
    recipient_display_name = graphene.String(description="Display name for the recipient (for UI)")

class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
    class Meta:
        model = SendTransaction
        fields = (
            'id',
            'sender_user', 
            'recipient_user',
            'sender_business',
            'recipient_business',
            'sender_type',
            'recipient_type',
            'sender_display_name',
            'recipient_display_name',
            'sender_phone',
            'recipient_phone',
            'sender_address',
            'recipient_address', 
            'amount', 
            'token_type', 
            'memo', 
            'status',
            'created_at', 
            'updated_at', 
            'transaction_hash',
            'is_invitation',
            'invitation_claimed',
            'invitation_reverted',
            'invitation_expires_at'
        )

class CreateSendTransaction(graphene.Mutation):
    """Mutation for creating a new send transaction"""
    class Arguments:
        input = SendTransactionInput(required=True)

    send_transaction = graphene.Field(SendTransactionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        # Import what we need
        from decimal import Decimal
        from users.jwt_context import get_jwt_business_context_with_validation
        
        # Debug logging
        print(f"CreateSendTransaction: User {user.id} attempting send")
        print(f"CreateSendTransaction: Input received: {input}")
        print(f"CreateSendTransaction: Idempotency key: {getattr(input, 'idempotency_key', 'NOT PROVIDED')}")
        
        # Validate the transaction amount
        try:
            validate_transaction_amount(input.amount)
        except ValidationError as e:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )
        
        # Get JWT context and check permissions
        jwt_context = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not jwt_context:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=["No access or permission to send funds"]
            )

        # Now proceed with database operations
        try:
            with transaction.atomic():
                # Check for existing transaction with same idempotency key
                if hasattr(input, 'idempotency_key') and input.idempotency_key:
                    print(f"CreateSendTransaction: Checking for existing transaction with idempotency key: {input.idempotency_key}")
                    existing_transaction = SendTransaction.objects.filter(
                        sender_user=user,
                        idempotency_key=input.idempotency_key
                    ).first()
                    
                    if existing_transaction:
                        print(f"CreateSendTransaction: Found existing transaction {existing_transaction.id}, returning it")
                        # Return existing transaction to prevent duplicate
                        return CreateSendTransaction(
                            send_transaction=existing_transaction,
                            success=True,
                            errors=None
                        )
                    else:
                        print(f"CreateSendTransaction: No existing transaction found, proceeding with creation")
                else:
                    print(f"CreateSendTransaction: No idempotency key provided")
                    
                account_type = jwt_context['account_type']
                account_index = jwt_context['account_index']
                business_id = jwt_context.get('business_id')
                
                # For business accounts, get the business
                if account_type == 'business' and business_id:
                    from users.models import Business
                    try:
                        business = Business.objects.get(id=business_id)
                        
                        # Get the business account
                        active_account = Account.objects.select_for_update().get(
                            business=business,
                            account_type='business'
                        )
                    except (Business.DoesNotExist, Account.DoesNotExist):
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=False,
                            errors=["Business account not found"]
                        )
                    except PermissionDenied:
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=False,
                            errors=["You don't have permission to send funds from this business account"]
                        )
                else:
                    # Personal account
                    active_account = user.accounts.select_for_update().filter(
                        account_type=account_type,
                        account_index=account_index
                    ).first()
                
                if not active_account or not active_account.sui_address:
                    return CreateSendTransaction(
                        send_transaction=None,
                        success=False,
                        errors=["Sender's Sui address not found"]
                    )
                
                sender_address = active_account.sui_address
                sender_account = active_account  # Store for later use in notifications

                # Find recipient and their Sui address
                recipient_user = None
                recipient_account = None
                recipient_address = None
                
                # Priority 1: Lookup by user ID (most reliable for Confío users)
                if hasattr(input, 'recipient_user_id') and input.recipient_user_id:
                    print(f"CreateSendTransaction: Looking up recipient by user ID: {input.recipient_user_id}")
                    try:
                        recipient_user = User.objects.get(id=input.recipient_user_id)
                        # Get recipient's active personal account
                        recipient_account = recipient_user.accounts.filter(
                            account_type='personal',
                            account_index=0
                        ).first()
                        if recipient_account and recipient_account.sui_address:
                            recipient_address = recipient_account.sui_address
                            print(f"CreateSendTransaction: Found recipient address by user ID: {recipient_address}")
                        else:
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Sui address not found"]
                            )
                    except User.DoesNotExist:
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=False,
                            errors=["Recipient user not found"]
                        )
                
                # Priority 2: Lookup by phone number
                elif hasattr(input, 'recipient_phone') and input.recipient_phone:
                    print(f"CreateSendTransaction: Looking up recipient by phone: {input.recipient_phone}")
                    # Clean and normalize phone number - remove all non-digits
                    cleaned_phone = ''.join(filter(str.isdigit, input.recipient_phone))
                    
                    # Try to find user by phone
                    try:
                        recipient_user = User.objects.get(phone_number=cleaned_phone)
                        # Get recipient's active personal account
                        recipient_account = recipient_user.accounts.filter(
                            account_type='personal',
                            account_index=0
                        ).first()
                        if recipient_account and recipient_account.sui_address:
                            recipient_address = recipient_account.sui_address
                            print(f"CreateSendTransaction: Found recipient address by phone: {recipient_address}")
                        else:
                            # Confío user without address - shouldn't happen
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Sui address not found"]
                            )
                    except User.DoesNotExist:
                        # Non-Confío user - create invitation transaction
                        print(f"CreateSendTransaction: Phone number not found in Confío - creating invitation")
                        # Generate a deterministic external address for this phone number
                        import hashlib
                        phone_hash = hashlib.sha256(cleaned_phone.encode()).hexdigest()
                        recipient_address = f"0x{phone_hash[:64]}"
                        # recipient_user remains None for invitation transactions
                
                # Priority 3: Legacy - direct Sui address (DEPRECATED)
                elif hasattr(input, 'recipient_address') and input.recipient_address:
                    print(f"CreateSendTransaction: WARNING - Using deprecated recipient_address field")
                    recipient_address = input.recipient_address
                    validate_recipient(recipient_address)
                    # Try to find recipient user by their Sui address
                    try:
                        recipient_account = Account.objects.get(sui_address=recipient_address)
                        recipient_user = recipient_account.user
                    except Account.DoesNotExist:
                        recipient_user = None
                else:
                    return CreateSendTransaction(
                        send_transaction=None,
                        success=False,
                        errors=["Recipient identification required (user ID or phone number)"]
                    )

                # Determine sender type and business details
                sender_business = None
                sender_type = 'user'  # default to personal
                sender_display_name = f"{user.first_name} {user.last_name}".strip()
                # Fallback to username if no first/last name
                if not sender_display_name:
                    sender_display_name = user.username or f"User {user.id}"
                sender_phone = f"{user.phone_country}{user.phone_number}" if user.phone_country and user.phone_number else ""
                
                if active_account.account_type == 'business' and active_account.business:
                    sender_business = active_account.business
                    sender_type = 'business'
                    sender_display_name = active_account.business.name

                # Determine recipient type and business details
                recipient_business = None
                recipient_type = 'user'  # default to personal
                recipient_display_name = "External Address"
                recipient_phone = ""
                
                if recipient_user:
                    recipient_display_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip()
                    # Fallback to username if no first/last name
                    if not recipient_display_name:
                        recipient_display_name = recipient_user.username or f"User {recipient_user.id}"
                    recipient_phone = f"{recipient_user.phone_country}{recipient_user.phone_number}" if recipient_user.phone_country and recipient_user.phone_number else ""
                    # Check if recipient has business account for this address
                    if recipient_account.account_type == 'business' and recipient_account.business:
                        recipient_business = recipient_account.business
                        recipient_type = 'business'
                        recipient_display_name = recipient_account.business.name
                else:
                    # For external wallets, use the provided display name and phone if available
                    if hasattr(input, 'recipient_display_name') and input.recipient_display_name:
                        recipient_display_name = input.recipient_display_name
                    if hasattr(input, 'recipient_phone') and input.recipient_phone:
                        recipient_phone = input.recipient_phone
                    # For non-Confío users, ensure we store the phone number
                    if not recipient_phone and hasattr(input, 'recipient_phone') and input.recipient_phone:
                        # Clean and normalize phone number - remove all non-digits
                        recipient_phone = ''.join(filter(str.isdigit, input.recipient_phone))

                # Convert amount to Decimal for database storage
                amount_decimal = Decimal(str(input.amount))
                
                # Calculate invitation expiry if this is an invitation
                from datetime import timedelta
                invitation_expires_at = None
                if recipient_user is None and bool(recipient_phone):
                    invitation_expires_at = timezone.now() + timedelta(days=7)
                
                # Create the send transaction (but don't save yet)
                send_transaction = SendTransaction(
                    # Legacy user fields (kept for compatibility)
                    sender_user=user,
                    recipient_user=recipient_user,
                    
                    # NEW: Business fields based on account type
                    sender_business=sender_business,
                    recipient_business=recipient_business,
                    sender_type=sender_type,
                    recipient_type=recipient_type,
                    sender_display_name=sender_display_name,
                    recipient_display_name=recipient_display_name,
                    sender_phone=sender_phone,
                    recipient_phone=recipient_phone,
                    
                    # Transaction details
                    sender_address=sender_address,
                    recipient_address=recipient_address,  # Use the determined address
                    amount=amount_decimal,
                    token_type=input.token_type,
                    memo=input.memo or '',
                    status='PENDING',
                    idempotency_key=input.idempotency_key,
                    is_invitation=(recipient_user is None and bool(recipient_phone)),  # Only invitations for phone-based sends
                    invitation_expires_at=invitation_expires_at
                )
                
                # Import time and uuid at the beginning
                import time
                import uuid
                
                # Generate unique components for transaction hash
                microsecond_timestamp = int(time.time() * 1000000)
                unique_id = str(uuid.uuid4())[:8]
                
                # All non-blocked transactions proceed immediately
                send_transaction.status = 'CONFIRMED'
                send_transaction.transaction_hash = f"test_send_tx_{microsecond_timestamp}_{unique_id}"
                
                # Save the transaction
                send_transaction.save()

                # Create notifications
                from notifications.utils import create_notification
                from notifications.models import NotificationType
                
                # Notification for sender
                create_notification(
                    user=user,
                    account=sender_account,
                    business=sender_business,
                    notification_type=NotificationType.SEND_SENT,
                    title="Envío completado",
                    message=f"Enviaste {str(amount_decimal)} {input.token_type} a {recipient_display_name}",
                    data={
                        'amount': str(amount_decimal),
                        'token_type': input.token_type,
                        'transaction_id': str(send_transaction.id),
                        'recipient_name': recipient_display_name,
                        'recipient_phone': recipient_phone,
                    },
                    related_object_type='SendTransaction',
                    related_object_id=str(send_transaction.id),
                    action_url=f'confio://transaction/{send_transaction.id}'
                )
                
                # Notification for recipient (if they exist)
                if recipient_user:
                    create_notification(
                        user=recipient_user,
                        account=recipient_account,
                        business=recipient_business,
                        notification_type=NotificationType.SEND_RECEIVED,
                        title="Pago recibido",
                        message=f"Recibiste {str(amount_decimal)} {input.token_type} de {sender_display_name}",
                        data={
                            'amount': str(amount_decimal),
                            'token_type': input.token_type,
                            'transaction_id': str(send_transaction.id),
                            'sender_name': sender_display_name,
                            'sender_phone': sender_phone,
                        },
                        related_object_type='SendTransaction',
                        related_object_id=str(send_transaction.id),
                        action_url=f'confio://transaction/{send_transaction.id}'
                    )
                elif recipient_phone:
                    # This is an invitation - create invitation notification for sender
                    create_notification(
                        user=user,
                        account=sender_account,
                        business=sender_business,
                        notification_type=NotificationType.SEND_INVITATION_SENT,
                        title="Invitación enviada",
                        message=f"Enviaste {str(amount_decimal)} {input.token_type} a {recipient_phone}. Tienen 7 días para reclamar.",
                        data={
                            'amount': str(amount_decimal),
                            'token_type': input.token_type,
                            'transaction_id': str(send_transaction.id),
                            'recipient_phone': recipient_phone,
                            'expires_at': invitation_expires_at.isoformat() if invitation_expires_at else None,
                        },
                        related_object_type='SendTransaction',
                        related_object_id=str(send_transaction.id),
                        action_url=f'confio://transaction/{send_transaction.id}'
                    )

                return CreateSendTransaction(
                    send_transaction=send_transaction,
                    success=True,
                    errors=None
                )

        except ValidationError as e:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )

class Query(graphene.ObjectType):
    """GraphQL queries for send transactions"""
    send_transactions = graphene.List(SendTransactionType)
    send_transaction = graphene.Field(SendTransactionType, id=graphene.ID(required=True))
    send_transactions_with_friend = graphene.List(
        SendTransactionType,
        friend_user_id=graphene.ID(required=False),
        friend_phone=graphene.String(required=False),
        limit=graphene.Int()
    )
    # TEMP: Simple test resolver that always returns data
    all_send_transactions = graphene.List(SendTransactionType, limit=graphene.Int())

    def resolve_send_transactions(self, info):
        """Resolve all send transactions for the authenticated user and active account"""
        user = getattr(info.context, 'user', None)
        
        # TEMPORARY: For demo purposes, show some transactions
        if not (user and getattr(user, 'is_authenticated', False)):
            # Return some demo transactions for testing UI
            return SendTransaction.objects.all().order_by('-created_at')[:5]
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        # Get the account
        try:
            from users.models import Account
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT
                # This will find the business account regardless of who owns it
                account = Account.objects.get(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                )
            else:
                # For personal accounts
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
            
            # Filter by account's Sui address
            if account.sui_address:
                return SendTransaction.objects.filter(
                    models.Q(sender_address=account.sui_address) | 
                    models.Q(recipient_address=account.sui_address)
                ).order_by('-created_at')
        except Account.DoesNotExist:
            pass
        
        # Fallback to user-based filtering if account not found
        return SendTransaction.objects.filter(
            models.Q(sender_user=user) | models.Q(recipient_user=user)
        ).order_by('-created_at')

    def resolve_send_transaction(self, info, id):
        """Resolve a specific send transaction by ID"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        try:
            return SendTransaction.objects.get(
                models.Q(id=id) & (models.Q(sender_user=user) | models.Q(recipient_user=user))
            )
        except SendTransaction.DoesNotExist:
            return None


    def resolve_send_transactions_with_friend(self, info, friend_user_id=None, friend_phone=None, limit=None):
        """Resolve send transactions between current user's active account and a specific friend"""
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
        
        # Get the user's active account
        try:
            from users.models import Account
            if account_type == 'business' and business_id:
                # For business accounts, find by business_id from JWT
                # This will find the business account regardless of who owns it
                user_account = Account.objects.get(
                    account_type='business',
                    account_index=account_index,
                    business_id=business_id
                )
            else:
                # For personal accounts
                user_account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
            
            if not user_account.sui_address:
                return []
                
        except Account.DoesNotExist:
            return []
        
        # Build the query based on whether we have a user ID or phone number
        if friend_user_id and not friend_user_id.startswith('contact_'):
            # Regular Confío user - search by user ID and account addresses
            # Get all accounts for the friend user
            friend_accounts = Account.objects.filter(user_id=friend_user_id).values_list('sui_address', flat=True)
            friend_addresses = list(friend_accounts)
            
            if friend_addresses:
                queryset = SendTransaction.objects.filter(
                    (models.Q(sender_address=user_account.sui_address) & models.Q(recipient_address__in=friend_addresses)) |
                    (models.Q(sender_address__in=friend_addresses) & models.Q(recipient_address=user_account.sui_address))
                ).order_by('-created_at')
            else:
                # Friend has no accounts with addresses yet
                queryset = SendTransaction.objects.none()
        elif friend_phone:
            # Non-Confío friend - search by phone number from user's account
            queryset = SendTransaction.objects.filter(
                models.Q(sender_address=user_account.sui_address) & models.Q(recipient_phone=friend_phone)
            ).order_by('-created_at')
        else:
            # No valid identifier provided
            return []
        
        if limit:
            queryset = queryset[:limit]
            
        return queryset

    def resolve_all_send_transactions(self, info, limit=None):
        """TEMP: Simple resolver that always returns transactions for testing"""
        queryset = SendTransaction.objects.all().order_by('-created_at')
        if limit:
            queryset = queryset[:limit]
        return queryset

class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    create_send_transaction = CreateSendTransaction.Field() 