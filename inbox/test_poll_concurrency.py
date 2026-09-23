"""PostgreSQL regression coverage for the poll's publication-row lock."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from graphql import GraphQLError, GraphQLResolveInfo

from users.models import Account, User
from .models import Channel, ContentItem, ContentPollVote, ContentSurface
from .schema import PortalSaveContentItem, VoteOnContentPoll


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
class ContentPollConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='poll-race', email='race@example.com', firebase_uid='poll-race')
        self.user.is_staff = True
        self.user.is_verified = lambda: True
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.channel = Channel.objects.create(slug='poll-race', kind='FOUNDER', title='Poll')
        self.metadata = {'poll': {'question': 'Choose', 'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}]}}
        self.item = ContentItem.objects.create(channel=self.channel, item_type='TEXT', status='PUBLISHED',
                                               published_at=timezone.now(), metadata=self.metadata)
        ContentSurface.objects.create(content_item=self.item, surface='DISCOVER')
        self.info = Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=self.user))

    def run_concurrently(self, *actions):
        barrier = Barrier(len(actions))
        def run(action):
            try:
                barrier.wait(timeout=5)
                try:
                    return action()
                except GraphQLError as error:
                    return error
            finally:
                connections.close_all()
        with patch('inbox.schema.get_context_models', return_value=(self.user, self.account, None, {})):
            with ThreadPoolExecutor(max_workers=len(actions)) as executor:
                futures = [executor.submit(run, action) for action in actions]
                return [future.result(timeout=10) for future in futures]

    def vote(self):
        return VoteOnContentPoll.mutate(None, self.info, str(self.item.id), 'a')

    def test_simultaneous_duplicate_submissions_are_idempotent(self):
        results = self.run_concurrently(self.vote, self.vote)
        self.assertTrue(all(result.success for result in results))
        self.assertEqual([result.poll.total_votes for result in results], [1, 1])
        self.assertEqual(ContentPollVote.objects.filter(content_item=self.item).count(), 1)

    def test_option_edit_and_first_vote_cannot_both_succeed(self):
        changed = deepcopy(self.metadata)
        changed['poll']['options'][0] = {'id': 'new', 'label': 'New answer'}
        def edit():
            return PortalSaveContentItem.mutate(None, self.info, channel_slug=self.channel.slug,
                item_type='TEXT', status='PUBLISHED', content_item_id=self.item.id,
                metadata=changed, surfaces=['DISCOVER'])
        results = self.run_concurrently(self.vote, edit)
        self.assertEqual(sum(isinstance(result, GraphQLError) for result in results), 1)
        self.item.refresh_from_db()
        option_ids = {option['id'] for option in self.item.metadata['poll']['options']}
        self.assertTrue(all(vote.option_id in option_ids for vote in self.item.poll_votes.all()))
