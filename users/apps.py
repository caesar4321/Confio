from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'users'
    
    def ready(self):
        import users.signals
        import users.payroll_sync
        
        # Eagerly load the encryption master key on startup
        # Initialize encryption key manager early to fail fast if keys are missing
        from .encryption import GlobalKeyManager
        try:
            GlobalKeyManager.get_instance()
        except Exception:
            # Error is already logged in encryption.py
            # We re-raise to stop startup if critical key is missing
            raise
