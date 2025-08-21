import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.db import models
from .models import P2PTrade, P2PMessage

User = get_user_model()

class TradeChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection"""
        self.trade_id = self.scope['url_route']['kwargs']['trade_id']
        self.room_group_name = f'trade_chat_{self.trade_id}'
        
        # For development: accept connection first, then check access
        await self.accept()
        
        # Check if user is authenticated and has access to this trade
        if not await self.check_user_access():
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Access denied or user not authenticated'
            }))
            await self.close()
            return
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Send chat history when user connects
        await self.send_chat_history()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', 'chat_message')
            
            if message_type == 'chat_message':
                await self.handle_chat_message(text_data_json)
            elif message_type == 'typing':
                await self.handle_typing_indicator(text_data_json)
            elif message_type == 'trade_status_update':
                await self.handle_trade_status_update(text_data_json)
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def handle_chat_message(self, data):
        """Handle chat message"""
        message_content = data.get('message', '').strip()
        
        if not message_content:
            return
            
        # Save message to database
        message = await self.save_message(message_content)
        
        if message:
            # Determine sender info based on new direct relationships
            sender_info = {}
            if message.sender_user:
                sender_info = {
                    'id': str(message.sender_user.id),
                    'username': message.sender_user.username,
                    'firstName': message.sender_user.first_name,
                    'lastName': message.sender_user.last_name,
                    'type': 'user'
                }
            elif message.sender_business:
                # For business, we need to get the user who sent the message
                # Since we know the user from scope, use that
                user = self.scope['user']
                sender_info = {
                    'id': str(user.id),
                    'username': user.username,
                    'firstName': user.first_name,
                    'lastName': user.last_name,
                    'type': 'business',
                    'businessName': message.sender_business.name,
                    'businessId': str(message.sender_business.id)
                }
            else:
                # Fallback to old sender field
                sender_info = {
                    'id': str(message.sender.id),
                    'username': message.sender.username,
                    'firstName': message.sender.first_name,
                    'lastName': message.sender.last_name,
                    'type': 'user'
                }
            
            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': {
                        'id': message.id,
                        'sender': sender_info,
                        'content': message.content,
                        'messageType': message.message_type,
                        'createdAt': message.created_at.isoformat(),
                        'isRead': message.is_read,
                    }
                }
            )

    async def handle_typing_indicator(self, data):
        """Handle typing indicator"""
        is_typing = data.get('isTyping', False)
        
        # Broadcast typing indicator to other users in the room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': str(self.scope['user'].id),
                'username': self.scope['user'].username,
                'is_typing': is_typing,
            }
        )

    async def handle_trade_status_update(self, data):
        """Handle trade status updates"""
        new_status = data.get('status')
        payment_reference = data.get('paymentReference', '')
        payment_notes = data.get('paymentNotes', '')
        
        # Update trade status in database
        trade_updated = await self.update_trade_status(new_status, payment_reference, payment_notes)
        
        if trade_updated:
            # Broadcast status update to room
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'trade_status_update',
                    'status': new_status,
                    'updated_by': str(self.scope['user'].id),
                    'payment_reference': payment_reference,
                    'payment_notes': payment_notes,
                }
            )

    # WebSocket message handlers
    async def chat_message(self, event):
        """Send chat message to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message']
        }))

    async def typing_indicator(self, event):
        """Send typing indicator to WebSocket"""
        # Don't send typing indicator back to the sender
        if event['user_id'] != str(self.scope['user'].id):
            await self.send(text_data=json.dumps({
                'type': 'typing_indicator',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_typing': event['is_typing'],
            }))

    async def trade_status_update(self, event):
        """Send trade status update to WebSocket"""
        message_data = {
            'type': 'trade_status_update',
            'status': event['status'],
            'updated_by': event['updated_by'],
            'payment_reference': event.get('payment_reference', ''),
            'payment_notes': event.get('payment_notes', ''),
        }
        # Include expires_at if provided by the broadcaster (aligns client timer immediately)
        if 'expires_at' in event and event['expires_at']:
            message_data['expires_at'] = event['expires_at']
        
        await self.send(text_data=json.dumps(message_data))

    # Database operations
    @database_sync_to_async
    def check_user_access(self):
        """Check if the current user has access to this trade"""
        try:
            user = self.scope['user']
            
            if not hasattr(user, 'is_authenticated') or not user.is_authenticated:
                return False
                
            trade = P2PTrade.objects.get(id=self.trade_id)
            
            # Check if user has access to this trade using new direct relationships
            has_access = (
                trade.buyer_user == user or 
                trade.seller_user == user or
                # Also check business relationships
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists()) or
                # Fallback to old system for backward compatibility
                trade.buyer == user or 
                trade.seller == user
            )
            
            return has_access
        except P2PTrade.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, content):
        """Save message to database"""
        try:
            user = self.scope['user']
            trade = P2PTrade.objects.get(id=self.trade_id)
            
            # Get account context from JWT middleware (secure)
            account_context = self.scope.get('account_context')
            if account_context:
                active_account_type = account_context['account_type']
                active_account_index = account_context['account_index']
                business_id = account_context['business_id']
            else:
                # Fallback to personal account if no context
                active_account_type = 'personal'
                active_account_index = 0
                business_id = None
            
            
            # Determine sender entity based on active account context
            message_kwargs = {
                'trade': trade,
                'content': content,
                'message_type': 'TEXT',
                # Keep old field for backward compatibility
                'sender': user,
            }
            
            # Determine which account is sending the message based on active account context
            if active_account_type == 'business':
                # User is sending as a business - find which business they're using
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    message_kwargs['sender_business'] = trade.buyer_business
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    message_kwargs['sender_business'] = trade.seller_business
                else:
                    # Fallback to personal if business not found
                    message_kwargs['sender_user'] = user
            else:
                # User is sending as personal account
                message_kwargs['sender_user'] = user
            
            message = P2PMessage.objects.create(**message_kwargs)
            return message
        except Exception as e:
            print(f"Error saving message: {e}")
            return None

    @database_sync_to_async
    def update_trade_status(self, status, payment_reference, payment_notes):
        """Update trade status in database"""
        try:
            user = self.scope['user']
            trade = P2PTrade.objects.get(id=self.trade_id)
            
            # Check if user has permission to update this trade
            if trade.buyer != user and trade.seller != user:
                return False
            
            trade.status = status
            if payment_reference:
                trade.payment_reference = payment_reference
            if payment_notes:
                trade.payment_notes = payment_notes
                
            trade.save()
            return True
        except Exception as e:
            print(f"Error updating trade status: {e}")
            return False

    @database_sync_to_async
    def get_chat_history(self):
        """Get chat history for this trade"""
        try:
            trade = P2PTrade.objects.get(id=self.trade_id)
            messages = P2PMessage.objects.filter(trade=trade).order_by('created_at')
            
            history = []
            for message in messages:
                # Determine sender info based on new direct relationships
                sender_info = {}
                if message.sender_user:
                    sender_info = {
                        'id': str(message.sender_user.id),
                        'username': message.sender_user.username,
                        'firstName': message.sender_user.first_name,
                        'lastName': message.sender_user.last_name,
                        'type': 'user'
                    }
                elif message.sender_business:
                    # For business messages, we still need to identify the user who sent it
                    # We'll use the account relationship to find the user
                    business_account = message.sender_business.accounts.first()
                    if business_account:
                        sender_info = {
                            'id': str(business_account.user.id),
                            'username': business_account.user.username,
                            'firstName': business_account.user.first_name,
                            'lastName': business_account.user.last_name,
                            'type': 'business',
                            'businessName': message.sender_business.name,
                            'businessId': str(message.sender_business.id)
                        }
                    else:
                        # Fallback if no account found
                        sender_info = {
                            'id': str(message.sender_business.id),
                            'username': message.sender_business.name,
                            'firstName': message.sender_business.name,
                            'lastName': '',
                            'type': 'business',
                            'businessName': message.sender_business.name,
                            'businessId': str(message.sender_business.id)
                        }
                else:
                    # Fallback to old sender field
                    sender_info = {
                        'id': str(message.sender.id),
                        'username': message.sender.username,
                        'firstName': message.sender.first_name,
                        'lastName': message.sender.last_name,
                        'type': 'user'
                    }
                
                history.append({
                    'id': message.id,
                    'sender': sender_info,
                    'content': message.content,
                    'messageType': message.message_type,
                    'createdAt': message.created_at.isoformat(),
                    'isRead': message.is_read,
                })
            
            return history
        except Exception as e:
            print(f"Error getting chat history: {e}")
            return []

    async def send_chat_history(self):
        """Send chat history to the connected user"""
        history = await self.get_chat_history()
        
        await self.send(text_data=json.dumps({
            'type': 'chat_history',
            'messages': history
        }))
