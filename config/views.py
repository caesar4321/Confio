from django.shortcuts import render, redirect
from django.utils.translation import get_language_from_request
import logging
import json
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_http_methods
import requests
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.views.generic import TemplateView

logger = logging.getLogger(__name__)

# Create your views here.

def index(request):
	path = request.path.lower()
	lang = get_language_from_request(request)
	
	titles = {
		'es': 'Confío: Envía y paga en dólares digitales',
		'en': 'Confío: Send and pay in digital dollars',
		'default': 'Confío'
	}
	
	title = titles.get(lang, titles['default'])
	og_description = {
		'es': 'Confío ayuda a venezolanos y argentinos a protegerse de la hiperinflación permitiéndoles pagar en dólares digitales estables.',
		'en': 'Confío helps Venezuelans and Argentines protect themselves from hyperinflation by allowing them to pay in stable digital dollars.',
		'default': 'Confío: Digital payments for Latin America'
	}
	
	return render(request, 'index.html', {
		'lang': lang,
		'title': title,
		'ogDescription': og_description.get(lang, og_description['default'])
	})

@csrf_exempt
def graphql_view(request):
	try:
		logger.info("Received GraphQL request")
		
		# Log request details
		logger.debug(f"Request method: {request.method}")
		logger.debug(f"Request headers: {dict(request.headers)}")
		
		# Parse and log request body
		try:
			body = request.body.decode('utf-8')
			logger.debug(f"Request body: {body}")
			data = json.loads(body) if body else {}
			logger.debug(f"Parsed request data: {data}")
		except json.JSONDecodeError as e:
			logger.error(f"Failed to parse request body: {str(e)}")
			return JsonResponse({
				'errors': [{'message': 'Invalid JSON in request body'}]
			}, status=400)
		
		# Process the request
		response = GraphQLView.as_view(graphiql=settings.DEBUG)(request)
		
		# Log response details
		logger.info(f"GraphQL response status: {response.status_code}")
		try:
			response_data = json.loads(response.content.decode('utf-8'))
			logger.debug(f"Response data: {json.dumps(response_data, indent=2)}")
		except:
			logger.debug(f"Response content: {response.content.decode('utf-8')}")
		
		return response
		
	except Exception as e:
		logger.error(f"GraphQL request failed: {str(e)}", exc_info=True)
		return JsonResponse({
			'errors': [{
				'message': str(e),
				'locations': [],
				'path': []
			}]
		}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def generate_zk_proof(request):
	try:
		# Parse request body
		data = json.loads(request.body)
		jwt = data.get('jwt')
		max_epoch = data.get('maxEpoch')
		randomness = data.get('randomness')
		key_claim_name = data.get('keyClaimName')
		extended_ephemeral_public_key = data.get('extendedEphemeralPublicKey')
		salt = data.get('salt')
		audience = data.get('audience')

		if not all([jwt, max_epoch, randomness, key_claim_name, extended_ephemeral_public_key, salt, audience]):
			return JsonResponse({
				'error': 'Missing required fields',
				'details': 'All fields (jwt, maxEpoch, randomness, keyClaimName, extendedEphemeralPublicKey, salt, audience) are required'
			}, status=400)

		# Verify Google token
		try:
			google_info = id_token.verify_oauth2_token(
				jwt,
				google_requests.Request(),
				audience
			)
			logger.info(f"Successfully verified Google token for sub: {google_info.get('sub')}")
		except Exception as e:
			logger.error(f"Google token verification failed: {str(e)}")
			return JsonResponse({
				'error': 'Token verification failed',
				'details': str(e)
			}, status=400)

		# Call zkLogin Prover service
		prover_url = "http://localhost:8001/v1"  # Update this to your prover service URL
		payload = {
			"jwt": jwt,
			"maxEpoch": max_epoch,
			"randomness": randomness,
			"keyClaimName": key_claim_name,
			"extendedEphemeralPublicKey": extended_ephemeral_public_key,
			"salt": salt,
			"audience": audience
		}

		try:
			response = requests.post(prover_url, json=payload)
			response.raise_for_status()
			zk_proof = response.json()
			
			return JsonResponse({
				'zkProof': zk_proof,
				'sub': google_info.get('sub'),
				'aud': audience
			})
		except requests.exceptions.RequestException as e:
			logger.error(f"Prover service error: {str(e)}")
			return JsonResponse({
				'error': 'Prover service error',
				'details': str(e)
			}, status=500)

	except json.JSONDecodeError:
		return JsonResponse({
			'error': 'Invalid JSON',
			'details': 'Request body must be valid JSON'
		}, status=400)
	except Exception as e:
		logger.error(f"Unexpected error: {str(e)}")
		return JsonResponse({
			'error': 'Internal server error',
			'details': str(e)
		}, status=500)

class DebugGraphQLView(GraphQLView):
	def dispatch(self, request, *args, **kwargs):
		try:
			if request.content_type == "application/json":
				data = json.loads(request.body)
				logger.info(f"GraphQL Request Body: {json.dumps(data, indent=2)}")
				if 'variables' in data:
					logger.info(f"GraphQL Variables: {json.dumps(data['variables'], indent=2)}")
			
			result = super().dispatch(request, *args, **kwargs)
			
			if hasattr(result, 'content'):
				try:
					content = json.loads(result.content)
					logger.info(f"GraphQL Response: {json.dumps(content, indent=2)}")
				except json.JSONDecodeError:
					logger.info(f"Raw Response Content: {result.content}")
			
			return result
			
		except Exception as e:
			logger.error(f"GraphQL View Error: {str(e)}", exc_info=True)
			return JsonResponse({
				"errors": [{"message": str(e)}]
			}, status=400)

class LegalPageView(TemplateView):
	template_name = None

	def get_template_names(self):
		page = self.kwargs.get('page')
		return [f'legal/{page}.html']


