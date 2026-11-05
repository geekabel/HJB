from django.contrib.admin.apps import AdminConfig


class AdminHJBConfig(AdminConfig):
    """Remplace « django.contrib.admin » dans INSTALLED_APPS (doc Django, default_site)."""

    default_site = "config.admin.SiteAdministration"
