from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models_rail_waitlist import LocalRailWaitlistEntry, parse_rail_id
from users.rail_waitlist_schema import JoinLocalRailWaitlist


def _info(user=None):
    return SimpleNamespace(context=SimpleNamespace(user=user, META={}))


class LocalRailWaitlistTests(TestCase):
    """The waitlist is people, not taps, and it never shrinks on its own the
    way the 90-day funnel events do — for "Próximamente" rails and for rails
    refused for the person's nationality alike."""

    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', firebase_uid='uid-ana')
        self.luis = User.objects.create_user(username='luis', firebase_uid='uid-luis')

    def join(self, user, rail_id, **kwargs):
        return JoinLocalRailWaitlist.mutate(None, _info(user), rail_id=rail_id, **kwargs)

    def test_a_probe_join_is_coming_soon_by_default(self):
        self.join(self.ana, 'send_ve_pagomovil')
        self.assertEqual(LocalRailWaitlistEntry.objects.get().kind, 'coming_soon')

    def test_a_nationality_blocked_rail_joins_by_its_server_method_id(self):
        with patch('users.rail_waitlist_schema._is_nationality_blocked', return_value=True):
            result = self.join(self.ana, 'co_breb_receive', kind='nationality_blocked')
        self.assertTrue(result.success)
        entry = LocalRailWaitlistEntry.objects.get()
        self.assertEqual((entry.rail_id, entry.kind, entry.direction, entry.country),
                         ('co_breb_receive', 'nationality_blocked', 'receive', 'CO'))

    def test_the_blocked_label_needs_the_server_to_agree(self):
        # Someone the server does not block cannot inflate the blocked count,
        # and a failed check is a refusal, not a guess.
        with patch('users.rail_waitlist_schema._is_nationality_blocked', return_value=False):
            self.assertFalse(self.join(self.ana, 'mx_clabe', kind='nationality_blocked').success)
        with patch('users.rail_waitlist_schema._is_nationality_blocked', side_effect=RuntimeError('no jwt')):
            self.assertFalse(self.join(self.ana, 'mx_clabe', kind='nationality_blocked').success)
        self.assertEqual(LocalRailWaitlistEntry.objects.count(), 0)

    def test_the_blocked_check_reads_the_same_rail_status_as_the_menu(self):
        from payment_accounts import local_money
        from users import rail_waitlist_schema
        owner = object()
        with patch('payment_accounts.local_money_schema._owner', return_value=owner), \
                patch('payment_accounts.local_money_schema._identity', return_value=None), \
                patch.object(local_money, 'rail_status') as rail_status:
            rail_status.return_value = ('unavailable', 'infinia_nationality_not_supported', None)
            self.assertTrue(rail_waitlist_schema._is_nationality_blocked(_info(self.ana), 'mx_clabe'))
            rail_status.return_value = ('unavailable', 'provider_disabled', None)
            self.assertFalse(rail_waitlist_schema._is_nationality_blocked(_info(self.ana), 'mx_clabe'))
            rail_status.return_value = ('live', '', None)
            self.assertFalse(rail_waitlist_schema._is_nationality_blocked(_info(self.ana), 'mx_clabe'))
        self.assertIs(rail_status.call_args.args[0], owner)
        self.assertEqual(rail_status.call_args.args[2], local_money.METHODS['mx_clabe'])

    def test_each_kind_only_accepts_its_own_catalog(self):
        # A method id is not a probe id, a probe id is not a method id, and
        # an unknown kind names nothing.
        self.assertFalse(self.join(self.ana, 'co_breb_receive').success)
        self.assertFalse(self.join(self.ana, 'send_co_breb', kind='nationality_blocked').success)
        self.assertFalse(self.join(self.ana, 'not_a_method', kind='nationality_blocked').success)
        self.assertFalse(self.join(self.ana, 'send_co_breb', kind='vip').success)
        self.assertEqual(LocalRailWaitlistEntry.objects.count(), 0)

    def test_the_migration_snapshot_matches_the_live_method_catalog(self):
        import importlib
        from payment_accounts.local_money import METHODS
        migration = importlib.import_module('users.migrations.0051_local_rail_waitlist')
        self.assertEqual(migration.BLOCKED_METHODS,
                         {m.id: (m.direction, m.iso2) for m in METHODS.values()})

    def test_joining_twice_keeps_one_entry(self):
        self.assertTrue(self.join(self.ana, 'send_ve_pagomovil').success)
        self.assertTrue(self.join(self.ana, 'send_ve_pagomovil').success)
        self.assertEqual(LocalRailWaitlistEntry.objects.count(), 1)

    def test_entry_keeps_the_rails_direction_and_country(self):
        self.join(self.ana, 'receive_ec_bank')
        entry = LocalRailWaitlistEntry.objects.get()
        self.assertEqual((entry.direction, entry.country), ('receive', 'EC'))

    def test_send_and_receive_are_separate_entries(self):
        self.join(self.ana, 'send_ve_pagomovil')
        self.join(self.ana, 'receive_ve_pagomovil')
        self.join(self.luis, 'send_ve_pagomovil')
        self.assertEqual(LocalRailWaitlistEntry.objects.filter(rail_id='send_ve_pagomovil').count(), 2)
        self.assertEqual(LocalRailWaitlistEntry.objects.filter(rail_id='receive_ve_pagomovil').count(), 1)

    def test_anonymous_callers_cannot_join(self):
        self.assertFalse(self.join(None, 'send_ec_bank').success)
        self.assertEqual(LocalRailWaitlistEntry.objects.count(), 0)

    def test_malformed_or_unknown_rail_ids_are_refused(self):
        # `send_zz_a1` is well formed but not a rail the app lists: accepting
        # it would let a script mint unlimited rows.
        for bad in ['', 'pagomovil', 'send_ven_pagomovil', 'transfer_ve_x', 'send_VE_pagomovil',
                    'send_ve_' + 'x' * 30, 'send_zz_a1', 'receive_ve_bank']:
            self.assertIsNone(parse_rail_id(bad), bad)
            self.assertFalse(self.join(self.ana, bad).success)
        self.assertEqual(LocalRailWaitlistEntry.objects.count(), 0)

    def test_backfill_turns_past_confirmations_into_entries(self):
        import importlib
        from django.apps import apps
        from users.models_analytics import FunnelEvent
        migration = importlib.import_module('users.migrations.0051_local_rail_waitlist')
        for stage in ('tap', 'confirmed', 'confirmed'):
            FunnelEvent.objects.create(event_name='local_rail_interest', user=self.ana,
                                       properties={'rail': 'send_co_breb', 'stage': stage})
        # A bare tap is curiosity, not a sign-up.
        FunnelEvent.objects.create(event_name='local_rail_interest', user=self.luis,
                                   properties={'rail': 'send_mx_clabe', 'stage': 'tap'})
        # A session-only confirmation has nobody to notify; a junk id is skipped.
        FunnelEvent.objects.create(event_name='local_rail_interest', session_id='s1',
                                   properties={'rail': 'send_ec_bank', 'stage': 'confirmed'})
        FunnelEvent.objects.create(event_name='local_rail_interest', user=self.luis,
                                   properties={'rail': 'not a rail', 'stage': 'confirmed'})
        # A nationality-blocked confirmation joins too, by its method id.
        FunnelEvent.objects.create(event_name='local_rail_blocked_interest', user=self.luis,
                                   properties={'rail': 'co_breb_receive', 'stage': 'confirmed'})
        FunnelEvent.objects.create(event_name='local_rail_blocked_interest', user=self.ana,
                                   properties={'rail': 'mx_clabe', 'stage': 'tap'})
        migration.backfill_from_confirmed_opt_ins(apps, None)
        self.assertEqual(
            sorted(LocalRailWaitlistEntry.objects.values_list(
                'user__username', 'rail_id', 'kind', 'direction', 'country')),
            [('ana', 'send_co_breb', 'coming_soon', 'send', 'CO'),
             ('luis', 'co_breb_receive', 'nationality_blocked', 'receive', 'CO')],
        )

    def test_backfill_keeps_the_earliest_confirmation_date(self):
        import importlib
        from datetime import timedelta
        from django.apps import apps
        from django.utils import timezone
        from users.models_analytics import FunnelEvent
        migration = importlib.import_module('users.migrations.0051_local_rail_waitlist')
        first = timezone.now() - timedelta(days=40)
        for when in (first + timedelta(days=5), first, first + timedelta(days=9)):
            event = FunnelEvent.objects.create(event_name='local_rail_interest', user=self.ana,
                                               properties={'rail': 'send_ve_pagomovil', 'stage': 'confirmed'})
            FunnelEvent.objects.filter(pk=event.pk).update(created_at=when)
        migration.backfill_from_confirmed_opt_ins(apps, None)
        self.assertEqual(LocalRailWaitlistEntry.objects.get().created_at, first)
