from django.shortcuts import render, redirect
from django.utils.translation import get_language_from_request

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


