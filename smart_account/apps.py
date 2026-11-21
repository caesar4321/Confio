from django.apps import AppConfig


class SmartAccountConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smart_account'
    verbose_name = 'Cuenta inteligente'

    def ready(self):
        from . import checks  # noqa: F401 — registers the system checks
