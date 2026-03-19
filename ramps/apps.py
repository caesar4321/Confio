from django.apps import AppConfig


class RampsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ramps'

    def ready(self):
        import ramps.signals  # noqa: F401
