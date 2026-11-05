from django.contrib.admin.apps import AdminConfig


class HJBAdminConfig(AdminConfig):
    """Replaces "django.contrib.admin" in INSTALLED_APPS (Django docs, default_site)."""

    default_site = "config.admin.HJBAdminSite"
