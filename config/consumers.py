import channels_graphql_ws
from .schema import schema
from django.conf import settings
from channels.auth import get_user
from channels.db import database_sync_to_async
from django.core.cache import cache

#GRAPHQL_WS_SUBPROTOCOL = "graphql-ws"

class MyGraphqlWsConsumer(channels_graphql_ws.GraphqlWsConsumer):
	"""Channels WebSocket consumer which provides GraphQL API."""
	schema = schema

	# Uncomment to send keepalive message every 42 seconds.
	# send_keepalive_every = 42

	# Uncomment to process requests sequentially (useful for tests).
	# strict_ordering = True

	def match_allowed_origin(self):
		origin = None
		for header_name, header_value in self.scope.get('headers', []):
			if header_name == b'origin':
				origin = header_value.decode('utf-8')
		if settings.DEBUG:
			return True
		else:
			if origin == 'https://confio.me' or origin == 'https://www.confio.me':
				return True
			else:
				return False

	async def on_connect(self, payload):
		"""New client connection handler."""
		# You can `raise` from here to reject the connection.

		# Extract the Origin header
		if self.match_allowed_origin() is False:
			await self.close(1008)
			
		self.scope['user'] = await get_user(self.scope)

		if self.scope['user'].is_authenticated is True:
			user = self.scope['user']
		else:
			user = None

	async def idle_close(self, event):
		await self.close(1000) # 1001 is server or browser is away from... but 1001 is not allowed for close()


	async def receive(self, text_data=None, bytes_data=None, **kwargs):
		last_active = cache.get(self.channel_name)

		if text_data:
			await self.receive_json(await self.decode_json(text_data), **kwargs) #Graphql-websocket receive_json()
		else:
			raise ValueError("No text section for incoming WebSocket frame!")

class MyGraphqlAppWsConsumer(channels_graphql_ws.GraphqlWsConsumer):
	"""Channels WebSocket consumer which provides GraphQL API."""
	schema = schema

	# Uncomment to send keepalive message every 42 seconds.
	# send_keepalive_every = 42

	# Uncomment to process requests sequentially (useful for tests).
	# strict_ordering = True

	async def on_connect(self, payload):
		"""New client connection handler."""
		# You can `raise` from here to reject the connection.
		self.scope['user'] = await get_user(self.scope)

		if self.scope['user'].is_authenticated is True:
			user = self.scope['user']
		else:
			user = None

	async def idle_close(self, event):
		await self.close(1000) # 1001 is server or browser is away from... but 1001 is not allowed for close()


	async def receive(self, text_data=None, bytes_data=None, **kwargs):
		last_active = cache.get(self.channel_name)

		if text_data:
			await self.receive_json(await self.decode_json(text_data), **kwargs) #Graphql-websocket receive_json()
		else:
			raise ValueError("No text section for incoming WebSocket frame!")