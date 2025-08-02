from django.apps import AppConfig


class BlockchainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blockchain'
    verbose_name = 'Blockchain Integration'
    
    def ready(self):
        # Import settings when app is ready
        from . import blockchain_settings
