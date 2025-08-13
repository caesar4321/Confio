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

class PrepareTransactionInput(graphene.InputObjectType):
    """Input type for preparing a transaction (returns unsigned txBytes)"""
    # Recipient identification - use ONE of these
    recipient_user_id = graphene.ID(description="User ID of the recipient (for Confío users)")
    recipient_phone = graphene.String(description="Phone number of the recipient (for any user)")
    recipient_address = graphene.String(description="Algorand address for external wallet recipients (58 chars)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")
    idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate transactions")
    
    # Display info (for UI purposes only)
    recipient_display_name = graphene.String(description="Display name for the recipient (for UI)")

class ExecuteTransactionInput(graphene.InputObjectType):
    """Input type for executing a prepared transaction with signature"""
    tx_bytes = graphene.String(required=True, description="Base64 encoded transaction bytes from prepare step")
    zk_login_signature = graphene.String(required=True, description="zkLogin signature from client")
    sponsor_signature = graphene.String(required=True, description="Sponsor signature from prepare step")
    transaction_metadata = graphene.JSONString(description="Metadata from prepare step for record keeping")

class SendTransactionInput(graphene.InputObjectType):
    """Input type for creating a send transaction"""
    # Recipient identification - use ONE of these
    recipient_user_id = graphene.ID(description="User ID of the recipient (for Confío users)")
    recipient_phone = graphene.String(description="Phone number of the recipient (for any user)")
    recipient_address = graphene.String(description="Algorand address for external wallet recipients (58 chars)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")
    idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate sends")
    
    # zkLogin signature from client
    zk_login_signature = graphene.String(description="zkLogin signature from client for transaction authorization")
    
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
                
                if not active_account or not active_account.algorand_address:
                    return CreateSendTransaction(
                        send_transaction=None,
                        success=False,
                        errors=["Sender's Algorand address not found"]
                    )
                
                sender_address = active_account.algorand_address
                sender_account = active_account  # Store for later use in notifications

                # Find recipient and their Algorand address
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
                        if recipient_account and recipient_account.algorand_address:
                            recipient_address = recipient_account.algorand_address
                            print(f"CreateSendTransaction: Found recipient address by user ID: {recipient_address}")
                        else:
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Algorand address not found"]
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
                        if recipient_account and recipient_account.algorand_address:
                            recipient_address = recipient_account.algorand_address
                            print(f"CreateSendTransaction: Found recipient address by phone: {recipient_address}")
                        else:
                            # Confío user without address - shouldn't happen
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Algorand address not found"]
                            )
                    except User.DoesNotExist:
                        # Non-Confío user - create invitation transaction
                        print(f"CreateSendTransaction: Phone number not found in Confío - creating invitation")
                        # Generate a deterministic external address for this phone number
                        import hashlib
                        phone_hash = hashlib.sha256(cleaned_phone.encode()).hexdigest()
                        recipient_address = f"0x{phone_hash[:64]}"
                        # recipient_user remains None for invitation transactions
                
                # Priority 3: External wallet address
                elif hasattr(input, 'recipient_address') and input.recipient_address:
                    print(f"CreateSendTransaction: Using external wallet address: {input.recipient_address}")
                    recipient_address = input.recipient_address
                    validate_recipient(recipient_address)
                    # Try to find if this is actually a Confío user's address
                    try:
                        recipient_account = Account.objects.get(algorand_address=recipient_address)
                        recipient_user = recipient_account.user
                        print(f"CreateSendTransaction: Found Confío user for external address")
                    except Account.DoesNotExist:
                        # External wallet - not a Confío user
                        recipient_user = None
                        print(f"CreateSendTransaction: External wallet - not a Confío user")
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
                    elif hasattr(input, 'recipient_address') and input.recipient_address:
                        # For address-only sends, don't use "External Address" as display name
                        recipient_display_name = ""
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
                
                # Execute blockchain transaction using Algorand
                from blockchain.algorand_sponsor_service import algorand_sponsor_service
                import asyncio
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # For Algorand, we don't need zkLogin signature - using Web3Auth instead
                    # Create sponsored transfer
                    asset_id = None
                    if input.token_type.upper() == 'CONFIO':
                        asset_id = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 743890784)
                    elif input.token_type.upper() == 'USDC':
                        asset_id = getattr(settings, 'ALGORAND_USDC_ASSET_ID', 10458941)
                    # For ALGO transfers, asset_id remains None
                    
                    # Use proper atomic group transaction where user sends and sponsor pays fees
                    result = loop.run_until_complete(
                        algorand_sponsor_service.create_sponsored_transfer(
                            sender=sender_address,
                            recipient=recipient_address,
                            amount=amount_decimal,
                            asset_id=asset_id,
                            note=input.memo
                        )
                    )
                    
                    if result['success']:
                        # Return the atomic group data for client-side signing
                        # This follows the proper two-step process:
                        # 1. Server creates atomic group (this step)
                        # 2. Client signs user transaction and submits group (next step)
                        
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=True,
                            errors=[],
                            # Add atomic group data for frontend
                            atomic_group_data=result
                        )
                    else:
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=False,
                            errors=[result.get('error', 'Failed to create atomic group transaction')]
                        )
                    
                    if result['success']:
                        # Update transaction with blockchain result
                        send_transaction.status = 'CONFIRMED'
                        send_transaction.transaction_hash = result.get('tx_id', '')
                        
                        # Log the blockchain transaction
                        print(f"Blockchain send successful: {amount_decimal} {input.token_type} to {recipient_address[:16]}...")
                        print(f"Transaction ID: {result.get('tx_id')}")
                        print(f"Fees saved: {result.get('fees_saved', 0)} ALGO")
                        
                        if result.get('warning'):
                            print(f"WARNING: {result['warning']}")
                    else:
                        # Blockchain transaction failed
                        send_transaction.status = 'FAILED'
                        send_transaction.transaction_hash = ''
                        send_transaction.save()
                        
                        return CreateSendTransaction(
                            send_transaction=None,
                            success=False,
                            errors=[result.get('error', 'Blockchain transaction failed')]
                        )
                        
                finally:
                    loop.close()
                
                # Save the transaction with blockchain result
                send_transaction.save()

                # Create notifications
                from notifications.utils import create_notification
                from notifications.models import NotificationType
                
                # Notification for sender
                try:
                    print(f"CreateSendTransaction: Creating notification for sender {user.id}")
                    sender_notification = create_notification(
                    user=user,
                    account=sender_account,
                    business=sender_business,
                    notification_type=NotificationType.SEND_SENT,
                    title="Envío completado",
                    message=f"Enviaste {str(amount_decimal)} {input.token_type} a {recipient_display_name}",
                    data={
                        'transaction_type': 'send',
                        'amount': f'-{str(amount_decimal)}',  # Negative for sent
                        'token_type': input.token_type,
                        'currency': input.token_type,
                        'transaction_id': str(send_transaction.id),
                        'recipient_name': recipient_display_name,
                        'recipient_phone': recipient_phone,
                        'recipient_address': send_transaction.recipient_address,
                        'sender_name': sender_display_name,
                        'sender_phone': sender_phone,
                        'sender_address': send_transaction.sender_address,
                        'status': send_transaction.status.lower(),
                        'created_at': send_transaction.created_at.isoformat(),
                        'memo': send_transaction.memo,
                        'transaction_hash': send_transaction.transaction_hash,
                        'is_invited_friend': bool(recipient_phone and not recipient_user),
                        # For TransactionDetailScreen - amount needs sign
                        'type': 'send',
                        'to': recipient_display_name if recipient_display_name else '',
                        'toAddress': send_transaction.recipient_address,
                        'is_external_address': bool(not recipient_user and not recipient_phone and recipient_address),
                        'from': sender_display_name,
                        'fromAddress': send_transaction.sender_address,
                        'date': send_transaction.created_at.strftime('%Y-%m-%d'),
                        'time': send_transaction.created_at.strftime('%H:%M'),
                        'hash': send_transaction.transaction_hash or '',
                        'note': send_transaction.memo,
                        'avatar': recipient_display_name[0] if recipient_display_name else 'U',
                    },
                    related_object_type='SendTransaction',
                    related_object_id=str(send_transaction.id),
                    action_url=f'confio://transaction/{send_transaction.id}'
                    )
                    print(f"CreateSendTransaction: Sender notification created successfully with ID {sender_notification.id}")
                except Exception as e:
                    print(f"CreateSendTransaction ERROR: Failed to create sender notification: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Notification for recipient (if they exist)
                if recipient_user:
                    try:
                        print(f"CreateSendTransaction: Creating notification for recipient {recipient_user.id}")
                        recipient_notification = create_notification(
                        user=recipient_user,
                        account=recipient_account,
                        business=recipient_business,
                        notification_type=NotificationType.SEND_RECEIVED,
                        title="Envío recibido",
                        message=f"Recibiste {str(amount_decimal)} {input.token_type} de {sender_display_name}",
                        data={
                            'transaction_type': 'send',
                            'amount': f'+{str(amount_decimal)}',  # Positive for received
                            'token_type': input.token_type,
                            'currency': input.token_type,
                            'transaction_id': str(send_transaction.id),
                            'sender_name': sender_display_name,
                            'sender_phone': sender_phone,
                            'sender_address': send_transaction.sender_address,
                            'recipient_name': recipient_display_name,
                            'recipient_phone': recipient_phone,
                            'recipient_address': send_transaction.recipient_address,
                            'status': send_transaction.status.lower(),
                            'created_at': send_transaction.created_at.isoformat(),
                            'memo': send_transaction.memo,
                            'transaction_hash': send_transaction.transaction_hash,
                            # For TransactionDetailScreen
                            'type': 'received',
                            'from': sender_display_name,
                            'fromAddress': send_transaction.sender_address,
                            'to': recipient_display_name,
                            'toAddress': send_transaction.recipient_address,
                            'date': send_transaction.created_at.strftime('%Y-%m-%d'),
                            'time': send_transaction.created_at.strftime('%H:%M'),
                            'hash': send_transaction.transaction_hash or '',
                            'note': send_transaction.memo,
                            'avatar': sender_display_name[0] if sender_display_name else 'U',
                        },
                        related_object_type='SendTransaction',
                        related_object_id=str(send_transaction.id),
                        action_url=f'confio://transaction/{send_transaction.id}'
                        )
                        print(f"CreateSendTransaction: Recipient notification created successfully with ID {recipient_notification.id}")
                    except Exception as e:
                        print(f"CreateSendTransaction ERROR: Failed to create recipient notification: {e}")
                        import traceback
                        traceback.print_exc()
                elif recipient_phone:
                    # This is an invitation - create invitation notification for sender
                    create_notification(
                        user=user,
                        account=sender_account,
                        business=sender_business,
                        notification_type=NotificationType.SEND_INVITATION_SENT,
                        title="Invitación enviada",
                        message=f"Enviaste {str(amount_decimal)} {input.token_type} a {recipient_display_name if recipient_display_name else recipient_phone}. Tienen 7 días para reclamar.",
                        data={
                            'transaction_type': 'send',
                            'amount': f'-{str(amount_decimal)}',  # Negative for sent invitation
                            'token_type': input.token_type,
                            'currency': input.token_type,
                            'transaction_id': str(send_transaction.id),
                            'recipient_phone': recipient_phone,
                            'expires_at': invitation_expires_at.isoformat() if invitation_expires_at else None,
                            'recipient_address': send_transaction.recipient_address,
                            'sender_name': sender_display_name,
                            'sender_phone': sender_phone,
                            'sender_address': send_transaction.sender_address,
                            'status': send_transaction.status.lower(),
                            'created_at': send_transaction.created_at.isoformat(),
                            'memo': send_transaction.memo,
                            'transaction_hash': send_transaction.transaction_hash,
                            'is_invited_friend': True,
                            # For TransactionDetailScreen
                            'type': 'send',
                            'to': recipient_display_name if recipient_display_name else '',  # Include display name if provided
                            'toAddress': send_transaction.recipient_address,
                            'recipient_name': recipient_display_name,
                            'from': sender_display_name,
                            'fromAddress': send_transaction.sender_address,
                            'date': send_transaction.created_at.strftime('%Y-%m-%d'),
                            'time': send_transaction.created_at.strftime('%H:%M'),
                            'hash': send_transaction.transaction_hash or '',
                            'note': send_transaction.memo,
                            'avatar': 'U',  # Unknown user
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
            
            # Filter by account's Algorand address
            if account.algorand_address:
                return SendTransaction.objects.filter(
                    models.Q(sender_address=account.algorand_address) | 
                    models.Q(recipient_address=account.algorand_address)
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
            
            if not user_account.algorand_address:
                return []
                
        except Account.DoesNotExist:
            return []
        
        # Build the query based on whether we have a user ID or phone number
        if friend_user_id and not friend_user_id.startswith('contact_'):
            # Regular Confío user - search by user ID and account addresses
            # Get all accounts for the friend user
            friend_accounts = Account.objects.filter(user_id=friend_user_id).values_list('algorand_address', flat=True)
            friend_addresses = list(friend_accounts)
            
            if friend_addresses:
                queryset = SendTransaction.objects.filter(
                    (models.Q(sender_address=user_account.algorand_address) & models.Q(recipient_address__in=friend_addresses)) |
                    (models.Q(sender_address__in=friend_addresses) & models.Q(recipient_address=user_account.algorand_address))
                ).order_by('-created_at')
            else:
                # Friend has no accounts with addresses yet
                queryset = SendTransaction.objects.none()
        elif friend_phone:
            # Non-Confío friend - search by phone number from user's account
            queryset = SendTransaction.objects.filter(
                models.Q(sender_address=user_account.algorand_address) & models.Q(recipient_phone=friend_phone)
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

class PrepareTransaction(graphene.Mutation):
    """Prepare a transaction and return unsigned txBytes for client signing"""
    class Arguments:
        input = PrepareTransactionInput(required=True)

    # Outputs
    success = graphene.Boolean()
    tx_bytes = graphene.String(description="Base64 encoded transaction bytes to sign")
    sponsor_signature = graphene.String(description="Sponsor signature")
    transaction_metadata = graphene.JSONString(description="Metadata for execute step")
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PrepareTransaction(
                success=False,
                errors=["Authentication required"]
            )

        try:
            from decimal import Decimal
            from users.jwt_context import get_jwt_business_context_with_validation
            from blockchain.algorand_sponsor_service import algorand_sponsor_service
            import asyncio
            
            # Get account context from JWT
            jwt_context = get_jwt_business_context_with_validation(info, 'send_funds')
            if not jwt_context:
                return PrepareTransaction(
                    success=False,
                    errors=["Account context not found"]
                )
            
            # Get the active account
            from users.models import Account
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            
            if account_type == 'business' and jwt_context.get('business_id'):
                active_account = Account.objects.get(
                    account_type='business',
                    account_index=account_index,
                    business_id=jwt_context['business_id']
                )
            else:
                active_account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index
                )
            
            # Validate amount
            amount_decimal = Decimal(input.amount)
            if amount_decimal <= 0:
                return PrepareTransaction(
                    success=False,
                    errors=["Amount must be positive"]
                )
            
            # Determine recipient address
            recipient_address = None
            recipient_user = None
            
            if hasattr(input, 'recipient_user_id') and input.recipient_user_id:
                try:
                    recipient_user = User.objects.get(id=input.recipient_user_id)
                    recipient_account = recipient_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_account and recipient_account.algorand_address:
                        recipient_address = recipient_account.algorand_address
                    else:
                        return PrepareTransaction(
                            success=False,
                            errors=["Recipient's Algorand address not found"]
                        )
                except User.DoesNotExist:
                    return PrepareTransaction(
                        success=False,
                        errors=["Recipient user not found"]
                    )
            elif hasattr(input, 'recipient_phone') and input.recipient_phone:
                # For phone numbers, try to find the user
                cleaned_phone = ''.join(filter(str.isdigit, input.recipient_phone))
                try:
                    recipient_user = User.objects.get(phone_number=cleaned_phone)
                    recipient_account = recipient_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_account and recipient_account.algorand_address:
                        recipient_address = recipient_account.algorand_address
                except User.DoesNotExist:
                    # Non-Confío user - create invitation address
                    import hashlib
                    phone_hash = hashlib.sha256(cleaned_phone.encode()).hexdigest()
                    recipient_address = f"0x{phone_hash[:64]}"
            elif hasattr(input, 'recipient_address') and input.recipient_address:
                recipient_address = input.recipient_address
            else:
                return PrepareTransaction(
                    success=False,
                    errors=["Recipient identification required"]
                )
            
            # Prepare transaction using the blockchain service
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Prepare the transaction (but don't execute) - Algorand version
                asset_id = None
                if input.token_type.upper() == 'CONFIO':
                    asset_id = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 743890784)
                elif input.token_type.upper() == 'USDC':
                    asset_id = getattr(settings, 'ALGORAND_USDC_ASSET_ID', 10458941)
                
                result = loop.run_until_complete(
                    algorand_sponsor_service.create_sponsored_transfer(
                        sender=active_account.algorand_address,
                        recipient=recipient_address,
                        amount=amount_decimal,
                        asset_id=asset_id
                    )
                )
                
                if result.get('success'):
                    # Prioritize frontend's display name (contact name), fallback to user data
                    recipient_display_name = getattr(input, 'recipient_display_name', '')
                    
                    # Only fallback to user data if frontend didn't provide a name
                    if not recipient_display_name and recipient_user:
                        recipient_display_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip()
                        if not recipient_display_name:
                            recipient_display_name = recipient_user.username or f"User {recipient_user.id}"
                    
                    # Ensure we never have an empty string (database constraint)
                    if not recipient_display_name:
                        recipient_display_name = "External Address"
                    
                    # Transaction prepared successfully
                    transaction_metadata = {
                        'sender_address': active_account.algorand_address,
                        'recipient_address': recipient_address,
                        'amount': str(amount_decimal),
                        'token_type': input.token_type,
                        'recipient_display_name': recipient_display_name,
                        'timestamp': timezone.now().isoformat(),
                        'asset_id': asset_id
                    }
                    
                    return PrepareTransaction(
                        success=True,
                        tx_bytes=result['user_transaction'],
                        sponsor_signature=result['sponsor_transaction'],
                        transaction_metadata=transaction_metadata,
                        errors=None
                    )
                else:
                    return PrepareTransaction(
                        success=False,
                        errors=[result.get('error', 'Failed to prepare transaction')]
                    )
                    
            finally:
                loop.close()
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return PrepareTransaction(
                success=False,
                errors=[str(e)]
            )


class ExecuteTransaction(graphene.Mutation):
    """Execute a prepared transaction with zkLogin signature"""
    class Arguments:
        input = ExecuteTransactionInput(required=True)

    send_transaction = graphene.Field(SendTransactionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ExecuteTransaction(
                send_transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            from users.jwt_context import get_jwt_business_context_with_validation
            from blockchain.algorand_sponsor_service import algorand_sponsor_service
            import asyncio
            import json
            
            # Get account context from JWT
            jwt_context = get_jwt_business_context_with_validation(info, 'send_funds')
            if not jwt_context:
                return ExecuteTransaction(
                    send_transaction=None,
                    success=False,
                    errors=["Account context not found"]
                )
            
            # Parse transaction metadata
            if input.transaction_metadata:
                if isinstance(input.transaction_metadata, dict):
                    # Already a dict, use as-is
                    metadata = input.transaction_metadata
                else:
                    # String, parse it
                    metadata = json.loads(input.transaction_metadata)
            else:
                metadata = {}
            
            # Create transaction record
            from decimal import Decimal
            amount_decimal = Decimal(metadata.get('amount', '0'))
            
            # Determine account details
            from users.models import Account
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            sender_business = None
            
            if account_type == 'business' and jwt_context.get('business_id'):
                from users.models import Business
                sender_business = Business.objects.get(id=jwt_context['business_id'])
            
            # Create the transaction record
            send_transaction = SendTransaction.objects.create(
                sender_user=user,
                sender_business=sender_business,
                sender_type='business' if sender_business else 'user',
                sender_display_name=sender_business.name if sender_business else f"{user.first_name} {user.last_name}".strip(),
                sender_phone=f"{user.phone_country}{user.phone_number}" if user.phone_country and user.phone_number else "",
                sender_address=metadata.get('sender_address', ''),
                recipient_address=metadata.get('recipient_address', ''),
                recipient_display_name=metadata.get('recipient_display_name', 'External Address'),
                amount=amount_decimal,
                token_type=metadata.get('token_type', 'CUSD'),
                status='PENDING'
            )
            
            # Execute the transaction with signatures
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Get the active account for zkProof retrieval
                active_account = None
                if account_type == 'business' and jwt_context.get('business_id'):
                    from users.models import Account
                    active_account = Account.objects.get(
                        account_type='business',
                        account_index=account_index,
                        business_id=jwt_context['business_id']
                    )
                else:
                    from users.models import Account
                    active_account = Account.objects.get(
                        user=user,
                        account_type=account_type,
                        account_index=account_index
                    )
                
                result = loop.run_until_complete(
                    algorand_sponsor_service.submit_sponsored_group(
                        signed_user_txn=input.zk_login_signature,  # This is now the user's signed transaction
                        signed_sponsor_txn=input.sponsor_signature
                    )
                )
                
                if result.get('success'):
                    # Update transaction with success
                    send_transaction.status = 'CONFIRMED'
                    send_transaction.transaction_hash = result.get('tx_id', '')
                    send_transaction.save()
                    
                    # Create notifications
                    from notifications.utils import create_notification
                    from notifications.models import NotificationType
                    
                    create_notification(
                        user=user,
                        account=None,  # TODO: Get account
                        business=sender_business,
                        notification_type=NotificationType.SEND_SENT,
                        title="Envío completado",
                        message=f"Enviaste {str(amount_decimal)} {metadata.get('token_type', 'CUSD')}",
                        data={
                            'transaction_type': 'send',
                            'amount': f'-{str(amount_decimal)}',
                            'token_type': metadata.get('token_type', 'CUSD'),
                            'transaction_id': str(send_transaction.id),
                            'transaction_hash': send_transaction.transaction_hash
                        }
                    )
                    
                    return ExecuteTransaction(
                        send_transaction=send_transaction,
                        success=True,
                        errors=None
                    )
                else:
                    # Update transaction with failure
                    send_transaction.status = 'FAILED'
                    send_transaction.save()
                    
                    return ExecuteTransaction(
                        send_transaction=None,
                        success=False,
                        errors=[result.get('error', 'Transaction execution failed')]
                    )
                    
            finally:
                loop.close()
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return ExecuteTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )


class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    # Note: Send transactions now handled by Algorand mutations in blockchain/schema.py
    # These mutations are kept for backwards compatibility but should not be used
    # create_send_transaction = CreateSendTransaction.Field()  # Deprecated - use algorandSponsoredSend
    # prepare_transaction = PrepareTransaction.Field()  # Deprecated - Sui/zkLogin specific
    # execute_transaction = ExecuteTransaction.Field()  # Deprecated - Sui/zkLogin specific 