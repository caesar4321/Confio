from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from cusd_plus import perps_flow

T0 = datetime(2026, 10, 27, 11, 0, tzinfo=dt_timezone.utc)


def ms(when):
    return int(when.timestamp() * 1000)


class CostEventsTests(SimpleTestCase):
    def test_every_payment_keeps_its_own_cumulative_event(self):
        # Two funding payments the same UTC day: a snapshot between them is
        # valued with the first only, so neither may replace the other.
        position = SimpleNamespace(created_at=T0 - timedelta(days=1), market=SimpleNamespace(coin='BTC'),
                                   wallet='0xabc')
        funding = [{'time': ms(T0), 'delta': {'coin': 'BTC', 'usdc': '-5'}},
                   {'time': ms(T0 + timedelta(hours=2)), 'delta': {'coin': 'BTC', 'usdc': '-1'}}]
        fills = [{'time': ms(T0 + timedelta(hours=2)), 'coin': 'BTC', 'fee': '0.5'}]
        with mock.patch.object(perps_flow.hyperliquid, 'user_fills_by_time', return_value=fills), \
                mock.patch.object(perps_flow.hyperliquid, 'user_funding', return_value=funding):
            events = perps_flow._cost_events(position)
        self.assertEqual([(e['funding_paid'], e['fees']) for e in events],
                         [('5', '0'), ('6', '0.5')])
        self.assertEqual(datetime.fromisoformat(events[0]['at']), T0)
        self.assertEqual(Decimal(events[-1]['funding_paid']), Decimal('6'))
