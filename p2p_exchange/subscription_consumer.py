import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from graphql_jwt.middleware import JSONWebTokenMiddleware
from graphql_jwt.shortcuts import get_user_by_token
from .models import P2PTrade, P2PMessage
from config.schema import schema
import graphene

User = get_user_model()

class GraphQLSubscriptionConsumer(AsyncWebsocketConsumer):
    """GraphQL Subscription WebSocket Consumer"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscriptions = {}  # Track active subscriptions
        self.user = None
        
    async def connect(self):
        """Handle WebSocket connection with GraphQL subscription protocol"""
        await self.accept(subprotocol="graphql-ws")
        
        # Send connection_ack after successful connection
        await self.send(text_data=json.dumps({
            'type': 'connection_ack'
        }))
        
    async def disconnect(self, close_code):
        """Handle disconnection"""
        # Clean up subscriptions
        for sub_id in list(self.subscriptions.keys()):
            await self.unsubscribe(sub_id)
            
    async def receive(self, text_data):
        """Handle incoming GraphQL subscription messages"""
        try:
            message = json.loads(text_data)
            message_type = message.get('type')
            
            if message_type == 'connection_init':
                await self.handle_connection_init(message)
            elif message_type == 'start':
                await self.handle_start(message)
            elif message_type == 'stop':
                await self.handle_stop(message)
            elif message_type == 'connection_terminate':
                await self.close()
                
        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format')
        except Exception as e:
            await self.send_error(f'Error processing message: {str(e)}')
            
    async def handle_connection_init(self, message):
        """Handle GraphQL connection initialization with authentication"""
        payload = message.get('payload', {})
        
        # Extract JWT token from payload
        token = payload.get('Authorization', '').replace('Bearer ', '')
        if not token:
            # Try alternative token locations
            token = payload.get('authToken') or payload.get('token')
            
        if token:
            # Authenticate user with JWT token
            try:
                self.user = await self.authenticate_token(token)
                if not self.user or not self.user.is_authenticated:
                    await self.send_error('Authentication failed')
                    await self.close()
                    return
            except Exception as e:
                await self.send_error(f'Authentication error: {str(e)}')
                await self.close()
                return
        else:
            await self.send_error('No authentication token provided')
            await self.close()
            return
            
        # Send connection_ack for successful authentication
        await self.send(text_data=json.dumps({
            'type': 'connection_ack'
        }))
        
    async def handle_start(self, message):
        """Handle GraphQL subscription start"""
        sub_id = message.get('id')
        payload = message.get('payload', {})
        
        query = payload.get('query', '')
        variables = payload.get('variables', {})
        
        if not sub_id:
            await self.send_error('Subscription ID required')
            return
            
        # Execute GraphQL subscription
        try:
            # Create context with authenticated user
            class Context:
                def __init__(self, user):
                    self.user = user
                    
            context = Context(self.user)
            
            # Parse and validate the subscription
            if 'tradeChatMessage' in query:
                await self.start_chat_message_subscription(sub_id, variables, context)
            elif 'tradeStatusUpdate' in query:
                await self.start_status_update_subscription(sub_id, variables, context)
            elif 'typingIndicator' in query:
                await self.start_typing_subscription(sub_id, variables, context)
            else:
                await self.send_error(f'Unknown subscription type for ID {sub_id}')
                
        except Exception as e:
            await self.send_error(f'Subscription error: {str(e)}')
            
    async def handle_stop(self, message):
        """Handle GraphQL subscription stop"""
        sub_id = message.get('id')
        if sub_id:
            await self.unsubscribe(sub_id)
            
    async def start_chat_message_subscription(self, sub_id, variables, context):
        """Start chat message subscription"""
        trade_id = variables.get('tradeId')
        if not trade_id:
            await self.send_error('tradeId required for chat message subscription')
            return
            
        # Verify user has access to this trade
        has_access = await self.check_trade_access(trade_id, context.user)
        if not has_access:
            await self.send_error('Access denied to this trade')
            return
            
        # Join the channel group for this trade
        group_name = f'trade_chat_{trade_id}'
        await self.channel_layer.group_add(group_name, self.channel_name)
        
        # Store subscription info
        self.subscriptions[sub_id] = {
            'type': 'chat_message',
            'trade_id': trade_id,
            'group_name': group_name
        }
        
        # Send initial chat history
        await self.send_chat_history(sub_id, trade_id)
        
    async def start_status_update_subscription(self, sub_id, variables, context):
        """Start trade status update subscription"""
        trade_id = variables.get('tradeId')
        if not trade_id:
            await self.send_error('tradeId required for status update subscription')
            return
            
        has_access = await self.check_trade_access(trade_id, context.user)
        if not has_access:
            await self.send_error('Access denied to this trade')
            return
            
        group_name = f'trade_status_{trade_id}'
        await self.channel_layer.group_add(group_name, self.channel_name)
        
        self.subscriptions[sub_id] = {
            'type': 'status_update',
            'trade_id': trade_id,
            'group_name': group_name
        }
        
    async def start_typing_subscription(self, sub_id, variables, context):
        """Start typing indicator subscription"""
        trade_id = variables.get('tradeId')
        if not trade_id:
            await self.send_error('tradeId required for typing subscription')
            return
            
        has_access = await self.check_trade_access(trade_id, context.user)
        if not has_access:
            await self.send_error('Access denied to this trade')
            return
            
        group_name = f'trade_typing_{trade_id}'
        await self.channel_layer.group_add(group_name, self.channel_name)
        
        self.subscriptions[sub_id] = {
            'type': 'typing',
            'trade_id': trade_id,
            'group_name': group_name
        }
        
    async def unsubscribe(self, sub_id):
        """Remove subscription"""
        if sub_id in self.subscriptions:
            subscription = self.subscriptions[sub_id]
            group_name = subscription['group_name']
            
            # Leave the channel group
            await self.channel_layer.group_discard(group_name, self.channel_name)
            
            # Remove from subscriptions
            del self.subscriptions[sub_id]
            
            # Send complete message
            await self.send(text_data=json.dumps({
                'type': 'complete',
                'id': sub_id
            }))
            
    async def send_error(self, error_message):
        """Send GraphQL error message"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'payload': {'message': error_message}
        }))
        
    async def send_data(self, sub_id, data):
        """Send GraphQL subscription data"""
        await self.send(text_data=json.dumps({
            'type': 'data',
            'id': sub_id,
            'payload': data
        }))
        
    # Channel layer message handlers
    async def chat_message(self, event):
        """Handle incoming chat message from channel layer"""
        # Find subscription ID for this trade
        message_data = event['message']
        trade_id = str(event.get('trade_id'))
        
        for sub_id, subscription in self.subscriptions.items():
            if (subscription['type'] == 'chat_message' and 
                subscription['trade_id'] == trade_id):
                
                # Format GraphQL response
                await self.send_data(sub_id, {
                    'data': {
                        'tradeChatMessage': {
                            'tradeId': trade_id,
                            'message': message_data
                        }
                    }
                })
                
    async def status_update(self, event):
        """Handle trade status update from channel layer"""
        trade_id = str(event.get('trade_id'))
        
        for sub_id, subscription in self.subscriptions.items():
            if (subscription['type'] == 'status_update' and 
                subscription['trade_id'] == trade_id):
                
                await self.send_data(sub_id, {
                    'data': {
                        'tradeStatusUpdate': {
                            'tradeId': trade_id,
                            'status': event.get('status'),
                            'updatedBy': event.get('updated_by')
                        }
                    }
                })
                
    async def typing_indicator(self, event):
        """Handle typing indicator from channel layer"""
        trade_id = str(event.get('trade_id'))
        
        # Don't send typing indicator back to sender
        if event.get('user_id') == str(self.user.id):
            return
            
        for sub_id, subscription in self.subscriptions.items():
            if (subscription['type'] == 'typing' and 
                subscription['trade_id'] == trade_id):
                
                await self.send_data(sub_id, {
                    'data': {
                        'typingIndicator': {
                            'tradeId': trade_id,
                            'userId': event.get('user_id'),
                            'username': event.get('username'),
                            'isTyping': event.get('is_typing')
                        }
                    }
                })
    
    # Database operations
    @database_sync_to_async
    def authenticate_token(self, token):
        """Authenticate JWT token"""
        try:
            user = get_user_by_token(token)
            return user
        except Exception:
            return None
            
    @database_sync_to_async
    def check_trade_access(self, trade_id, user):
        """Check if user has access to trade"""
        try:
            trade = P2PTrade.objects.get(id=trade_id)
            has_access = (
                trade.buyer_user == user or 
                trade.seller_user == user or
                # Check business relationships
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists()) or
                # Fallback to old system
                trade.buyer == user or 
                trade.seller == user
            )
            return has_access
        except P2PTrade.DoesNotExist:
            return False
            
    async def send_chat_history(self, sub_id, trade_id):
        """Send initial chat history for subscription"""
        history = await self.get_chat_history(trade_id)
        
        for message in history:
            await self.send_data(sub_id, {
                'data': {
                    'tradeChatMessage': {
                        'tradeId': trade_id,
                        'message': message
                    }
                }
            })
            
    @database_sync_to_async
    def get_chat_history(self, trade_id):
        """Get chat history for trade"""
        try:
            trade = P2PTrade.objects.get(id=trade_id)
            messages = P2PMessage.objects.filter(trade=trade).order_by('created_at')
            
            history = []
            for message in messages:
                # Format message similar to WebSocket consumer
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
                        sender_info = {
                            'id': str(message.sender_business.id),
                            'username': message.sender_business.name,
                            'firstName': message.sender_business.name,
                            'lastName': '',
                            'type': 'business'
                        }
                else:
                    # Fallback
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
        except P2PTrade.DoesNotExist:
            return []