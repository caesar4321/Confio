from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from graphql import GraphQLError, GraphQLResolveInfo

from users.models import User, Account
from .models import Channel, ChannelMembership, ContentItem, ContentPollVote, ContentSurface
from .polls import validate_poll_metadata
from .schema import VoteOnContentPoll, PortalSaveContentItem, build_poll_payload, build_editorial_message_payload, build_discover_feed_item_payload


def MockInfo(user):
    return Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=user))


class ContentPollTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='poll-user', email='poll@example.com', firebase_uid='poll-user')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.channel = Channel.objects.create(slug='poll-tests', kind='FOUNDER', title='Polls')
        self.metadata = {'poll': {'question': '¿Qué sigue?', 'options': [
            {'id': 'a', 'label': 'Pagos'}, {'id': 'b', 'label': 'Ahorro'},
        ], 'closed': False}}
        self.item = ContentItem.objects.create(channel=self.channel, item_type='TEXT', status='PUBLISHED',
                                               published_at=timezone.now(), metadata=self.metadata)
        self.surface = ContentSurface.objects.create(content_item=self.item, surface='DISCOVER')
        self.info = MockInfo(self.user)
        self.context = patch('inbox.schema.get_context_models', return_value=(self.user, self.account, None, {}))
        self.context.start()
        self.addCleanup(self.context.stop)

    def vote(self, option='a'):
        return VoteOnContentPoll.mutate(None, self.info, str(self.item.id), option)

    def test_duplicate_submission_and_change_keep_one_vote(self):
        self.vote()
        result = self.vote()
        self.assertEqual(result.poll.total_votes, 1)
        result = self.vote('b')
        self.assertEqual(result.poll.viewer_option_id, 'b')
        self.assertEqual([option.count for option in result.poll.options], [0, 1])
        self.assertEqual(ContentPollVote.objects.count(), 1)

    def test_results_shared_between_discover_and_messages(self):
        self.vote()
        membership = ChannelMembership.objects.create(channel=self.channel, user=self.user, account=self.account)
        discover = build_discover_feed_item_payload(self.item, self.user, self.account, None)
        message = build_editorial_message_payload(self.item, membership)
        self.assertEqual(discover.poll.viewer_option_id, message.poll.viewer_option_id)
        self.assertEqual(discover.poll.total_votes, message.poll.total_votes)

    def test_invalid_closed_future_draft_and_inactive_polls_rejected(self):
        with self.assertRaises(GraphQLError):
            self.vote('missing')
        for field, value in [('metadata', {'poll': {**self.metadata['poll'], 'closed': True}}),
                             ('published_at', timezone.now() + timedelta(days=1)), ('status', 'DRAFT')]:
            original = getattr(self.item, field)
            setattr(self.item, field, value)
            self.item.save()
            with self.assertRaises(GraphQLError):
                self.vote()
            setattr(self.item, field, original)
            self.item.save()
        self.channel.is_active = False
        self.channel.save()
        with self.assertRaises(GraphQLError):
            self.vote()
        self.assertEqual(ContentPollVote.objects.count(), 0)

    def test_expired_discover_and_missing_membership_rejected(self):
        self.surface.ends_at = timezone.now() - timedelta(seconds=1)
        self.surface.save()
        with self.assertRaises(GraphQLError):
            self.vote()
        self.surface.delete()
        with self.assertRaises(GraphQLError):
            self.vote()
        ChannelMembership.objects.create(channel=self.channel, user=self.user, account=self.account)
        self.item.visibility_policy = 'BACKLOG'
        self.item.save()
        self.assertTrue(self.vote().success)

    def test_anonymous_vote_rejected(self):
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(Exception):
            VoteOnContentPoll.mutate(None, MockInfo(AnonymousUser()), str(self.item.id), 'a')
        self.assertEqual(ContentPollVote.objects.count(), 0)

    def test_graphql_vote_contract(self):
        import graphene
        from .schema import Query, Mutation
        schema = graphene.Schema(query=Query, mutation=Mutation)
        result = schema.execute(
            'mutation($id: ID!) { voteOnContentPoll(contentItemId: $id, optionId: "a") { success poll { id totalVotes viewerOptionId options { id count } } } }',
            variable_values={'id': str(self.item.id)}, context_value=self.info.context,
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['voteOnContentPoll']['poll']['totalVotes'], 1)
        self.assertEqual(result.data['voteOnContentPoll']['poll']['viewerOptionId'], 'a')

    def test_vote_is_shared_across_account_contexts(self):
        self.vote()
        other_account = Account.objects.create(user=self.user, account_type='personal', account_index=1)
        with patch('inbox.schema.get_context_models', return_value=(self.user, other_account, None, {})):
            self.assertEqual(self.vote('b').poll.total_votes, 1)
        self.assertEqual(ContentPollVote.objects.count(), 1)

    def test_second_user_has_independent_answer(self):
        self.vote()
        other = User.objects.create_user(username='other-voter', email='other@example.com', firebase_uid='other-voter')
        ContentPollVote.objects.create(content_item=self.item, user=other, option_id='b')
        payload = build_poll_payload(self.item, other.id)
        self.assertEqual(payload.total_votes, 2)
        self.assertEqual(payload.viewer_option_id, 'b')

    def test_portal_creates_closes_and_locks_answer_configuration(self):
        self.user.is_staff = True
        self.user.is_verified = lambda: True
        def save(metadata, item_id=None):
            return PortalSaveContentItem.mutate(None, self.info, channel_slug=self.channel.slug,
                item_type='TEXT', status='PUBLISHED', metadata=metadata,
                content_item_id=item_id, surfaces=['DISCOVER', 'CHANNEL'])
        created = save(self.metadata)
        self.assertEqual(created.content_item.poll.question, '¿Qué sigue?')
        self.assertEqual(set(created.content_item.surfaces), {'DISCOVER', 'CHANNEL'})
        self.vote()
        changed = deepcopy(self.metadata)
        changed['poll']['options'][0]['label'] = 'Otra cosa'
        with self.assertRaises(GraphQLError):
            save(changed, self.item.id)
        with self.assertRaises(GraphQLError):
            save({}, self.item.id)
        closed = deepcopy(self.metadata)
        closed['poll']['closed'] = True
        self.assertTrue(save(closed, self.item.id).content_item.poll.closed)

    def test_portal_requires_staff(self):
        with self.assertRaises(GraphQLError):
            PortalSaveContentItem.mutate(None, self.info, channel_slug=self.channel.slug,
                item_type='TEXT', status='DRAFT', metadata=self.metadata)

    def test_validation_rejects_bad_questions_options_and_duplicate_labels(self):
        for poll in [[], {}, {'question': '', 'options': []},
                     {**self.metadata['poll'], 'options': [{'id': 'a', 'label': 'Solo'}]},
                     {**self.metadata['poll'], 'options': [{'id': 'a', 'label': 'Same'}, {'id': 'b', 'label': ' same '}]},
                     {**self.metadata['poll'], 'closed': 'false'}]:
            with self.subTest(poll=poll), self.assertRaises(GraphQLError):
                validate_poll_metadata({'poll': poll})

    def test_feed_poll_queries_do_not_grow_with_poll_count(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .schema import Query
        for index in range(5):
            item = ContentItem.objects.create(channel=self.channel, item_type='TEXT', status='PUBLISHED',
                                             published_at=timezone.now(), metadata=self.metadata)
            ContentSurface.objects.create(content_item=item, surface='DISCOVER')
            ContentPollVote.objects.create(content_item=item, user=self.user, option_id='b')
        self.vote()
        with CaptureQueriesContext(connection) as queries:
            page = Query().resolve_discover_feed(self.info, limit=20)
        poll_queries = [query for query in queries if 'inbox_contentpollvote' in query['sql']]
        self.assertEqual(len(poll_queries), 1)
        self.assertEqual(len(page.items), 6)
        self.assertEqual(sum(item.poll.total_votes for item in page.items), 6)
        self.assertEqual([item.poll.viewer_option_id for item in page.items].count('b'), 5)

    def test_portal_batches_poll_results_and_does_not_expose_viewer_answers(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .schema import Query
        self.user.is_staff = True
        self.user.is_verified = lambda: True
        self.vote()
        other = ContentItem.objects.create(channel=self.channel, item_type='TEXT', metadata=self.metadata)
        ContentPollVote.objects.create(content_item=other, user=self.user, option_id='b')
        with CaptureQueriesContext(connection) as queries:
            items = Query().resolve_portal_content_items(self.info)
        self.assertEqual(len([query for query in queries if 'inbox_contentpollvote' in query['sql']]), 1)
        self.assertTrue(all(item.poll.viewer_option_id is None for item in items if item.poll))
        self.assertEqual(sum(item.poll.total_votes for item in items if item.poll), 2)

    def test_channel_pages_batch_poll_results(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .schema import build_editorial_channel_payload, build_editorial_channel_thread_page
        membership = ChannelMembership.objects.create(channel=self.channel, user=self.user, account=self.account)
        self.item.visibility_policy = 'BACKLOG'
        self.item.save(update_fields=['visibility_policy'])
        self.vote()
        for index in range(4):
            ContentItem.objects.create(channel=self.channel, item_type='TEXT', status='PUBLISHED',
                                       published_at=timezone.now(), metadata=self.metadata)
        for build, expected_queries in [(build_editorial_channel_payload, 1), (build_editorial_channel_thread_page, 2)]:
            with self.subTest(builder=build.__name__), CaptureQueriesContext(connection) as queries:
                build(membership)
            self.assertEqual(len([query for query in queries if 'inbox_contentpollvote' in query['sql']]), expected_queries)

    def test_totals_and_viewer_answer_use_one_query_snapshot(self):
        self.vote()
        with self.assertNumQueries(1):
            payload = build_poll_payload(self.item, self.user.id)
        self.assertEqual(payload.total_votes, 1)
        self.assertEqual(payload.viewer_option_id, 'a')


    def test_results_use_configuration_that_belongs_to_counted_votes(self):
        # Model the interval between fetching a feed page and fetching its votes.
        stale_item = ContentItem.objects.get(pk=self.item.pk)
        self.user.is_staff = True
        self.user.is_verified = lambda: True
        changed = deepcopy(self.metadata)
        changed['poll']['options'][0] = {'id': 'new', 'label': 'Nueva opción'}
        PortalSaveContentItem.mutate(None, self.info, channel_slug=self.channel.slug,
            item_type='TEXT', status='PUBLISHED', content_item_id=self.item.id,
            metadata=changed, surfaces=['DISCOVER'])
        self.vote('new')
        payload = build_poll_payload(stale_item, self.user.id)
        self.assertEqual(payload.viewer_option_id, 'new')
        self.assertEqual(payload.total_votes, 1)
        self.assertEqual([(option.id, option.count) for option in payload.options], [('new', 1), ('b', 0)])
