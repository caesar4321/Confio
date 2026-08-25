from datetime import datetime, timezone
from unittest import TestCase

from users.rail_interest_metrics import build_rail_interest_metrics


class RailInterestMetricsTests(TestCase):
    def test_counts_distinct_people_per_rail_and_across_headline_totals(self):
        now = datetime.now(timezone.utc)
        rows = [
            # Repeated events from one user count once on the rail.
            {
                'event_name': 'local_rail_interest',
                'properties': {'rail': 'send_ar_alias', 'direction': 'send', 'stage': 'tap'},
                'country': 'AR', 'created_at': now, 'user_id': 1, 'session_id': '',
            },
            {
                'event_name': 'local_rail_interest',
                'properties': {'rail': 'send_ar_alias', 'direction': 'send', 'stage': 'tap'},
                'country': 'AR', 'created_at': now, 'user_id': 1, 'session_id': '',
            },
            {
                'event_name': 'local_rail_interest',
                'properties': {'rail': 'send_ar_alias', 'direction': 'send', 'stage': 'confirmed'},
                'country': 'AR', 'created_at': now, 'user_id': 1, 'session_id': '',
            },
            # A confirmation proves the tap even when its tap event was lost.
            {
                'event_name': 'local_rail_interest',
                'properties': {'rail': 'send_ar_alias', 'direction': 'send', 'stage': 'confirmed'},
                'country': 'GT', 'created_at': now, 'user_id': 2, 'session_id': '',
            },
            # The same user on another rail counts on that row, but only once
            # in the headline's distinct-person total.
            {
                'event_name': 'receive_rail_interest',
                'properties': {'rail': 'polygon', 'stage': 'tap'},
                'country': 'AR', 'created_at': now, 'user_id': 1, 'session_id': '',
            },
            # Pre-authenticated probes can fall back to a stable session.
            {
                'event_name': 'receive_rail_interest',
                'properties': {'rail': 'polygon', 'stage': 'tap'},
                'country': 'BO', 'created_at': now, 'user_id': None, 'session_id': 'session-1',
            },
            {
                'event_name': 'receive_rail_interest',
                'properties': {'rail': 'polygon', 'stage': 'tap'},
                'country': 'BO', 'created_at': now, 'user_id': None, 'session_id': 'session-1',
            },
            # Without either identity, a row cannot safely represent a person.
            {
                'event_name': 'receive_rail_interest',
                'properties': {'rail': 'polygon', 'stage': 'tap'},
                'country': 'MX', 'created_at': now, 'user_id': None, 'session_id': '',
            },
        ]

        rail_interest, totals = build_rail_interest_metrics(rows)
        by_rail = {row['rail']: row for row in rail_interest}

        self.assertEqual(by_rail['send_ar_alias']['taps'], 2)
        self.assertEqual(by_rail['send_ar_alias']['confirmed'], 2)
        self.assertEqual(by_rail['send_ar_alias']['conversion_pct'], 100.0)
        self.assertEqual(by_rail['send_ar_alias']['countries'], 'AR, GT')
        self.assertEqual(by_rail['polygon']['direction'], 'receive')
        self.assertEqual(by_rail['polygon']['taps'], 2)
        self.assertEqual(by_rail['polygon']['confirmed'], 0)
        self.assertEqual(totals, {
            'taps': 3,
            'confirmed': 2,
            'rails': 2,
            'unidentified_events': 1,
        })
