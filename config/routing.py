from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from .consumers import MyGraphqlWsConsumer, MyGraphqlAppWsConsumer
from channels.security.websocket import AllowedHostsOriginValidator

application = ProtocolTypeRouter({
	'http': get_asgi_application(),
	'websocket':
		AuthMiddlewareStack(
			URLRouter([
				path('graphql/', MyGraphqlWsConsumer.as_asgi()),
				path('graphqlapp/', MyGraphqlAppWsConsumer.as_asgi()),
			])
	),
})