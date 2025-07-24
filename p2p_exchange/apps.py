from django.apps import AppConfig


class P2PExchangeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'p2p_exchange'
    
    def ready(self):
        import p2p_exchange.signals
