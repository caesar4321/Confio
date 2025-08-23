from django.urls import re_path
from . import consumers
from .subscription_consumer import GraphQLSubscriptionConsumer
from payments.ws_consumers import PaySessionConsumer

websocket_urlpatterns = [
    # GraphQL Subscriptions endpoint
    re_path(r'graphql/subscriptions/$', GraphQLSubscriptionConsumer.as_asgi()),
    
    # Legacy WebSocket chat endpoint (for backward compatibility)
    re_path(r'ws/trade/(?P<trade_id>[\w-]+)/$', consumers.TradeChatConsumer.as_asgi()),

    # Payment flow ephemeral WebSocket
    re_path(r'ws/pay_session$', PaySessionConsumer.as_asgi()),
]
