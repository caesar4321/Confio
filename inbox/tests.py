from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import Account, User

from .models import (
    Channel,
    ChannelKind,
    ContentItem,
    ContentStatus,
    ContentSurface,
    ContentSurfaceType,
    SupportConversation,
    SupportConversationStatus,
    SupportMessage,
    SupportSenderType,
)
from .schema import Query


class MockInfo:
    class Context:
        def __init__(self, user):
            self.user = user

    def __init__(self, user):
        self.context = self.Context(user)


class PortalSupportConversationSearchTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='testpass123',
            firebase_uid='firebase-staff',
            is_staff=True,
        )
        self.staff.is_verified = lambda: True
        self.query = Query()
        self.info = MockInfo(self.staff)

    def _create_conversation(self, index, *, first_name='User', last_name='', email=None, body='General question', minutes_ago=0):
        user = User.objects.create_user(
            username=f'user{index}',
            email=email or f'user{index}@example.com',
            password='testpass123',
            firebase_uid=f'firebase-user-{index}',
            first_name=first_name,
            last_name=last_name,
        )
        account = Account.objects.create(user=user, account_type='personal', account_index=0)
        conversation = SupportConversation.objects.create(
            user=user,
            account=account,
            status=SupportConversationStatus.OPEN,
            last_message_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        SupportMessage.objects.create(
            conversation=conversation,
            sender_type=SupportSenderType.USER,
            sender_user=user,
            body=body,
            created_at=conversation.last_message_at,
        )
        return conversation

    def test_search_matches_customer_outside_default_first_100(self):
        target = self._create_conversation(
            999,
            first_name='Needle',
            last_name='Customer',
            minutes_ago=999,
        )
        for index in range(105):
            self._create_conversation(index, minutes_ago=index)

        results = self.query.resolve_portal_support_conversations(
            self.info,
            status=SupportConversationStatus.OPEN,
            search='Needle',
        )

        self.assertEqual([result.id for result in results], [str(target.id)])

    def test_search_matches_message_body_outside_default_first_100(self):
        target = self._create_conversation(
            1000,
            body='My transfer has the unique reference AlphaNeedle42',
            minutes_ago=999,
        )
        for index in range(105):
            self._create_conversation(index, minutes_ago=index)

        results = self.query.resolve_portal_support_conversations(
            self.info,
            status=SupportConversationStatus.OPEN,
            search='AlphaNeedle42',
        )

        self.assertEqual([result.id for result in results], [str(target.id)])


class DiscoverStructuredDataTests(TestCase):
    def setUp(self):
        self.founder_user = User.objects.create_user(
            username='julianmoon',
            password='testpass123',
            firebase_uid='firebase-julian',
            first_name='Julian',
            last_name='Moon',
        )
        self.founder_channel = Channel.objects.create(
            slug='founder',
            kind=ChannelKind.FOUNDER,
            title='Founder',
        )
        self.news_channel = Channel.objects.create(
            slug='news',
            kind=ChannelKind.NEWS,
            title='News',
        )

    def _publish(self, *, channel, title, author_user=None, metadata=None):
        item = ContentItem.objects.create(
            channel=channel,
            author_user=author_user,
            owner_type='SYSTEM',
            item_type='NEWS',
            status=ContentStatus.PUBLISHED,
            title=title,
            body='Body copy for structured data test.',
            published_at=timezone.now(),
            metadata=metadata or {},
        )
        ContentSurface.objects.create(
            content_item=item,
            surface=ContentSurfaceType.DISCOVER,
            rank=1,
        )
        return item

    def test_founder_posts_render_person_author_schema(self):
        item = self._publish(
            channel=self.founder_channel,
            title='Founder update',
            author_user=self.founder_user,
        )

        response = self.client.get(
            reverse('discover_post_detail', kwargs={'post_id': item.id, 'slug': 'founder-update'})
        )

        self.assertContains(response, '"@type": "Person"')
        self.assertContains(response, '"name": "Julian Moon"')
        self.assertContains(response, '"jobTitle": "Founder"')
        self.assertContains(response, '"worksFor": {')
    def test_news_posts_can_render_organization_author_schema_from_metadata(self):
        item = self._publish(
            channel=self.news_channel,
            title='Market note',
            metadata={
                'schema_author_type': 'organization',
                'schema_author_name': 'Confío News',
                'schema_author_url': 'https://confio.lat/discover/',
            },
        )

        response = self.client.get(
            reverse('discover_post_detail', kwargs={'post_id': item.id, 'slug': 'market-note'})
        )

        self.assertContains(response, '"@type": "Organization"')
        self.assertContains(response, '"name": "Confío News"')
        self.assertNotContains(response, '"jobTitle": "Founder"')
