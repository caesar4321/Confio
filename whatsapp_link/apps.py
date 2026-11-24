from django.apps import AppConfig


class WhatsappLinkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'whatsapp_link'

    def ready(self):
        from django.db import transaction
        from django.db.models.signals import pre_delete

        from .models import WhatsAppLink

        def leave(sender, instance, **kwargs):
            """A row deleted with its person (a cascade) leaves no WhatsApp device behind."""
            from . import tasks
            if instance.provider == 'whatsmeow':
                link_id = instance.pk
                transaction.on_commit(lambda: tasks.logout.delay(link_id, ''))
            elif instance.context_id:
                provider, context, session = instance.provider, instance.context_id, instance.session_id
                transaction.on_commit(lambda: tasks.drop_profile.delay(provider, context, session))

        pre_delete.connect(leave, sender=WhatsAppLink, dispatch_uid='whatsapp_link.drop_profile')
