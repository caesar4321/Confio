from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import NotificationPreference
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_notification_preference(sender, instance, created, **kwargs):
    """
    Create notification preferences for new users automatically
    """
    if created:
        try:
            # Create notification preference with push enabled by default
            notification_pref, pref_created = NotificationPreference.objects.get_or_create(
                user=instance,
                defaults={
                    'push_enabled': True,
                    'push_transactions': True,
                    'push_p2p': True,
                    'push_security': True,
                    'push_promotions': True,
                    'push_announcements': True,
                    'in_app_enabled': True,
                    'in_app_transactions': True,
                    'in_app_p2p': True,
                    'in_app_security': True,
                    'in_app_promotions': True,
                    'in_app_announcements': True,
                }
            )
            
            if pref_created:
                logger.info(f"Created notification preferences for new user {instance.id}")
            else:
                logger.info(f"Notification preferences already exist for user {instance.id}")
                
        except Exception as e:
            logger.error(f"Error creating notification preferences for user {instance.id}: {e}", exc_info=True)