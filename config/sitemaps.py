# sitemaps.py
from django.contrib import sitemaps
from django.urls import reverse


class StaticViewSitemap(sitemaps.Sitemap):

    def items(self):
        return ['terms_of_service', 'privacy_policy', 'frequently_asked_questions', 'whitepaper', 'roadmap',]

    def location(self, item):
        return reverse(item)