from django.urls import re_path
from . import consumers
from .subscription_consumer import GraphQLSubscriptionConsumer

websocket_urlpatterns = [
    # GraphQL Subscriptions endpoint
    re_path(r'graphql/subscriptions/$', GraphQLSubscriptionConsumer.as_asgi()),
    
    # Legacy WebSocket chat endpoint (for backward compatibility)
    re_path(r'ws/trade/(?P<trade_id>[\w-]+)/$', consumers.TradeChatConsumer.as_asgi()),
]