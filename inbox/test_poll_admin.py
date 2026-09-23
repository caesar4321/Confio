from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from django.utils import timezone
from graphql import GraphQLResolveInfo

from users.models import User
from .admin import ChannelAdmin, ContentItemAdmin
from .models import Channel, ContentItem, ContentPollVote
from .schema import PortalSaveContentItem, build_poll_payload


class PollAdminSaveTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='poll-admin', email='poll-admin@example.com',
            firebase_uid='poll-admin', is_staff=True,
        )
        self.staff.is_verified = lambda: True
        self.info = Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=self.staff))
        self.channel = Channel.objects.create(slug='poll-admin', kind='FOUNDER', title='Polls')
        self.metadata = {'poll': {'question': 'Next?', 'options': [
            {'id': 'a', 'label': 'Payments'}, {'id': 'b', 'label': 'Savings'},
        ], 'closed': False}}
        self.item = ContentItem.objects.create(
            channel=self.channel, item_type='TEXT', status='PUBLISHED',
            published_at=timezone.now(), metadata=self.metadata,
        )

    def portal_save(self, metadata):
        PortalSaveContentItem.mutate(
            None, self.info, channel_slug=self.channel.slug, item_type='TEXT',
            status='PUBLISHED', content_item_id=self.item.pk, metadata=metadata,
        )

    def admin_save(self, stale, inline):
        stale.title = 'Edited in Django admin'
        stale.metadata['tag_color'] = '#2563EB'
        if inline:
            formset = Mock(model=ContentItem, deleted_objects=[])
            formset.save.return_value = [stale]
            ChannelAdmin(Channel, AdminSite()).save_formset(None, None, formset, True)
            formset.save.assert_called_once_with(commit=False)
            formset.save_m2m.assert_called_once_with()
        else:
            ContentItemAdmin(ContentItem, AdminSite()).save_model(None, stale, None, True)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Edited in Django admin')
        self.assertEqual(self.item.metadata['tag_color'], '#2563EB')

    def test_stale_admin_saves_preserve_new_options_and_first_vote(self):
        for inline in [False, True]:
            with self.subTest(inline=inline):
                stale = ContentItem.objects.get(pk=self.item.pk)
                metadata = deepcopy(self.metadata)
                metadata['poll']['options'][0] = {'id': 'new', 'label': 'New choice'}
                self.portal_save(metadata)
                ContentPollVote.objects.update_or_create(
                    content_item=self.item, user=self.staff, defaults={'option_id': 'new'},
                )
                self.admin_save(stale, inline)
                self.assertEqual(self.item.metadata['poll'], metadata['poll'])
                poll = build_poll_payload(self.item, self.staff.pk)
                self.assertEqual(poll.total_votes, 1)
                self.assertEqual(poll.options[0].count, 1)
                # Reset for the second independent admin path.
                ContentPollVote.objects.filter(content_item=self.item).delete()
                self.portal_save(self.metadata)

    def test_stale_admin_saves_preserve_closure(self):
        for inline in [False, True]:
            with self.subTest(inline=inline):
                self.portal_save(self.metadata)
                stale = ContentItem.objects.get(pk=self.item.pk)
                metadata = deepcopy(self.metadata)
                metadata['poll']['closed'] = True
                self.portal_save(metadata)
                self.admin_save(stale, inline)
                self.assertTrue(self.item.metadata['poll']['closed'])

    def test_stale_admin_saves_do_not_restore_removed_poll(self):
        for inline in [False, True]:
            with self.subTest(inline=inline):
                self.portal_save(self.metadata)
                stale = ContentItem.objects.get(pk=self.item.pk)
                self.portal_save({})
                self.admin_save(stale, inline)
                self.assertNotIn('poll', self.item.metadata)
