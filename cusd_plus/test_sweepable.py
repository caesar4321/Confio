"""What may be auto-minted, and what must be left alone.

Nothing on BSC escrows a prepared send or an in-flight off-ramp — both are
just database rows — so this subtraction is the only thing stopping the
savings auto-mint from moving funds out from under them. It is also why the
balance must be read FRESH: the cached one is display-grade (30s TTL with a
last-known fallback), and minting a stale figure either misses a deposit or
reverts for insufficient funds.
"""
import json
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.core.cache import cache

from cusd_plus import vault

WAD = 10 ** 18
ADDR = '0x' + 'ab' * 20


def _send(amount, kind='send_usdt'):
    return SimpleNamespace(amount=Decimal(str(amount)),
                           bsc_calls_json=json.dumps({'kind': kind}))


def _qs(rows):
    """A queryset stub supporting .only(...)[:n] and iteration."""
    q = mock.Mock()
    q.only.return_value = rows
    q.exclude.return_value = q
    return q


class _Rows(list):
    """A .only() result that also answers .iterator(), like a real queryset.

    The pending-send scan reads row-wise (no slice) so a capped scan can't
    silently stop reserving; a plain list stub no longer models it.
    """

    def iterator(self, chunk_size=None):
        return iter(list(self))


def _sum(rows, field):
    """What the DB would hand back from .aggregate(Sum(field)) — None if empty."""
    total = sum((getattr(row, field) for row in rows), Decimal(0))
    return total if rows else None


class ReservedUsdtTests(SimpleTestCase):
    def _reserved(self, sends=(), ramps=(), sagas=(), buys=()):
        with mock.patch('send.models.SendTransaction.objects') as s_objs, \
             mock.patch('ramps.models.RampTransaction.objects') as r_objs, \
             mock.patch('conversion.models.Conversion.objects') as c_objs, \
             mock.patch('presale.models.PresalePurchase.objects') as p_objs:
            s_objs.filter.return_value.exclude.return_value.only.return_value = _Rows(sends)
            # Everything except the sends is summed in the database: a capped
            # scan stopped reserving past the cap, so those reads are
            # aggregates now (Codex audit 2026-08-02, P2).
            r_objs.filter.return_value.aggregate.return_value = {
                's': _sum(ramps, 'crypto_amount_estimated'),
            }
            c_objs.filter.return_value.aggregate.return_value = {
                's': _sum(sagas, 'to_amount'),
            }
            p_objs.filter.return_value.aggregate.return_value = {
                's': _sum(buys, 'cusd_amount'),
            }
            return vault.reserved_usdt_wei(SimpleNamespace(id=1), ADDR)

    def test_nothing_committed_reserves_nothing(self):
        self.assertEqual(self._reserved(), 0)

    def test_a_prepared_usdt_send_is_reserved(self):
        self.assertEqual(self._reserved(sends=[_send('2.50')]), int(Decimal('2.5') * WAD))

    def test_a_vault_funded_send_reserves_nothing(self):
        # send_redeem spends VAULT shares, not wallet USDT.
        self.assertEqual(self._reserved(sends=[_send('2.50', 'send_redeem')]), 0)

    def test_an_in_flight_offramp_is_reserved(self):
        order = SimpleNamespace(crypto_amount_estimated=Decimal('10'))
        self.assertEqual(self._reserved(ramps=[order]), 10 * WAD)

    def test_an_in_flight_saga_is_reserved(self):
        # Its delivered USDT belongs to that mint, not to a deposit sweep —
        # otherwise a saga whose own mint just failed gets swept out from
        # under itself and strands.
        saga = SimpleNamespace(to_amount=Decimal('3'))
        self.assertEqual(self._reserved(sagas=[saga]), 3 * WAD)

    def test_a_prepared_presale_buy_is_reserved(self):
        # The batch spends wallet USDT, so an auto-mint must not get there
        # first — even before the buy is signed.
        buy = SimpleNamespace(cusd_amount=Decimal('4'))
        self.assertEqual(self._reserved(buys=[buy]), 4 * WAD)

    def test_reservations_accumulate(self):
        total = self._reserved(
            sends=[_send('1')],
            ramps=[SimpleNamespace(crypto_amount_estimated=Decimal('2'))],
            sagas=[SimpleNamespace(to_amount=Decimal('3'))],
            buys=[SimpleNamespace(cusd_amount=Decimal('4'))])
        self.assertEqual(total, 10 * WAD)

    def test_an_unreadable_reservation_raises_rather_than_vanishing(self):
        # Swallowing this would silently make committed funds spendable.
        with mock.patch('send.models.SendTransaction.objects') as s_objs:
            s_objs.filter.side_effect = RuntimeError('db down')
            with self.assertRaises(RuntimeError):
                vault.reserved_usdt_wei(SimpleNamespace(id=1), ADDR)

    def test_no_address_reserves_nothing(self):
        self.assertEqual(vault.reserved_usdt_wei(SimpleNamespace(id=1), ''), 0)


class SweepableUsdtTests(SimpleTestCase):
    def _sweepable(self, balance, reserved):
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=balance) as bal, \
             mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=reserved):
            out = vault.sweepable_usdt_wei(SimpleNamespace(id=1), ADDR)
        return out, bal

    def test_balance_minus_reservations(self):
        out, _ = self._sweepable(10 * WAD, 4 * WAD)
        self.assertEqual(out, 6 * WAD)

    def test_exact_one_dollar_stays_raw_and_spendable(self):
        out, _ = self._sweepable(WAD, 0)
        self.assertEqual(out, 0)

    def test_one_micro_dollar_buffer_is_safe_to_mint(self):
        safe = WAD + 10 ** 12
        out, _ = self._sweepable(safe, 0)
        self.assertEqual(out, safe)

    def test_reservation_that_leaves_one_dollar_prevents_mint(self):
        out, _ = self._sweepable(2 * WAD, WAD)
        self.assertEqual(out, 0)

    def test_never_negative(self):
        out, _ = self._sweepable(1 * WAD, 5 * WAD)
        self.assertEqual(out, 0)

    def test_balance_is_read_FRESH(self):
        # The cached read is display-grade; minting it reverts or misses.
        _, bal = self._sweepable(WAD, 0)
        self.assertEqual(bal.call_args.kwargs.get('fresh'), True)


class SweepableResolverTests(SimpleTestCase):
    def test_any_failure_reports_zero_not_the_balance(self):
        from cusd_plus.schema import _sweepable_usdt_usd
        with mock.patch('cusd_plus.vault.sweepable_usdt_wei',
                        side_effect=RuntimeError('rpc down')):
            self.assertEqual(_sweepable_usdt_usd(SimpleNamespace(id=1), ADDR), 0.0)

    def test_no_address_is_zero(self):
        from cusd_plus.schema import _sweepable_usdt_usd
        self.assertEqual(_sweepable_usdt_usd(SimpleNamespace(id=1), ''), 0.0)

    def test_arrival_amount_uses_observed_value_and_floors_to_public_precision(self):
        from cusd_plus.tasks import _usdt_amount_decimal
        self.assertEqual(
            _usdt_amount_decimal(1_999_999_999_999_999_999),
            Decimal('1.999999'),
        )

    def test_arrival_persists_observed_amount_for_leg_c(self):
        from cusd_plus.tasks import _mark_bridge_arrived
        conv = mock.Mock(to_amount=Decimal('1.100000'))
        now = object()
        log = {
            'data': hex(10**18 + 999_999_999_999),
            'transactionHash': '0xabc',
        }
        with mock.patch(
                'cusd_plus.unified.sync_unified_from_cusd_plus_conversion') as sync:
            _mark_bridge_arrived(conv, log, now)
        self.assertEqual(conv.to_amount, Decimal('1.000000'))
        self.assertEqual(conv.status, 'DEST_ARRIVED')
        conv.save.assert_called_once_with(update_fields=[
            'to_amount', 'status', 'dest_arrived_at',
            'bridge_arrival_tx', 'updated_at',
        ])
        sync.assert_called_once_with(conv)


class DeliveredAsUsdtTests(SimpleTestCase):
    """A saga the mint gate will never allow must reach a TERMINAL state."""

    @staticmethod
    def _delivery_rows(*rows):
        qs = mock.Mock()
        qs.filter.return_value = qs
        qs.order_by.return_value = qs
        qs.__iter__ = mock.Mock(return_value=iter(rows))
        return qs

    def test_refused_holder_closes_their_in_flight_sagas(self):
        from cusd_plus.tasks import mark_saga_delivered_as_usdt
        row_a, row_b = mock.Mock(), mock.Mock()
        qs = self._delivery_rows(row_a, row_b)
        with mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('django.db.transaction.atomic', return_value=nullcontext()), \
             mock.patch('cusd_plus.unified.sync_unified_from_cusd_plus_conversion') as sync:
            convs.select_for_update.return_value = qs
            self.assertEqual(mark_saga_delivered_as_usdt(ADDR), 2)
        for row in (row_a, row_b):
            self.assertEqual(row.status, 'DELIVERED_USDT')
            row.save.assert_called_once_with(update_fields=['status', 'updated_at'])
            sync.assert_any_call(row)

    def test_amount_refusal_closes_only_one_matching_saga(self):
        from cusd_plus.tasks import mark_saga_delivered_as_usdt
        row = mock.Mock()
        qs = self._delivery_rows(row)
        qs.__getitem__ = mock.Mock(return_value=qs)
        with mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('django.db.transaction.atomic', return_value=nullcontext()), \
             mock.patch('cusd_plus.unified.sync_unified_from_cusd_plus_conversion'):
            convs.select_for_update.return_value = qs
            self.assertEqual(mark_saga_delivered_as_usdt(ADDR, WAD), 1)
        qs.filter.assert_any_call(to_amount=Decimal('1.000000'))
        qs.__getitem__.assert_called_once_with(slice(None, 1, None))

    def test_legacy_fallback_does_not_close_a_second_matching_saga(self):
        from cusd_plus.tasks import mark_saga_delivered_as_usdt
        cache.clear()
        first = mock.Mock()
        qs = self._delivery_rows(first)
        qs.__getitem__ = mock.Mock(return_value=qs)
        with mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('django.db.transaction.atomic', return_value=nullcontext()), \
             mock.patch('cusd_plus.unified.sync_unified_from_cusd_plus_conversion'):
            convs.select_for_update.return_value = qs
            self.assertEqual(mark_saga_delivered_as_usdt(
                ADDR, WAD, refusal_source='sponsored'), 1)
            convs.reset_mock()
            self.assertEqual(mark_saga_delivered_as_usdt(ADDR, WAD), 0)
            convs.select_for_update.assert_not_called()
        cache.clear()

    def test_equal_concurrent_refusals_keep_one_marker_per_fallback(self):
        from cusd_plus.tasks import _change_floor_refusal_marker
        key = f'test:mint_floor:{ADDR}:{WAD}'
        cache.clear()
        self.assertTrue(_change_floor_refusal_marker(key, 1))
        self.assertTrue(_change_floor_refusal_marker(key, 1))
        self.assertTrue(_change_floor_refusal_marker(key, -1))
        self.assertTrue(_change_floor_refusal_marker(key, -1))
        self.assertFalse(_change_floor_refusal_marker(key, -1))
        cache.clear()

    def test_delivered_usdt_is_terminal(self):
        from conversion.models import Conversion
        self.assertEqual(Conversion.TRANSITIONS['DELIVERED_USDT'], set())
        self.assertIn('DELIVERED_USDT', Conversion.TRANSITIONS['DEST_ARRIVED'])

    def test_it_is_not_counted_as_in_flight(self):
        from conversion.models import Conversion
        self.assertNotIn('DELIVERED_USDT', Conversion.IN_FLIGHT_STATUSES)

    def test_failure_never_breaks_the_refusal_path(self):
        from cusd_plus.tasks import mark_saga_delivered_as_usdt
        with mock.patch('conversion.models.Conversion.objects') as convs, \
             mock.patch('django.db.transaction.atomic', return_value=nullcontext()):
            convs.select_for_update.side_effect = RuntimeError('db down')
            self.assertEqual(mark_saga_delivered_as_usdt(ADDR), 0)
