from datetime import datetime, timezone as tz
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from payment_accounts.infinia_maintenance import accrue, quoted_charges, reserve, reconcile
from payment_accounts.infinia_fees import FeePricingError
from payment_accounts.models import FinancialAccount, InfiniaMaintenanceCharge, MoneyFlow
from . import test_infinia_journeys as helpers


@override_settings(INFINIA_MAINTENANCE_FEES_ENABLED=True, INFINIA_PASS_THROUGH_FEE_COUNTRIES='PE,MX',
    INFINIA_ACCOUNT_FEE_TIER=0, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True)
class MaintenanceTests(TestCase):
    def setUp(self):
        helpers.JourneyTests.setUp(self)
        self.clock = mock.patch('payment_accounts.infinia_maintenance.timezone.now',
                                return_value=datetime(2026,9,24,tzinfo=tz.utc)).start()

    def flow(self):
        return MoneyFlow.objects.create(confio_account=self.owner,kind='fund',status='created',
                                        source_asset='PEN',source_amount='10',target_asset='USDT_BSC')

    def test_one_charge_per_local_account_month_and_no_crypto_charge(self):
        accrue(self.owner); accrue(self.owner)
        rows = list(InfiniaMaintenanceCharge.objects.all())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].account_id,self.local.pk)
        self.assertEqual(rows[0].amount_usd,Decimal('0.10'))
        self.assertEqual(str(rows[0].period),'2026-09-01')

    def _opening(self, status, amount, paid=None):
        """An activation for self.local; `paid` = (amount, status) of its payment."""
        from payment_accounts.models import AccountActivation
        from send.models import SendTransaction
        payment = None
        if paid:
            payment = SendTransaction.objects.create(sender_user=self.owner.user, sender_address='0x' + '1' * 40,
                recipient_address='0x' + '2' * 40, recipient_type='external', amount=paid[0], token_type='CUSD',
                status=paid[1])
        AccountActivation.objects.filter(confio_account=self.owner, country=self.local.country,
                                         asset=self.local.asset).delete()
        return AccountActivation.objects.create(confio_account=self.owner, country=self.local.country,
            asset=self.local.asset, method_id='x', status=status, amount=amount, payment=payment)

    def _reset(self):
        from payment_accounts.models import InfiniaMaintenanceState
        InfiniaMaintenanceCharge.objects.all().delete()
        InfiniaMaintenanceState.objects.all().delete()

    def test_account_paid_at_the_old_one_time_price_owes_no_maintenance(self):
        self._opening('active', Decimal('10.00'), paid=(Decimal('10.00'), 'CONFIRMED'))
        accrue(self.owner)
        self.assertEqual(InfiniaMaintenanceCharge.objects.count(), 0)
        self.assertEqual(quoted_charges(self.owner)[1], Decimal('0'))

    def test_only_a_confirmed_old_price_payment_exempts(self):
        cases = [
            ('active', Decimal('1.00'), (Decimal('1.00'), 'CONFIRMED')),     # today's price
            ('active', Decimal('0.00'), None),                              # free opening
            ('active', Decimal('10.00'), None),                             # amount alone proves nothing
            ('active', Decimal('10.00'), (Decimal('10.00'), 'FAILED')),     # never actually paid
            ('payment_pending', Decimal('10.00'), (Decimal('10.00'), 'SUBMITTED')),
            ('legacy', Decimal('0.00'), None),
        ]
        for status, amount, paid in cases:
            self._reset()
            self._opening(status, amount, paid)
            accrue(self.owner)
            self.assertEqual(InfiniaMaintenanceCharge.objects.count(), 1, (status, amount, paid))

    def test_months_invoiced_before_the_old_price_was_paid_are_dropped_once_it_is(self):
        from send.models import SendTransaction
        row = self._opening('payment_pending', Decimal('10.00'), paid=(Decimal('10.00'), 'SUBMITTED'))
        self.assertEqual(quoted_charges(self.owner)[1], Decimal('0.10'))      # open, not yet paid
        SendTransaction.objects.filter(pk=row.payment_id).update(status='CONFIRMED')
        type(row).objects.filter(pk=row.pk).update(status='active')
        ids, cost = quoted_charges(self.owner)
        self.assertEqual((ids, cost), ([], Decimal('0')))
        self.assertEqual(InfiniaMaintenanceCharge.objects.count(), 0)
        self.clock.return_value = datetime(2026,12,10,tzinfo=tz.utc)
        self.assertEqual(quoted_charges(self.owner)[1], Decimal('0'))         # and none later

    def test_exempt_account_keeps_a_month_already_inside_a_signed_flow(self):
        from send.models import SendTransaction
        row = self._opening('payment_pending', Decimal('10.00'), paid=(Decimal('10.00'), 'SUBMITTED'))
        ids, _ = quoted_charges(self.owner)
        flow = self.flow()
        reserve({'maintenance_ids': ids}, flow)
        SendTransaction.objects.filter(pk=row.payment_id).update(status='CONFIRMED')
        type(row).objects.filter(pk=row.pk).update(status='active')
        accrue(self.owner)
        self.assertEqual(InfiniaMaintenanceCharge.objects.filter(reserved_flow=flow).count(), 1)

    def test_missing_months_accrue_once_and_closure_stops_next_cycle(self):
        accrue(self.owner)
        self.clock.return_value = datetime(2026,11,10,tzinfo=tz.utc)
        accrue(self.owner)
        self.assertEqual(InfiniaMaintenanceCharge.objects.count(),3)
        self.local.status='closed'; self.local.save()
        accrue(self.owner)
        self.clock.return_value = datetime(2026,12,10,tzinfo=tz.utc)
        accrue(self.owner)
        self.assertEqual(InfiniaMaintenanceCharge.objects.count(),3)
        self.local.status='active'; self.local.save()
        accrue(self.owner); accrue(self.owner)
        self.assertEqual(InfiniaMaintenanceCharge.objects.count(),4)

    def test_reserved_charge_cannot_be_collected_by_a_second_flow(self):
        ids, cost = quoted_charges(self.owner)
        self.assertEqual(cost,Decimal('0.10'))
        first, second = self.flow(), self.flow()
        snapshot={'maintenance_ids':ids}
        reserve(snapshot,first)
        self.assertEqual(quoted_charges(self.owner),([],Decimal(0)))
        with self.assertRaises(FeePricingError): reserve(snapshot,second)
        first.metadata={'infinia_fee':snapshot}
        from types import SimpleNamespace
        journey=SimpleNamespace(direction='to_wallet',money_flow=first)
        reconcile(journey,{'transaction_hash':'0x'+'aa'*32})
        reconcile(journey,{'transaction_hash':'0x'+'aa'*32})
        self.assertEqual(InfiniaMaintenanceCharge.objects.get().collected_tx_hash,'0x'+'aa'*32)
        reconcile(journey,None)
        row=InfiniaMaintenanceCharge.objects.get()
        self.assertEqual(row.collected_tx_hash,'')
        self.assertEqual(row.reserved_flow_id,first.pk)

    def test_new_account_in_same_month_adds_only_its_own_maintenance(self):
        accrue(self.owner)
        FinancialAccount.objects.create(provider_profile=self.local.provider_profile,
            provider_account_id='second',country='MEX',asset='MXN',status='active',ownership_structure='provider_named')
        self.assertEqual(quoted_charges(self.owner)[1],Decimal('0.20'))

    def test_disabling_new_accrual_does_not_forgive_existing_invoice(self):
        from payment_accounts.infinia_fee_policy import price
        accrue(self.owner)
        with override_settings(INFINIA_MAINTENANCE_FEES_ENABLED=False):
            fee = price(self.local, 'to_wallet')
        self.assertEqual(Decimal(fee['maintenance_usd']), Decimal('0.10'))
        self.assertEqual(Decimal(fee['total_usd']), Decimal('1.10'))
