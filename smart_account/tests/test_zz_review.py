from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from smart_account import relay_purchases
from smart_account.models import SmartRelayPurchase
from smart_account.tests import test_hands_off_purchases as purchase_tests


class ResumeReplyStateTests(purchase_tests.ChatTests):
    def test_resumed_cap_row_is_not_withdrawn(self):
        from inbox.schema import get_or_create_support_conversation
        from inbox.models import SupportMessage
        conv = get_or_create_support_conversation(self.user, self.personal, None)
        SupportMessage.objects.create(conversation=conv, sender_type='USER', message_type='TEXT', body='sí')
        (_d, _r, extra), _s = self.answer('no_rule', suggested=Decimal('50'))
        row = SmartRelayPurchase.objects.get()
        self.assertEqual(row.conversation_id, conv.pk)
        SupportMessage.objects.create(conversation=conv, sender_type='AGENT', message_type='TEXT', body='x',
                                      metadata={'actions': extra['actions']})
        with mock.patch('smart_account.tasks.run_relay_purchase.apply_async'), \
                self.captureOnCommitCallbacks(execute=True):
            relay_purchases.resume(self.user, row.internal_id)
        SmartRelayPurchase.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        try:
            relay_purchases.run(row.pk)
        except relay_purchases.Later:
            pass                       # the rule just signed is not live yet: it waits, never withdrawn
        row.refresh_from_db()
        self.assertNotEqual(row.status, 'cancelled')
        self.assertEqual(row.status, 'pending')
