from django.apps import AppConfig


class BlockchainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blockchain'
    verbose_name = 'Blockchain Integration'
    
    def ready(self):
        # No-op: Sui settings module removed; Algorand uses Django settings directly
        return
