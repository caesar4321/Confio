from django.apps import AppConfig


class PaymentAccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payment_accounts'

    def ready(self):
        from . import checks  # noqa: F401
        from . import activity  # noqa: F401
        from . import infinia_maintenance  # noqa: F401
    verbose_name = 'Payment accounts'
