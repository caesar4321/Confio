from django.apps import AppConfig


class CusdPlusConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cusd_plus'
    verbose_name = 'Confío Dollar+ (cUSD+ savings)'

    def ready(self):
        from . import signals  # noqa: F401 — referral activation for savings deposits
