from django.contrib.sitemaps import Sitemap
from datetime import date


class StaticPageSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6
    protocol = 'https'

    def items(self):
        today = date.today()
        return [
            {'location': '/', 'lastmod': today},
            {'location': '/discover/', 'lastmod': today},
            {'location': '/about/julian-moon/', 'lastmod': today},
            {'location': '/about/confio-news/', 'lastmod': today},
            {'location': '/terms/', 'lastmod': today},
            {'location': '/privacy/', 'lastmod': today},
            {'location': '/deletion/', 'lastmod': today},
        ]

    def location(self, item):
        return item['location']

    def lastmod(self, item):
        return item['lastmod']
