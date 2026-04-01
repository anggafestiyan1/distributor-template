"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("distributors/", include("apps.distributors.urls", namespace="distributors")),
    path("fields/", include("apps.field_templates.urls", namespace="field_templates")),
    path("uploads/", include("apps.uploads.urls", namespace="uploads")),
    path("review/", include("apps.review.urls", namespace="review")),
    path("master-data/", include("apps.master_data.urls", namespace="master_data")),
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("health/", include("apps.dashboard.health_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
