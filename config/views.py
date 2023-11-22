from django.shortcuts import render, redirect
from django.utils.translation import get_language_from_request
from languages import LANGUAGE_CHOICES
from language_pack import translated_message

# Create your views here.

supported_languages = dict(LANGUAGE_CHOICES)

def index(request):
	path = request.path.lower()

	return render(request, 'index.html', {'lang': "en", 'title': "Confío: Latin America's PayPal", 'ogDescription': "Confío aims to be Latin America's PayPal by helping Venezuelans and Argentines from hyperinflation by allowing them to pay in US dollar stablecoins."})


