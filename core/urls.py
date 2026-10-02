"""URL map for the public pages, plus two routes that are not pages.

This is PRD_website_pages.md §1.2's launch sitemap, one route per row, in
the order the PRD lists them, followed by /api/lead/ and /healthz/ from
backend_plan.md §7.1 and §10. The URLs are the ones the PRD specifies, so
they match the canonical tags and structured data already in the
templates.

Two deviations from §1.2, both required by the PRD's own notes:
  - There is no /services/ or /areas/ index page, because §1.2's sitemap
    does not contain one. The header's "Services" and "Areas" links point
    at the home-page sections, which carry links to every service and
    area page, and the footer carries both link lists in full.
  - /areas/old-town/ is absent and /areas/chandrasekharpur/ takes its
    place. §1.2's closing note records that "Old Town" is not among the
    seven localities the site actually names, and PAGE TYPE 3 instructs
    building area pages "from the 7-name list, not from the older 4-name
    list in §1.2". Add Old Town if §3 item 4 confirms it is served.
"""

from django.conf import settings
from django.contrib.sitemaps.views import sitemap
from django.urls import path
from django.views.generic import RedirectView, TemplateView

from core import views
from core.sitemaps import StaticViewSitemap
from core.views import PageView

sitemaps_dict = {
    "static": StaticViewSitemap,
}


def sitemap_view(request):
    response = sitemap(request, sitemaps=sitemaps_dict)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def page(route, template, name):
    return path(route, PageView.as_view(template_name=template), name=name)


urlpatterns = [
    # 1 - Home
    page("", "pages/home.html", "home"),
    # 2-7 - Current public service pages (§5)
    page(
        "services/leak-repair/",
        "pages/services/leak-repair.html",
        "service-leak-repair",
    ),
    page(
        "services/water-tank/", "pages/services/water-tank.html", "service-water-tank"
    ),
    page(
        "services/wc-toilet-fittings/",
        "pages/services/wc-toilet-fittings.html",
        "service-wc-toilet-fittings",
    ),
    page(
        "services/washbasin-bath-accessories/",
        "pages/services/washbasin-bath-accessories.html",
        "service-washbasin-bath-accessories",
    ),
    page(
        "services/bathroom-tile-grouting/",
        "pages/services/bathroom-tile-grouting.html",
        "service-bathroom-tile-grouting",
    ),
    page(
        "services/bathroom-installation-renovation/",
        "pages/services/bathroom-installation-renovation.html",
        "service-bathroom-installation-renovation",
    ),
    # Semantically close retired pages keep their search equity.
    path(
        "services/bathroom-plumbing/",
        RedirectView.as_view(
            pattern_name="service-bathroom-installation-renovation",
            permanent=True,
            query_string=True,
        ),
        name="service-bathroom-plumbing",
    ),
    path(
        "services/tap-fixture-repair/",
        RedirectView.as_view(
            pattern_name="service-washbasin-bath-accessories",
            permanent=True,
            query_string=True,
        ),
        name="service-tap-fixture-repair",
    ),
    # These enquiry types remain in both forms but no longer have public pages.
    path(
        "services/drain-cleaning/",
        views.GoneServiceView.as_view(),
        name="service-drain-cleaning",
    ),
    path(
        "services/emergency/",
        views.GoneServiceView.as_view(),
        name="service-emergency",
    ),
    # 8-11 - Service-area pages, genuinely served localities only (§5)
    # [Removed] Area pages removed in favour of city-wide coverage.
    # 12-13 - Trust and conversion
    page("about/", "pages/about.html", "about"),
    page("contact/", "pages/contact.html", "contact"),
    # 14-17 - Legal pages. Required before launch, since the forms collect
    # consented personal data (§5, §11 Phase 3).
    #
    # /cookies/ and /refunds/ were added by the September 2026 compliance
    # review. The cookie policy exists to document that this site sets only
    # strictly necessary cookies and therefore needs no consent banner -
    # the reasoning belongs somewhere durable, not in a commit message.
    # The refund page exists because money changes hands in person even
    # though there is no online checkout, and the Consumer Protection
    # (E-Commerce) Rules 2020 expect a published cancellation position.
    page("privacy/", "pages/privacy.html", "privacy"),
    page("cookies/", "pages/cookies.html", "cookies"),
    page("terms/", "pages/terms.html", "terms"),
    page("refunds/", "pages/refunds.html", "refunds"),
    # --- Not pages ---------------------------------------------------
    # backend_plan.md §7.1. POST only; this is the path §7.2's fetch()
    # posts to, so it is fixed.
    path("api/lead/", views.submit_lead, name="submit_lead"),
    path("api/booking/", views.submit_booking, name="submit_booking"),
    # backend_plan.md §10/§12 step 6 - the URL UptimeRobot pings.
    path("healthz/", views.healthz, name="healthz"),
    # --- SEO ---------------------------------------------------------
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="robots.txt",
            content_type="text/plain",
            extra_context={"SITE_URL": settings.SITE_URL},
        ),
        name="robots_txt",
    ),
    path(
        "sitemap.xml",
        sitemap_view,
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
