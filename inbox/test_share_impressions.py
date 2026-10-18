"""Share-sheet impressions: what the sheet was offered, on which build, and
how it ended, so "did they see it?" is answerable from data."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from graphql import GraphQLResolveInfo

from . import activity_share, share_impressions
from .activity_share import STOCK_BUY
from .models import ActivityShareImpression
from .schema import Query, RecordActivityShareDismissal, ShareActivityIntent
from .test_activity_share import buy_activity
from .test_community import CommunityTestBase, make_user

ANDROID_524 = {'HTTP_X_CONFIO_PLATFORM': 'android', 'HTTP_X_CONFIO_VERSION': '5.2.4'}


def info_for(user, meta=None):
    return Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=user, META=meta or {}))


class SheetPreviewTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.member = make_user()
        self.snap = activity_share.Snapshot(
            STOCK_BUY, {k: v for k, v in buy_activity().items() if k != 'show_amount'})
        ctx = patch('inbox.schema.get_context_models', side_effect=lambda info: (info.context.user, None, None, {}))
        ctx.start()
        self.addCleanup(ctx.stop)

    def preview(self, meta=ANDROID_524, snap=True, reference='0xabc', allow_pending=True, block=None):
        found = (None, self.snap, False) if snap else None
        with patch.object(activity_share, 'preview_activity', return_value=found), \
                patch('inbox.community.posting_block', return_value=block):
            return Query().resolve_shareable_activity(
                info_for(self.member, meta), group='stock', reference=reference, allow_pending=allow_pending)

    def test_a_sheet_preview_records_build_and_offer(self):
        self.assertIsNotNone(self.preview())
        row = ActivityShareImpression.objects.get(user=self.member, group='stock', reference='0xabc')
        self.assertEqual((row.platform, row.app_version, row.offered, row.fetches, row.outcome),
                         ('android', '5.2.4', True, 1, ''))

    def test_refetches_update_one_row(self):
        self.preview()
        self.preview(meta={'HTTP_X_CONFIO_PLATFORM': 'android', 'HTTP_X_CONFIO_VERSION': '5.2.5'})
        row = ActivityShareImpression.objects.get(user=self.member)
        self.assertEqual((row.fetches, row.app_version), (2, '5.2.5'))

    def test_nothing_to_preview_is_recorded_as_a_quiet_close(self):
        self.assertIsNone(self.preview(snap=False))
        row = ActivityShareImpression.objects.get(user=self.member)
        self.assertEqual((row.offered, row.block_code), (False, 'unavailable'))

    def test_blocked_member_is_not_offered_but_rules_required_is(self):
        self.preview(reference='0x1', block='not_verified')
        self.preview(reference='0x2', block='rules_required')
        rows = {r.reference: r for r in ActivityShareImpression.objects.filter(user=self.member)}
        self.assertEqual((rows['0x1'].offered, rows['0x1'].block_code), (False, 'not_verified'))
        self.assertEqual((rows['0x2'].offered, rows['0x2'].block_code), (True, 'rules_required'))

    def test_only_the_sheet_call_is_recorded(self):
        with patch.object(activity_share, 'find_activity', return_value=None):
            Query().resolve_shareable_activity(info_for(self.member), group='stock', reference='0xabc')
        self.assertFalse(ActivityShareImpression.objects.exists())

    def test_unknown_headers_are_stored_blank(self):
        self.preview(meta={'HTTP_X_CONFIO_PLATFORM': 'web', 'HTTP_X_CONFIO_VERSION': 'banana'})
        row = ActivityShareImpression.objects.get(user=self.member)
        self.assertEqual((row.platform, row.app_version), ('', ''))

    def test_a_failed_write_never_breaks_the_sheet(self):
        with patch.object(ActivityShareImpression.objects, 'filter', side_effect=RuntimeError('db')):
            self.assertIsNotNone(self.preview())


class OutcomeTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.member = make_user()
        share_impressions.record_preview(self.member, 'stock', '0xabc', ANDROID_524, offered=True)

    def row(self):
        return ActivityShareImpression.objects.get(user=self.member, group='stock', reference='0xabc')

    def test_dismissal_is_recorded(self):
        result = RecordActivityShareDismissal.mutate(None, info_for(self.member), group='stock', reference='0xabc')
        self.assertTrue(result.success)
        self.assertEqual(self.row().outcome, 'dismissed')
        self.assertIsNotNone(self.row().closed_at)

    def test_compartir_marks_it_shared_and_a_later_close_keeps_it(self):
        with patch('inbox.schema.get_context_models', return_value=(self.member, None, None, {})), \
                patch.object(activity_share, 'share_or_schedule', return_value=('scheduled', None)):
            result = ShareActivityIntent.mutate(None, info_for(self.member), group='stock', reference='0xabc')
        self.assertTrue(result.success)
        self.assertEqual(self.row().outcome, 'shared')
        share_impressions.record_outcome(self.member, 'stock', '0xabc', 'dismissed')
        self.assertEqual(self.row().outcome, 'shared')

    def test_a_refused_share_is_not_marked_shared(self):
        error = activity_share.ActivityShareError('links', 'No links')
        with patch('inbox.schema.get_context_models', return_value=(self.member, None, None, {})), \
                patch.object(activity_share, 'share_or_schedule', side_effect=error):
            ShareActivityIntent.mutate(None, info_for(self.member), group='stock', reference='0xabc')
        self.assertEqual(self.row().outcome, '')

    def test_a_failed_outcome_write_leaves_the_transaction_usable(self):
        from django.db import DatabaseError, transaction
        with transaction.atomic():
            with patch('django.db.models.query.QuerySet.update', side_effect=DatabaseError('timeout')):
                share_impressions.record_outcome(self.member, 'stock', '0xabc', 'dismissed')
            # The share that follows still reads and writes.
            self.assertEqual(self.row().outcome, '')

    def test_someone_else_cannot_close_my_impression(self):
        other = make_user()
        RecordActivityShareDismissal.mutate(None, info_for(other), group='stock', reference='0xabc')
        self.assertEqual(self.row().outcome, '')
