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
