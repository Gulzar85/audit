"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

# Determine admin URL - use custom path in production, default in development
if settings.DEBUG:
    admin_url = 'admin/'
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)
