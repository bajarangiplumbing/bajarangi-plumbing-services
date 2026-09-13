from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    def get_urls(self, page=1, site=None, protocol=None):
        parsed = urlparse(settings.SITE_URL)
        protocol = parsed.scheme or "http"
        
        class FakeSite:
            domain = parsed.netloc or parsed.path
            name = domain
            
        return super().get_urls(page=page, site=FakeSite(), protocol=protocol)

    def items(self):
        return [
            "home",
            "service-leak-repair",
            "service-water-tank",
            "service-wc-toilet-fittings",
            "service-washbasin-bath-accessories",
            "service-bathroom-tile-grouting",
            "service-bathroom-installation-renovation",
            "about",
            "contact",
            "privacy",
            "cookies",
            "terms",
            "refunds",
        ]

    def location(self, item):
        return reverse(item)
