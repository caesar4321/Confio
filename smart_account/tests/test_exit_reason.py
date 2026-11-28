"""Why people leave the subscribe screen (review 2026-11-28: 41 opened it, none
signed). One answer per person per day, only about a visit that just happened."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from smart_account import funnel, schema
from users.models_analytics import FunnelEvent

from .base import SmartAccountTestCase


class ExitReasonTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('leaver')

    def opened(self, ago=timedelta(minutes=3), stage='subscribe_opened'):
        event = FunnelEvent.objects.create(event_name=funnel.EVENT, user=self.user, properties={'stage': stage})
        FunnelEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - ago)

    def record(self, *args, **kw):
        # emit_once writes on commit: a TestCase never commits, so run the callbacks here.
        with self.captureOnCommitCallbacks(execute=True):
            return funnel.record_exit(*args, **kw)

    def answers(self):
        return list(FunnelEvent.objects.filter(event_name=funnel.EVENT, properties__stage='exit_reason')
                    .values_list('properties', flat=True))

    def test_answer_after_a_visit_is_kept_with_plan_and_verified(self):
        self.opened()
        with mock.patch('security.identity_status.is_identity_verified', return_value=False):
            self.assertTrue(self.record(self.user, 'money', plan='annual'))
        (props,) = self.answers()
        self.assertEqual((props['reason'], props['plan'], props['verified']), ('money', 'annual', False))

    def test_refused_without_a_recent_visit_or_after_signing(self):
        self.assertFalse(self.record(self.user, 'money'))
        self.opened(ago=timedelta(hours=3))
        self.assertFalse(self.record(self.user, 'money'))
        self.opened()
        self.opened(ago=timedelta(minutes=1), stage='subscribe_signed')
        self.assertFalse(self.record(self.user, 'money'))
        self.assertEqual(self.answers(), [])

    def test_unknown_reason_and_once_a_day(self):
        self.opened()
        self.assertFalse(self.record(self.user, 'free text'))
        self.assertTrue(self.record(self.user, 'later', plan='weird'))
        self.assertTrue(self.record(self.user, 'value'))
        (props,) = self.answers()
        self.assertEqual((props['reason'], props['plan']), ('later', ''))

    def test_mutation(self):
        self.opened()
        from types import SimpleNamespace
        from django.contrib.auth.models import AnonymousUser
        with self.captureOnCommitCallbacks(execute=True):
            out = schema.RecordSmartAccountExitReason().mutate(self.info(self.user), ' Trust ', plan='monthly')
        self.assertTrue(out.success)
        self.assertEqual(self.answers()[0]['reason'], 'trust')
        anon = schema.RecordSmartAccountExitReason().mutate(SimpleNamespace(context=SimpleNamespace(user=AnonymousUser())), 'trust')
        self.assertFalse(anon.success)

    def test_keys_match_the_app(self):
        import re
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / 'apps/src/services/smartAccountExit.ts').read_text()
        block = source.split('SMART_ACCOUNT_EXIT_REASONS = [', 1)[1].split('] as const', 1)[0]
        keys = set(re.findall(r"\['(\w+)',", block)) | {re.search(r"SMART_ACCOUNT_EXIT_SKIPPED = '(\w+)'", source).group(1)}
        self.assertEqual(keys, set(funnel.EXIT_REASONS))


class IdentityReviewCodeTests(SmartAccountTestCase):
    def test_documents_with_the_reviewers_are_not_told_to_verify(self):
        from unittest import mock as m
        user = self.make_user('waiting')
        with m.patch('smart_account.offer.subscribe_block', return_value='identity'), \
                m.patch('assistant.suggestions.waits_on_review', return_value=True):
            result = schema.Query.resolve_smart_account_offer(None, self.info(user))
        self.assertEqual(result.blocked_code, 'identity_review')
        self.assertIn('en revisión', result.blocked_reason)
        with m.patch('smart_account.offer.subscribe_block', return_value='identity'), \
                m.patch('assistant.suggestions.waits_on_review', return_value=False):
            result = schema.Query.resolve_smart_account_offer(None, self.info(user))
        self.assertEqual(result.blocked_code, 'identity')
