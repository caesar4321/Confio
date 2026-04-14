from django.contrib.sitemaps import Sitemap


class StaticPageSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6
    protocol = 'https'

    def items(self):
        return [
            '/',
            '/discover/',
            '/about/julian-moon/',
            '/about/confio-news/',
            '/terms/',
            '/privacy/',
            '/deletion/',
        ]

    def location(self, item):
        return item
