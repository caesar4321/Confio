from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assistant'
    verbose_name = 'Confio Assistant'

    def ready(self):
        from django.db.models.signals import post_save

        from users.models import Account, Business, User

        from . import memory
        for model in (User, Account, Business):
            post_save.connect(memory.on_owner_saved, sender=model,
                              dispatch_uid=f'assistant_memory_erase_{model.__name__}')
