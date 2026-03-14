from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from users.models import Account

from .models import Channel, ChannelMembership, SubscriptionMode
from .models import ContentItem, ContentStatus
from .tasks import send_content_item_push_task


@receiver(post_save, sender=Account)
def provision_default_channel_memberships(sender, instance: Account, created: bool, **kwargs):
    if not created:
        return

    default_channels = Channel.objects.filter(
        subscription_mode__in=[SubscriptionMode.REQUIRED, SubscriptionMode.DEFAULT_ON],
        is_active=True,
    )

    membership_kwargs = {'user': instance.user}
    if instance.account_type == 'business' and instance.business_id:
        membership_kwargs['business'] = instance.business
    else:
        membership_kwargs['account'] = instance

    for channel in default_channels:
        ChannelMembership.objects.get_or_create(
            channel=channel,
            **membership_kwargs,
            defaults={
                'is_subscribed': True,
            },
        )


@receiver(pre_save, sender=ContentItem)
def capture_content_item_publish_state(sender, instance: ContentItem, **kwargs):
    if not instance.pk:
        instance._publish_state_before_save = None
        return

    instance._publish_state_before_save = (
        ContentItem.objects.filter(pk=instance.pk)
        .values('status', 'send_push', 'published_at', 'push_sent_at')
        .first()
    )


@receiver(post_save, sender=ContentItem)
def enqueue_content_item_push_on_publish(sender, instance: ContentItem, created: bool, **kwargs):
    should_send_now = (
        instance.status == ContentStatus.PUBLISHED
        and instance.send_push
        and instance.published_at is not None
        and instance.push_sent_at is None
    )
    if not should_send_now:
        return

    previous_state = getattr(instance, '_publish_state_before_save', None)
    previously_ready = bool(
        previous_state
        and previous_state.get('status') == ContentStatus.PUBLISHED
        and previous_state.get('send_push')
        and previous_state.get('published_at') is not None
        and previous_state.get('push_sent_at') is None
    )
    if not created and previously_ready:
        return

    transaction.on_commit(lambda: send_content_item_push_task.delay(instance.id))
