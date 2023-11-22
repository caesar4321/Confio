# sitemaps.py
from django.contrib import sitemaps
from django.urls import reverse
from languages import LANGUAGE_CHOICES

supported_languages = list(dict(LANGUAGE_CHOICES).keys())

class StaticViewSitemap(sitemaps.Sitemap):

    def items(self):
        return ['terms_of_service', 'privacy_policy', 'frequently_asked_questions', 'whitepaper', 'career/programmer', 'career/content_creator']

    def location(self, item):
        return reverse(item)

class LocalizationSitemap(sitemaps.Sitemap):

    def items(self):
        return supported_languages\
        +[f'{supported_language}/frequently_asked_questions' for supported_language in supported_languages]

    def location(self, obj):
        return f'/{obj}/'