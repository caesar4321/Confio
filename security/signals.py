from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import django_redis
from .models import IPAddress

@receiver(post_save, sender=IPAddress)
def update_blocked_ip_cache(sender, instance, **kwargs):
    """
    Update Redis blocked_ips set when an IPAddress is saved.
    """
    if not getattr(settings, 'USE_REDIS_CACHE', False):
        return

    try:
        redis_conn = django_redis.get_redis_connection("default")
        if instance.is_blocked:
            redis_conn.sadd("blocked_ips", instance.ip_address)
        else:
            redis_conn.srem("blocked_ips", instance.ip_address)
    except Exception:
        pass

@receiver(post_delete, sender=IPAddress)
def remove_blocked_ip_cache(sender, instance, **kwargs):
    """
    Remove IP from Redis blocked_ips set when an IPAddress is deleted.
    """
    if not getattr(settings, 'USE_REDIS_CACHE', False):
        return

    try:
        redis_conn = django_redis.get_redis_connection("default")
        redis_conn.srem("blocked_ips", instance.ip_address)
    except Exception:
        pass
