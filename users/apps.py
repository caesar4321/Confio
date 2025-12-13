from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'users'
    
    def ready(self):
        import users.signals
        import users.payroll_sync
        
        # Eagerly load the encryption master key on startup
        # This ensures the application fails fast if the key is missing or inaccessible
        from .encryption import GlobalKeyManager
        try:
            GlobalKeyManager.get_instance()
        except Exception:
            # Error is already logged in encryption.py
            # We re-raise to stop startup if critical key is missing
            raise
