from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import TestCase, RequestFactory, override_settings
from django.template.loader import render_to_string

from payment_accounts.monitoring import delivered_usd, dashboard_context, journeys
from payment_accounts.admin import InfiniaJourneyAdmin, AutomaticPayinAdmin
from payment_accounts.models import AutomaticPayin, InfiniaJourney
from ramps.models import RampTransaction
from ramps.metrics import deposit_volume_and_count, deposited_volume_by_provider, withdrawn_volume_and_count
from . import test_activity


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
    PAYMENT_BRIDGE_POLYGON_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class MonitoringTests(TestCase):
    quote = test_activity.ActivityTests.quote
    prepared = test_activity.ActivityTests.prepared
    credit = test_activity.ActivityTests.credit
    inbound = test_activity.ActivityTests.inbound
    incoming_arrived = test_activity.ActivityTests.incoming_arrived
    mint = test_activity.ActivityTests.mint
    outgoing = test_activity.ActivityTests.outgoing

    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        test_activity.ActivityTests.setUp(self)

    def request(self, **params):
        request = RequestFactory().get('/', params)
        request.user = SimpleNamespace(has_perm=lambda permission: True)
        return request

    def complete(self):
        j, _ = self.incoming_arrived()
        conversion = self.mint(j)
        # Settle records without invoking the external recovery/notification pipeline.
        type(conversion).objects.filter(pk=conversion.pk).update(status='COMPLETED')
        InfiniaJourney.objects.filter(pk=j.pk).update(wallet_conversion=conversion)
        return journeys().get(pk=j.pk)

    def test_provider_completion_without_mint_is_not_delivered(self):
        j, _ = self.incoming_arrived()
        self.assertEqual(delivered_usd(j), 0)
        context = dashboard_context(self.request())
        self.assertEqual(context['infinia_sections'][0]['counts']['awaiting_wallet_conversion'], 1)
        self.assertEqual(context['infinia_sections'][0]['rate'], 0)

    def test_completed_net_wallet_credit_and_template(self):
        j = self.complete()
        self.assertEqual(delivered_usd(j), Decimal('1.982'))
        context = dashboard_context(self.request(infinia_direction='to_wallet', infinia_country='PER'))
        self.assertEqual(len(context['infinia_sections']), 1)
        self.assertEqual(context['infinia_sections'][0]['volume'], Decimal('1.982'))
        html = render_to_string('admin/_infinia_dashboard.html', context)
        self.assertIn('Net wallet delivery', html)
        self.assertIn(str(j.internal_id)[:8], html)
        self.assertFalse(dashboard_context(self.request(infinia_country='MEX'))['infinia_sections'][0]['recent'])

    def test_permissions_and_read_only_admin(self):
        request = self.request()
        request.user.has_perm = lambda permission: False
        self.assertEqual(dashboard_context(request), {})
        from config.admin_dashboard import confio_admin_site
        for model, cls in [(InfiniaJourney, InfiniaJourneyAdmin), (AutomaticPayin, AutomaticPayinAdmin)]:
            admin = cls(model, confio_admin_site)
            self.assertFalse(admin.has_add_permission(request))
            self.assertFalse(admin.has_change_permission(request))
            self.assertFalse(admin.has_delete_permission(request))

    def test_admin_list_and_detail_render_for_staff(self):
        from config.admin_dashboard import confio_admin_site
        j = self.complete()
        user = self.owner.user
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])
        # Exercise real admin views/templates without production middleware
        # closing the transaction-scoped test database connection.
        request = self.request()
        request.user = user
        request.user.is_verified = lambda: True
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.messages.storage.fallback import FallbackStorage
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        admin = confio_admin_site._registry[InfiniaJourney]
        response = admin.changelist_view(request)
        response.render()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End-to-end status')
        response = admin.change_view(request, str(j.pk))
        response.render()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        response = confio_admin_site._registry[AutomaticPayin].changelist_view(request)
        response.render()
        self.assertEqual(response.status_code, 200)

    def test_unstarted_deposit_is_visible(self):
        entry = self.credit(self.local)
        AutomaticPayin.objects.update_or_create(entry=entry, defaults={'status': 'review', 'reason': 'test'})
        self.assertEqual(dashboard_context(self.request())['infinia_unstarted'], 1)

    def test_staff_view_permissions_gate_each_monitoring_surface(self):
        from config.admin_dashboard import confio_admin_site
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.messages.storage.fallback import FallbackStorage

        j = self.complete()
        payin, _ = AutomaticPayin.objects.update_or_create(
            entry=j.funding_credit, defaults={'status': 'started'})
        user = self.owner.user
        user.is_staff = True
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label='payment_accounts', codename='view_infiniajourney'))
        request = self.request()
        request.user = type(user).objects.get(pk=user.pk)
        request.user.is_verified = lambda: True
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        journey_admin = confio_admin_site._registry[InfiniaJourney]
        payin_admin = confio_admin_site._registry[AutomaticPayin]

        for response in (journey_admin.changelist_view(request),
                         journey_admin.change_view(request, str(j.pk))):
            response.render()
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'name="_save"')
        context = dashboard_context(request)
        self.assertIsNone(context['infinia_unstarted'])
        self.assertNotIn('Automatic deposit processing',
                         render_to_string('admin/_infinia_dashboard.html', context))
        with self.assertRaises(PermissionDenied):
            payin_admin.changelist_view(request)
        with self.assertRaises(PermissionDenied):
            payin_admin.change_view(request, str(payin.pk))

        user.user_permissions.add(Permission.objects.get(
            content_type__app_label='payment_accounts', codename='view_automaticpayin'))
        request.user = type(user).objects.get(pk=user.pk)
        request.user.is_verified = lambda: True
        context = dashboard_context(request)
        self.assertEqual(context['infinia_unstarted'], 0)
        self.assertIn('Automatic deposit processing',
                      render_to_string('admin/_infinia_dashboard.html', context))
        for response in (payin_admin.changelist_view(request),
                         payin_admin.change_view(request, str(payin.pk))):
            response.render()
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'name="_save"')

        # Even a superuser cannot mutate the monitoring records through admin.
        request.user.is_superuser = True
        request.method = 'POST'
        request._dont_enforce_csrf_checks = True
        for model_admin, record in ((journey_admin, j), (payin_admin, payin)):
            with self.assertRaises(PermissionDenied):
                model_admin.change_view(request, str(record.pk))
            with self.assertRaises(PermissionDenied):
                model_admin.delete_view(request, str(record.pk))

    def test_combined_volume_excludes_mirrors_outgoing_and_unfinished(self):
        from conversion.models import Conversion
        j = self.complete()
        conversions = Conversion.objects.bulk_create([
            Conversion(actor_user=self.owner.user, actor_type='user',
                       conversion_type='usdc_to_cusd', status='COMPLETED',
                       from_amount=10, to_amount=10)
            for _ in range(3)])
        records = [RampTransaction(provider=p, direction='on_ramp', status='COMPLETED',
                                   final_amount=10, final_currency='CUSD', conversion=conversion)
            for p, conversion in zip(('koywe', 'guardarian', 'transak'), conversions)]
        records += [RampTransaction(provider='koywe', direction='off_ramp', status='COMPLETED', final_amount=999),
            RampTransaction(provider='guardarian', direction='on_ramp', status='PROCESSING', final_amount=999),
            RampTransaction(provider='koywe', direction='on_ramp', status='COMPLETED', final_amount=999, final_currency='BTC')]
        RampTransaction.objects.bulk_create(records)
        totals = deposited_volume_by_provider()
        self.assertEqual(sum(totals.values()), Decimal('31.982'))
        j.money_flow.legacy_ramp_transaction = records[0]
        j.money_flow.save(update_fields=['legacy_ramp_transaction'])
        self.assertEqual(sum(deposited_volume_by_provider().values()), Decimal('21.982'))

    def test_deposit_count_follows_delivered_journeys(self):
        j = self.complete()
        self.assertEqual(deposit_volume_and_count(), (Decimal('1.982'), 1))
        type(j.wallet_conversion).objects.filter(pk=j.wallet_conversion_id).update(is_deleted=True)
        self.assertEqual(deposit_volume_and_count(), (Decimal(0), 0))

    def succeeded_payout(self, source_asset='USDT_BSC', amount=Decimal('25')):
        j, _ = self.outgoing()
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')
        type(j.money_flow).objects.filter(pk=j.money_flow_id).update(
            status='succeeded', source_asset=source_asset, source_amount=amount)
        return j

    def test_withdrawals_count_succeeded_dollar_payouts_once(self):
        j = self.succeeded_payout()
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('25'), 1))
        # The legacy ramp mirrored by this journey is the same withdrawal.
        mirror = RampTransaction.objects.create(provider='koywe', direction='off_ramp',
            status='COMPLETED', crypto_currency='USDT BSC', crypto_amount_actual=Decimal('25'))
        type(j.money_flow).objects.filter(pk=j.money_flow_id).update(legacy_ramp_transaction=mirror)
        self.assertEqual(withdrawn_volume_and_count(), (Decimal('25'), 1))
        # Deposits are untouched by a payout.
        self.assertEqual(deposit_volume_and_count(), (Decimal(0), 0))

    def test_withdrawals_skip_unfinished_and_non_dollar_payouts(self):
        j = self.succeeded_payout()
        flows = type(j.money_flow).objects.filter(pk=j.money_flow_id)
        for field, value in (('status', 'needs_review'), ('source_asset', 'COP')):
            with self.subTest(**{field: value}):
                flows.update(status='succeeded', source_asset='USDT_BSC')
                flows.update(**{field: value})
                self.assertEqual(withdrawn_volume_and_count(), (Decimal(0), 0))
        flows.update(status='succeeded', source_asset='USDT_BSC')
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='needs_review')
        self.assertEqual(withdrawn_volume_and_count(), (Decimal(0), 0))

    def test_deleted_conversion_is_not_counted(self):
        j = self.complete()
        type(j.wallet_conversion).objects.filter(pk=j.wallet_conversion_id).update(is_deleted=True)
        self.assertEqual(delivered_usd(journeys().get(pk=j.pk)), 0)
        self.assertEqual(deposited_volume_by_provider()['infinia'], 0)
        context = dashboard_context(self.request(infinia_direction='to_wallet'))
        self.assertEqual(context['infinia_sections'][0]['volume'], 0)

    def test_mint_fallback_and_unfinished_conversion_volume(self):
        j = self.complete()
        conversions = type(j.wallet_conversion).objects.filter(pk=j.wallet_conversion_id)
        conversions.update(net_amount_exact=None, to_amount=Decimal('1.75'))
        self.assertEqual(delivered_usd(journeys().get(pk=j.pk)), Decimal('1.75'))
        self.assertEqual(deposited_volume_by_provider()['infinia'], Decimal('1.75'))
        for status in ('PENDING', 'FAILED'):
            with self.subTest(status=status):
                conversions.update(status=status)
                self.assertEqual(delivered_usd(journeys().get(pk=j.pk)), 0)
                self.assertEqual(deposited_volume_by_provider()['infinia'], 0)

    def test_outgoing_rail_and_completed_fiat_are_not_deposit_volume(self):
        j, _ = self.outgoing()
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')
        type(j.money_flow).objects.filter(pk=j.money_flow_id).update(target_amount=30)
        section = dashboard_context(self.request(infinia_direction='to_bank'))['infinia_sections'][0]
        self.assertEqual(section['breakdown'][0]['rail'], 'ACCOUNT_PERU')
        self.assertEqual(section['breakdown'][0]['fiat_delivered'], Decimal('30'))
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)

    def test_completed_outgoing_missing_amount_is_unknown_not_zero(self):
        j, _ = self.outgoing()
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')
        type(j.money_flow).objects.filter(pk=j.money_flow_id).update(target_amount=None)
        section = dashboard_context(self.request(infinia_direction='to_bank'))['infinia_sections'][0]
        self.assertEqual(section['breakdown'][0]['fiat_unknown'], 1)
        self.assertEqual(section['breakdown'][0]['fiat_known'], 0)

    def test_refund_and_stalled_processing_are_distinct(self):
        from datetime import timedelta
        from django.utils import timezone
        j, bridge = self.outgoing()
        type(bridge).objects.filter(pk=bridge.pk).update(status='refunded')
        section = dashboard_context(self.request(infinia_direction='to_bank'))['infinia_sections'][0]
        self.assertEqual(section['counts']['refunded'], 1)
        self.assertEqual(section['counts'].get('processing', 0), 0)
        type(bridge).objects.filter(pk=bridge.pk).update(status='submitted')
        InfiniaJourney.objects.filter(pk=j.pk).update(updated_at=timezone.now()-timedelta(hours=2))
        section = dashboard_context(self.request(infinia_direction='to_bank'))['infinia_sections'][0]
        self.assertEqual(section['counts']['stalled'], 1)

    def test_savings_uses_usd_value_not_token_quantity(self):
        j = self.complete()
        j.wallet_conversion.conversion_type = 'to_savings'
        j.wallet_conversion.to_amount = Decimal('1.5')
        self.assertEqual(delivered_usd(j), Decimal('1.982'))
        j.wallet_conversion.net_amount_exact = None
        self.assertEqual(delivered_usd(j), 0)

    def test_cobre_requires_delivered_bridge_and_counts_actual_units(self):
        import uuid
        from payment_accounts.models import CobreJourney, MoneyFlow
        j, bridge = self.incoming_arrived()
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='fund',
            source_asset='COP', source_amount=10000, target_asset='USDT')
        CobreJourney.objects.create(money_flow=flow, request_id=uuid.uuid4(), confio_account=self.owner,
            direction='to_wallet', local_account=self.local, crypto_account=self.crypto,
            copco_account=self.local, bridge=bridge, minimum_fx_output=1, stage='completed')
        self.assertEqual(deposited_volume_by_provider()['cobre'], Decimal(bridge.actual_out_units)/10**18)
        type(bridge).objects.filter(pk=bridge.pk).update(status='refunded')
        self.assertEqual(deposited_volume_by_provider()['cobre'], 0)
