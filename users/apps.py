from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'users'
    
    def ready(self):
        import users.signals
        import users.payroll_sync

        # Every request starts with no reader country (users/number_format):
        # a worker thread never carries the previous request's into this one.
        from django.core.signals import request_started

        from .number_format import set_reader
        request_started.connect(lambda **kwargs: set_reader(None), weak=False,
                                dispatch_uid='users.number_format.reset_reader')
        
        # Eagerly load the encryption master key on startup
        # Initialize encryption key manager early to fail fast if keys are missing
        from .encryption import GlobalKeyManager
        try:
            GlobalKeyManager.get_instance()
        except Exception:
            # Error is already logged in encryption.py
            # We re-raise to stop startup if critical key is missing
            raise
