from django.apps import AppConfig


class BlockchainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blockchain'
    verbose_name = 'Blockchain Integration'
    
    def ready(self):
        # Optional: warm Algod-related caches to reduce first-payment latency
        try:
            from django.conf import settings
            if getattr(settings, 'PAYMENT_WARM_CACHE_ON_STARTUP', False):
                from .payment_transaction_builder import PaymentTransactionBuilder
                builder = PaymentTransactionBuilder(network=settings.ALGORAND_NETWORK)
                # Warm app_info and app opt-in by validating app for configured assets
                for asset_id in (builder.cusd_asset_id, builder.confio_asset_id):
                    if asset_id:
                        try:
                            builder.validate_payment_app(asset_id)
                        except Exception:
                            # Do not block startup on warm failures
                            pass
        except Exception:
            # Never block app startup due to warm-up
            pass
