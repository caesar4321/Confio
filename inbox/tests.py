from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import User

from .models import Channel, ChannelKind, ContentItem, ContentStatus, ContentSurface, ContentSurfaceType


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
