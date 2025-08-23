from django.shortcuts import render
from django.utils.translation import get_language_from_request
from django.views.generic import TemplateView
from django.http import HttpResponse
import logging

logger = logging.getLogger(__name__)

def index(request):
	path = request.path.lower()
	lang = get_language_from_request(request)
	
	# Check for Korean language specifically
	if 'ko' in lang.lower():
		lang = 'ko'
	elif 'es' in lang.lower():
		lang = 'es'
	else:
		lang = 'en'  # Default to English for all other languages
	
	titles = {
		'es': 'Confío: PayPal de América Latina',
		'en': 'Confío: PayPal of Latin America',
		'ko': 'Confío: 라틴 아메리카의 PayPal',
		'default': 'Confío: PayPal de América Latina'
	}
	
	title = titles.get(lang, titles['default'])
	og_description = {
		'es': 'Sé de los primeros 10,000 beta testers. Envía y recibe dólares digitales sin comisiones. Protege tu dinero de la inflación en Venezuela, Argentina y Bolivia.',
		'en': 'Be among the first 10,000 beta testers. Send and receive digital dollars with no fees. Protect your money from inflation in Venezuela, Argentina and Bolivia.',
		'ko': '첫 10,000명의 베타 테스터가 되세요. 수수료 없이 디지털 달러를 보내고 받으세요. 베네수엘라, 아르헨티나, 볼리비아의 인플레이션으로부터 돈을 보호하세요.',
		'default': 'Confío: Digital payments for Latin America'
	}
	og_image = "https://confio.lat/images/ConfioApp.png"
	
	return render(request, 'index.html', {
		'lang': lang,
		'title': title or titles['default'],
		'ogDescription': og_description.get(lang, og_description['default']) or og_description['default'],
		'ogImage': og_image
	})

class LegalPageView(TemplateView):
	template_name = None

	def get_template_names(self):
		page = self.kwargs.get('page')
		return [f'legal/{page}.html']

def terms_view(request):
	"""View for Terms of Service page."""
	return render(request, 'terms.html')

def privacy_view(request):
	"""View for Privacy Policy page."""
	return render(request, 'privacy.html')

def deletion_view(request):
    """View for Data Deletion page."""
    return render(request, 'deletion.html')


def health_view(request):
    """Ultra-light health endpoint for prewarm/keepalive.

    Returns HTTP 200 with a short body and no heavy checks.
    """
    return HttpResponse('ok', content_type='text/plain')

