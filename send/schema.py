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
    recipient_address = graphene.String(description="Aptos address for external wallet recipients (0x...)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    
    # Display info (for UI purposes only)
    recipient_display_name = graphene.String(description="Display name for the recipient (for UI)")

class PrepareSponsoredTransferInput(graphene.InputObjectType):
    """Input type for preparing a V2 sponsored transaction"""
    # Recipient identification - use ONE of these
    recipient_user_id = graphene.ID(description="User ID of the recipient (for Confío users)")
    recipient_phone = graphene.String(description="Phone number of the recipient (for any user)")
    recipient_address = graphene.String(description="Aptos address for external wallet recipients (0x...)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'CUSD', 'CONFIO')")
    
    # Display info (for UI purposes only)
    recipient_display_name = graphene.String(description="Display name for the recipient (for UI)")

class SubmitSponsoredTransferInput(graphene.InputObjectType):
    """Input type for submitting a V2 sponsored transaction with signature"""
    transaction_id = graphene.String(required=True, description="Transaction ID from prepare step")
    sender_authenticator = graphene.String(required=True, description="Base64 encoded sender authenticator")
    sender_authenticator_bcs = graphene.String(description="A/B Test: Base64 encoded BCS authenticator")
    # EXPERIMENTAL: Add keyless data for bridge-side signing
    jwt = graphene.String(description="JWT token for keyless account recreation")
    ephemeral_key_pair = graphene.JSONString(description="Ephemeral key pair data for keyless account recreation")

class ExecuteTransactionInput(graphene.InputObjectType):
    """Input type for executing a prepared transaction with signature"""
    tx_bytes = graphene.String(required=True, description="Base64 encoded transaction bytes from prepare step")
    aptos_keyless_signature = graphene.String(required=True, description="Aptos keyless account signature from client")
    sponsor_signature = graphene.String(required=True, description="Sponsor signature from prepare step")
    transaction_metadata = graphene.JSONString(description="Metadata from prepare step for record keeping")

class SendTransactionInput(graphene.InputObjectType):
    """Input type for creating a send transaction"""
    # Recipient identification - use ONE of these
    recipient_user_id = graphene.ID(description="User ID of the recipient (for Confío users)")
    recipient_phone = graphene.String(description="Phone number of the recipient (for any user)")
    recipient_address = graphene.String(description="Aptos address for external wallet recipients (0x...)")
    
    # Transaction details
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")
    idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate sends")
    
    # Aptos keyless signature from client
    aptos_keyless_signature = graphene.String(description="Aptos keyless account signature from client for transaction authorization")
    
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
                
                if not active_account or not active_account.aptos_address:
                    return CreateSendTransaction(
                        send_transaction=None,
                        success=False,
                        errors=["Sender's Aptos address not found"]
                    )
                
                sender_address = active_account.aptos_address
                sender_account = active_account  # Store for later use in notifications

                # Find recipient and their Aptos address
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
                        if recipient_account and recipient_account.aptos_address:
                            recipient_address = recipient_account.aptos_address
                            print(f"CreateSendTransaction: Found recipient address by user ID: {recipient_address}")
                        else:
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Aptos address not found"]
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
                        if recipient_account and recipient_account.aptos_address:
                            recipient_address = recipient_account.aptos_address
                            print(f"CreateSendTransaction: Found recipient address by phone: {recipient_address}")
                        else:
                            # Confío user without address - shouldn't happen
                            return CreateSendTransaction(
                                send_transaction=None,
                                success=False,
                                errors=["Recipient's Aptos address not found"]
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
                        recipient_account = Account.objects.get(aptos_address=recipient_address)
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
                
                # Execute blockchain transaction using Aptos
                from blockchain.aptos_transaction_manager import AptosTransactionManager
                import asyncio
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Get Aptos keyless signature from client input
                    user_signature = getattr(input, 'aptos_keyless_signature', None)
                    if not user_signature:
                        # For backward compatibility, log warning but continue
                        print("WARNING: No Aptos keyless signature provided by client - transaction will use mock mode")
                    
                    # Execute the sponsored transaction using Aptos
                    result = loop.run_until_complete(
                        AptosTransactionManager.send_tokens(
                            sender_account,
                            recipient_address,
                            amount_decimal,
                            input.token_type.upper(),
                            user_signature
                        )
                    )
                    
                    if result['success']:
                        # Update transaction with blockchain result
                        send_transaction.status = 'CONFIRMED'
                        send_transaction.transaction_hash = result.get('digest', '')
                        
                        # Log the blockchain transaction
                        print(f"Aptos send successful: {amount_decimal} {input.token_type} to {recipient_address[:16]}...")
                        print(f"Transaction digest: {result.get('digest')}")
                        print(f"Gas saved: {result.get('gas_saved', 0)} APT")
                        
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
                create_notification(
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
            
            # Filter by account's Aptos address
            if account.aptos_address:
                return SendTransaction.objects.filter(
                    models.Q(sender_address=account.aptos_address) | 
                    models.Q(recipient_address=account.aptos_address)
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
            
            if not user_account.aptos_address:
                return []
                
        except Account.DoesNotExist:
            return []
        
        # Build the query based on whether we have a user ID or phone number
        if friend_user_id and not friend_user_id.startswith('contact_'):
            # Regular Confío user - search by user ID and account addresses
            # Get all accounts for the friend user
            friend_accounts = Account.objects.filter(user_id=friend_user_id).values_list('aptos_address', flat=True)
            friend_addresses = list(friend_accounts)
            
            if friend_addresses:
                queryset = SendTransaction.objects.filter(
                    (models.Q(sender_address=user_account.aptos_address) & models.Q(recipient_address__in=friend_addresses)) |
                    (models.Q(sender_address__in=friend_addresses) & models.Q(recipient_address=user_account.aptos_address))
                ).order_by('-created_at')
            else:
                # Friend has no accounts with addresses yet
                queryset = SendTransaction.objects.none()
        elif friend_phone:
            # Non-Confío friend - search by phone number from user's account
            queryset = SendTransaction.objects.filter(
                models.Q(sender_address=user_account.aptos_address) & models.Q(recipient_phone=friend_phone)
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
            # Legacy import removed - using Aptos transaction manager
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
                    if recipient_account and recipient_account.aptos_address:
                        recipient_address = recipient_account.aptos_address
                    else:
                        return PrepareTransaction(
                            success=False,
                            errors=["Recipient's Aptos address not found"]
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
                    if recipient_account and recipient_account.aptos_address:
                        recipient_address = recipient_account.aptos_address
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
            
            # Prepare transaction using the Aptos blockchain service
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Prepare the transaction (but don't execute)
                from blockchain.aptos_transaction_manager import AptosTransactionManager
                
                result = loop.run_until_complete(
                    AptosTransactionManager.prepare_send_transaction(
                        account=active_account,
                        recipient=recipient_address,
                        amount=amount_decimal,
                        token_type=input.token_type.upper()
                    )
                )
                
                if result.get('success') and result.get('requiresUserSignature'):
                    # Transaction prepared successfully
                    transaction_metadata = {
                        'sender_address': active_account.aptos_address,
                        'recipient_address': recipient_address,
                        'amount': str(amount_decimal),
                        'token_type': input.token_type,
                        'recipient_display_name': getattr(input, 'recipient_display_name', ''),
                        'timestamp': timezone.now().isoformat()
                    }
                    
                    return PrepareTransaction(
                        success=True,
                        tx_bytes=result['txBytes'],
                        sponsor_signature=result['sponsorSignature'],
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
    """Execute a prepared transaction with keyless signature"""
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
            from blockchain.aptos_transaction_manager import AptosTransactionManager
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
                    AptosTransactionManager.execute_transaction_with_signatures(
                        tx_bytes=input.tx_bytes,
                        sponsor_signature=input.sponsor_signature,
                        user_signature=input.aptos_keyless_signature,
                        account_id=active_account.id if active_account else None
                    )
                )
                
                if result.get('success'):
                    # Update transaction with success
                    send_transaction.status = 'CONFIRMED'
                    send_transaction.transaction_hash = result.get('digest', '')
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


class PrepareSponsoredTransfer(graphene.Mutation):
    """V2 Mutation to prepare a sponsored transaction through Django bridge"""
    class Arguments:
        input = PrepareSponsoredTransferInput(required=True)
    
    # Outputs
    success = graphene.Boolean()
    transaction_id = graphene.String(description="Transaction ID for tracking")
    raw_transaction = graphene.String(description="Base64 encoded raw transaction to sign")
    raw_bcs = graphene.String(description="A/B Test: Base64 encoded raw BCS bytes as alternative to signing message")
    fee_payer_address = graphene.String(description="Address of the fee payer (sponsor)")
    errors = graphene.List(graphene.String)
    
    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return PrepareSponsoredTransfer(
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            from decimal import Decimal
            from users.jwt_context import get_jwt_business_context_with_validation
            from blockchain.aptos_sponsor_service import AptosSponsorService
            import asyncio
            
            # Get account context from JWT
            jwt_context = get_jwt_business_context_with_validation(info, 'send_funds')
            if not jwt_context:
                return PrepareSponsoredTransfer(
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
            
            if not active_account.aptos_address:
                return PrepareSponsoredTransfer(
                    success=False,
                    errors=["Sender's Aptos address not found"]
                )
            
            # Validate amount
            amount_decimal = Decimal(input.amount)
            if amount_decimal <= 0:
                return PrepareSponsoredTransfer(
                    success=False,
                    errors=["Amount must be positive"]
                )
            
            # Determine recipient address
            recipient_address = None
            
            if hasattr(input, 'recipient_user_id') and input.recipient_user_id:
                try:
                    recipient_user = User.objects.get(id=input.recipient_user_id)
                    recipient_account = recipient_user.accounts.filter(
                        account_type='personal',
                        account_index=0
                    ).first()
                    if recipient_account and recipient_account.aptos_address:
                        recipient_address = recipient_account.aptos_address
                    else:
                        return PrepareSponsoredTransfer(
                            success=False,
                            errors=["Recipient's Aptos address not found"]
                        )
                except User.DoesNotExist:
                    return PrepareSponsoredTransfer(
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
                    if recipient_account and recipient_account.aptos_address:
                        recipient_address = recipient_account.aptos_address
                except User.DoesNotExist:
                    # Non-Confío user - create invitation address
                    import hashlib
                    phone_hash = hashlib.sha256(cleaned_phone.encode()).hexdigest()
                    recipient_address = f"0x{phone_hash[:64]}"
            elif hasattr(input, 'recipient_address') and input.recipient_address:
                recipient_address = input.recipient_address
            else:
                return PrepareSponsoredTransfer(
                    success=False,
                    errors=["Recipient identification required"]
                )
            
            # Call the V2 prepare method based on token type
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                token_type = input.token_type.upper()
                
                if token_type == 'CONFIO':
                    result = loop.run_until_complete(
                        AptosSponsorService.prepare_sponsored_confio_transfer(
                            sender_address=active_account.aptos_address,
                            recipient_address=recipient_address,
                            amount=amount_decimal
                        )
                    )
                elif token_type == 'CUSD':
                    result = loop.run_until_complete(
                        AptosSponsorService.prepare_sponsored_cusd_transfer(
                            sender_address=active_account.aptos_address,
                            recipient_address=recipient_address,
                            amount=amount_decimal
                        )
                    )
                else:
                    return PrepareSponsoredTransfer(
                        success=False,
                        errors=[f"Unsupported token type: {token_type}"]
                    )
                
                if result.get('success'):
                    return PrepareSponsoredTransfer(
                        success=True,
                        transaction_id=result['transactionId'],
                        raw_transaction=result['rawTransaction'],
                        raw_bcs=result.get('rawBcs'),  # A/B Test: Include raw BCS if available
                        fee_payer_address=result['feePayerAddress'],
                        errors=None
                    )
                else:
                    return PrepareSponsoredTransfer(
                        success=False,
                        errors=[result.get('error', 'Failed to prepare transaction')]
                    )
                    
            finally:
                loop.close()
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return PrepareSponsoredTransfer(
                success=False,
                errors=[str(e)]
            )

class SubmitSponsoredTransfer(graphene.Mutation):
    """V2 Mutation to submit a sponsored transaction with sender authenticator"""
    class Arguments:
        input = SubmitSponsoredTransferInput(required=True)
    
    # Outputs
    success = graphene.Boolean()
    send_transaction = graphene.Field(SendTransactionType)
    transaction_hash = graphene.String(description="Transaction hash on blockchain")
    digest = graphene.String(description="Transaction digest (alias for hash)")
    gas_used = graphene.Int(description="Gas used in the transaction")
    errors = graphene.List(graphene.String)
    
    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SubmitSponsoredTransfer(
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            from blockchain.aptos_sponsor_service import AptosSponsorService
            from users.jwt_context import get_jwt_business_context_with_validation
            import asyncio
            
            # Get account context from JWT
            jwt_context = get_jwt_business_context_with_validation(info, 'send_funds')
            if not jwt_context:
                return SubmitSponsoredTransfer(
                    success=False,
                    errors=["Account context not found"]
                )
            
            # Submit the V2 transaction
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # EXPERIMENTAL: Pass keyless data if provided
                kwargs = {
                    'transaction_id': input.transaction_id,
                    'sender_authenticator': input.sender_authenticator
                }
                
                # A/B Test: Add BCS authenticator if provided
                if hasattr(input, 'sender_authenticator_bcs') and input.sender_authenticator_bcs:
                    kwargs['sender_authenticator_bcs'] = input.sender_authenticator_bcs
                
                # Add optional keyless data for bridge-side signing
                if hasattr(input, 'jwt') and input.jwt:
                    kwargs['jwt'] = input.jwt
                if hasattr(input, 'ephemeral_key_pair') and input.ephemeral_key_pair:
                    kwargs['ephemeral_key_pair'] = input.ephemeral_key_pair
                
                result = loop.run_until_complete(
                    AptosSponsorService.submit_sponsored_confio_transfer_v2(**kwargs)
                )
                
                if result.get('success'):
                    # Create a simplified transaction record for success response
                    # In a real implementation, you'd create a proper SendTransaction record
                    from datetime import datetime
                    from decimal import Decimal
                    
                    # Create a minimal send transaction record for the response
                    # Note: In production, retrieve transaction details from cache/storage
                    send_transaction_data = {
                        'id': input.transaction_id,
                        'status': 'CONFIRMED',
                        'transaction_hash': result.get('transactionHash', ''),
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    
                    # Create a mock transaction object for the response
                    # In production, this should be retrieved from the prepare phase cache
                    class MockTransaction:
                        def __init__(self, data):
                            for key, value in data.items():
                                setattr(self, key, value)
                    
                    mock_transaction = MockTransaction(send_transaction_data)
                    
                    return SubmitSponsoredTransfer(
                        success=True,
                        send_transaction=mock_transaction,
                        transaction_hash=result.get('transactionHash'),
                        digest=result.get('transactionHash'),  # alias for compatibility
                        gas_used=result.get('gasUsed', 0),
                        errors=None
                    )
                else:
                    return SubmitSponsoredTransfer(
                        success=False,
                        errors=[result.get('error', 'Failed to submit transaction')]
                    )
                    
            finally:
                loop.close()
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return SubmitSponsoredTransfer(
                success=False,
                errors=[str(e)]
            )

class TestRegularTransferInput(graphene.InputObjectType):
    """Input for testing regular (non-sponsored) keyless transaction"""
    recipient_address = graphene.String(required=True, description="Recipient Aptos address")
    amount = graphene.String(required=True, description="Amount to send in CONFIO units")
    raw_transaction = graphene.String(required=True, description="Base64 encoded raw transaction built by client")
    sender_authenticator = graphene.String(required=True, description="Base64 encoded sender authenticator")

class TestRegularTransfer(graphene.Mutation):
    """Test mutation for regular (non-sponsored) keyless transactions"""
    class Arguments:
        input = TestRegularTransferInput(required=True)
    
    # Outputs
    success = graphene.Boolean()
    transaction_hash = graphene.String()
    error = graphene.String()
    debug_info = graphene.String()
    
    @classmethod
    @graphql_require_aml()
    @graphql_require_kyc('send_money')
    def mutate(cls, root, info, input):
        """
        Test regular keyless transaction submission
        This bypasses sponsored flow to test basic keyless account functionality
        """
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return TestRegularTransfer(
                success=False,
                error="Authentication required"
            )
        
        try:
            from blockchain.aptos_sponsor_service import AptosSponsorService
            from users.jwt_context import get_jwt_business_context_with_validation
            import asyncio
            import json
            
            # For testing, we'll extract sender address from the transaction itself
            # since the keyless account is managed client-side
            import base64
            
            # Log debug info
            debug_info = {
                "test_mode": True,
                "recipient_address": input.recipient_address,
                "amount": input.amount,
                "raw_transaction_length": len(input.raw_transaction) if input.raw_transaction else 0,
                "authenticator_length": len(input.sender_authenticator) if input.sender_authenticator else 0
            }
            
            # Note: For testing regular keyless transactions, we don't need the Django account
            # The sender address is embedded in the transaction itself
            
            print(f"TestRegularTransfer debug: {json.dumps(debug_info, indent=2)}")
            
            # Submit directly to Aptos (non-sponsored)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Call a new test method in AptosSponsorService
                # For testing, we don't need sender_address as it's in the transaction
                result = loop.run_until_complete(
                    AptosSponsorService.test_regular_keyless_transfer(
                        raw_transaction=input.raw_transaction,
                        sender_authenticator=input.sender_authenticator,
                        sender_address="test_keyless_account"  # Just for logging
                    )
                )
                
                if result.get('success'):
                    return TestRegularTransfer(
                        success=True,
                        transaction_hash=result.get('transactionHash'),
                        debug_info=json.dumps(debug_info)
                    )
                else:
                    return TestRegularTransfer(
                        success=False,
                        error=result.get('error', 'Failed to submit test transaction'),
                        debug_info=json.dumps({**debug_info, "error_details": result})
                    )
                    
            finally:
                loop.close()
                
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"TestRegularTransfer error: {error_trace}")
            return TestRegularTransfer(
                success=False,
                error=str(e),
                debug_info=json.dumps({"exception": str(e), "type": type(e).__name__})
            )

class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    create_send_transaction = CreateSendTransaction.Field()
    prepare_transaction = PrepareTransaction.Field()
    execute_transaction = ExecuteTransaction.Field()
    # V2 sponsored transaction mutations
    prepare_sponsored_transfer = PrepareSponsoredTransfer.Field()
    submit_sponsored_transfer = SubmitSponsoredTransfer.Field()
    # Test mutation for regular keyless transactions
    test_regular_transfer = TestRegularTransfer.Field() 