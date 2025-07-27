from django.apps import AppConfig


class UsdcTransactionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usdc_transactions'
    verbose_name = 'USDC Transactions'
    
    def ready(self):
        import usdc_transactions.signals
