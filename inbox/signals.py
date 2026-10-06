from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save, pre_delete, pre_save
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


# A deleted or banned account's Comunidad content comes down. Reads already
# hide deleted accounts at once (community.READABLE); this removes the posts,
# comments and profile picture for good, public images included.
def _remove_member_content_after_commit(user_id, kind):
    from .tasks import remove_member_content_task

    transaction.on_commit(lambda: remove_member_content_task.delay(user_id, kind))


@receiver(pre_save, sender='users.User')
def _remember_user_deleted_at(sender, instance, **kwargs):
    # Only a save that marks the account deleted needs the previous value; the
    # many ordinary user saves (logins, profile edits) cost no extra query.
    # A deferred deleted_at isn't being saved, and reading it would load it:
    # treat it as unchanged.
    if 'deleted_at' in instance.get_deferred_fields():
        instance._community_was_deleted = True
        return
    if instance.deleted_at is None or not instance.pk:
        instance._community_was_deleted = False
        return
    previous = sender.all_objects.filter(pk=instance.pk).values_list('deleted_at', flat=True).first()
    instance._community_was_deleted = previous is not None


@receiver(post_save, sender='users.User')
def remove_content_of_deleted_account(sender, instance, created, **kwargs):
    if getattr(instance, '_community_was_deleted', True):
        return
    if instance.deleted_at is not None:
        _remove_member_content_after_commit(instance.pk, 'deleted')


@receiver(post_save, sender='security.UserBan')
def remove_content_of_banned_account(sender, instance, created, **kwargs):
    if created and instance.deleted_at is None and instance.user_id:
        _remove_member_content_after_commit(instance.user_id, 'banned')


@receiver(pre_delete, sender='users.User')
def delete_member_content_with_account(sender, instance, **kwargs):
    """A hard-deleted user takes their Comunidad posts with them (the posts
    cannot outlive their owner), and every public image they had is doomed in
    the same transaction so the ledger sweeper deletes it."""
    from django.conf import settings
    from security.s3_utils import key_from_url

    from . import community, public_objects
    from .models import CommunityComment, ContentItem, OwnerType, ProfilePictureSubmission

    items = ContentItem.objects.filter(owner_type=OwnerType.USER, owner_user=instance)
    # Comment text (theirs, and others' on their posts) also sits in
    # members' notifications.
    community.erase_comment_notifications(
        list(CommunityComment.objects.filter(Q(author=instance) | Q(parent__author=instance))
             .values_list('id', flat=True)),
        content_item_ids=list(items.values_list('id', flat=True)),
    )
    backups = []
    for metadata in items.values_list('metadata', flat=True):
        url = ((metadata or {}).get('image') or {}).get('url')
        if url:
            public_objects.doom(settings.AWS_PUBLICATIONS_BUCKET, key_from_url(url))
        if (metadata or {}).get('removed_image_key'):
            backups.append(metadata['removed_image_key'])
    if backups:
        # Private moderation copies go too (the bucket lifecycle is the backstop).
        def delete_backups():
            from security.s3_utils import delete_object

            for key in backups:
                try:
                    delete_object(key=key, bucket=settings.AWS_COMMUNITY_UPLOAD_BUCKET)
                except Exception:
                    pass

        transaction.on_commit(delete_backups)
    for url in ProfilePictureSubmission.objects.filter(user=instance).exclude(public_url='').values_list('public_url', flat=True):
        public_objects.doom(settings.AWS_PROFILE_PICTURES_BUCKET, key_from_url(url))
    items.delete()
