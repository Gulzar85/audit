from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from config.views import server_error

# Determine admin URL - use custom path in production, default in development
if settings.DEBUG or getattr(settings, 'ENVIRONMENT', 'production') == 'development':
    admin_url = getattr(settings, 'ADMIN_URL', 'admin/')
else:
    # In production, use ADMIN_URL from settings (set via environment variable)
    admin_url = getattr(settings, 'ADMIN_URL', 'admin/')
    # Security: If ADMIN_URL not properly configured, disable admin completely
    if admin_url == 'admin/':
        raise ValueError("ADMIN_URL must be configured in production environment")

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='audits:dashboard', permanent=False)),
    path(admin_url, admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('audits/', include('audits.urls')),
    path('restaurants/', include('restaurants.urls')),
    path('core/', include('core.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)

handler500 = 'config.views.server_error'
