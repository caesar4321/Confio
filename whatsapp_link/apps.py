from django.apps import AppConfig


class WhatsappLinkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'whatsapp_link'

    def ready(self):
        from django.db import transaction
        from django.db.models.signals import pre_delete

        from .models import WhatsAppLink

        def drop_profile(sender, instance, **kwargs):
            """A row deleted with its person (a cascade) leaves no WhatsApp session at the vendor."""
            if not instance.context_id:
                return
            provider, context, session = instance.provider, instance.context_id, instance.session_id
            from . import tasks
            transaction.on_commit(lambda: tasks.drop_profile.delay(provider, context, session))

        pre_delete.connect(drop_profile, sender=WhatsAppLink, dispatch_uid='whatsapp_link.drop_profile')
