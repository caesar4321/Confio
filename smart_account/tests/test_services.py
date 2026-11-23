"""Offer, subscribe, designation and payment-rule rules (spec 10.3)."""
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import abi, offer, payouts, schema, services
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountPreparedAction, SmartAccountRule,
    SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from .base import BUILD, CUSD, FACTORY, VAULT, SmartAccountTestCase, WAD, vault_preview
from .base import INFINIA_SWITCHES, priced_payout


class OfferTests(SmartAccountTestCase):
    def test_prices_come_from_the_factory_and_annual_is_the_default(self):
        plans = {p['key']: p for p in offer.plans()}
        self.assertEqual([p['key'] for p in offer.plans()], ['annual', 'monthly'])
        self.assertEqual((plans['annual']['price_usd'], plans['monthly']['price_usd']), ('149.99', '14.99'))
        self.assertTrue(plans['annual']['is_default'])
        self.assertFalse(plans['monthly']['is_default'])
        self.assertEqual((plans['annual']['period_days'], plans['monthly']['period_days']), (365, 30))

    def test_factory_price_wins_over_settings_and_a_scheduled_change_is_shown(self):
        self.chain.fees['monthly'] = 1699 * 10 ** 16
        self.chain.scheduled['monthly'] = (1999 * 10 ** 16, 1_900_000_000)
        monthly = next(p for p in offer.plans() if p['key'] == 'monthly')
        self.assertEqual(monthly['price_usd'], '16.99')
        self.assertEqual(monthly['next_price_usd'], '19.99')
        self.assertIsNotNone(monthly['next_price_effective_at'])

    def test_settings_are_the_display_fallback_when_the_factory_is_unreadable(self):
        self.chain.fail.add('factory_fee_usd_wei')
        plans = {p['key']: p['price_usd'] for p in offer.plans()}
        self.assertEqual(plans, {'annual': '149.99', 'monthly': '14.99'})
        # ... but a subscription is never signed against the fallback.
        user = self.make_user('u')
        self.fund(VAULT, user.wallet, 500 * WAD)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_subscribe(self.viewer(user), 'annual',
                                       [{'asset_key': 'cusd_plus', 'units': 'max'}], True)
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_paid_offers_price_by_plan_and_can_subscribe(self):
        from users import paid_offers
        user = self.make_user('u')
        self.assertEqual(paid_offers.price('smart_account'), '14.99')
        self.assertEqual(paid_offers.price('smart_account', 'annual'), '149.99')
        self.assertIsNone(paid_offers.price('ia_plus', 'annual'))
        self.assertTrue(paid_offers.can_subscribe(user, is_employee=False, meta=BUILD))
        self.assertFalse(paid_offers.can_subscribe(user, is_employee=True, meta=BUILD))
        self.assertFalse(paid_offers.can_subscribe(user, is_employee=False, account_type='business', meta=BUILD))

    def test_no_new_waitlist_joins_for_someone_who_can_subscribe(self):
        from users.models_product_waitlist import ProductWaitlistEntry
        from users.product_waitlist_schema import JoinPaidOfferWaitlist
        user = self.make_user('u')
        with mock.patch('users.product_waitlist_schema._who', return_value=(user, False, 'personal')), \
                mock.patch('users.paid_offers.available', return_value=True), \
                mock.patch('users.funnel.emit_event'):
            refused = JoinPaidOfferWaitlist.mutate(None, self.info(user), product='smart_account', door='billeteras')
            self.assertFalse(refused.success)
            self.assertIn('ya está disponible', refused.error)
            self.assertEqual(ProductWaitlistEntry.objects.count(), 0)
            with override_settings(SMART_ACCOUNT_ALLOWED_USER_IDS=''):   # not in the canary: still the list
                joined = JoinPaidOfferWaitlist.mutate(None, self.info(user), product='smart_account', door='billeteras')
            self.assertTrue(joined.success, joined.error)
            self.assertEqual(ProductWaitlistEntry.objects.count(), 1)

    def test_who_may_subscribe(self):
        user = self.make_user('u')
        block = lambda **kw: offer.subscribe_block(user, personal_context=True, meta=BUILD, **kw)  # noqa: E731
        self.assertIsNone(block())
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            self.assertEqual(block(), 'disabled')
        with override_settings(SMART_ACCOUNT_FACTORY_ADDRESS=''):
            self.assertEqual(block(), 'disabled')
        with override_settings(SMART_ACCOUNT_ALLOWED_USER_IDS=''):
            self.assertEqual(block(), 'canary')
        with override_settings(SMART_ACCOUNT_ALLOWED_USER_IDS=f'7,{user.pk}'):
            self.assertIsNone(block())
        with override_settings(SMART_ACCOUNT_MIN_APP_VERSION=''):
            self.assertEqual(block(), 'build')
        self.assertEqual(offer.subscribe_block(user, personal_context=True,
                                               meta={'HTTP_X_CONFIO_VERSION': '5.9.9'}), 'build')
        self.assertEqual(offer.subscribe_block(user, personal_context=False, meta=BUILD), 'personal_only')
        self.unverified.add(user.pk)
        self.assertEqual(block(), 'identity')
        self.unverified.clear()
        self.holds[user.pk] = 'En revisión'
        self.assertEqual(block(), 'identity_hold')

    def test_offer_query(self):
        user = self.make_user('u')
        with mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False):
            result = schema.Query.resolve_smart_account_offer(None, self.info(user))
            self.assertTrue(result.available and result.can_subscribe)
            self.assertEqual(result.headline, 'automation_first')
            self.assertEqual([b.key for b in result.benefits], ['payments', 'investing', 'beneficiary', 'assistant'])
            self.assertEqual(len(result.disclosures), 6)
            self.assertEqual(result.payout_rails, [])
            self.assertEqual(result.min_first_deposit_usd, '14.99')
            self.assertFalse(result.investing_crypto_enabled)
            risk = ' '.join(result.beneficiary_risk_disclosure)
            self.assertIn('{name}', risk)
            self.assertIn('{days}', risk)
            self.assertEqual(risk.format(name='Ana', days=180).count('{'), 0)
            self.fund(VAULT, user.wallet, WAD)
            result = schema.Query.resolve_smart_account_offer(None, self.info(user))
            self.assertEqual(result.headline, 'beneficiary_first')
            self.assertEqual(result.benefits[0].key, 'beneficiary')


class SubscribeTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('u')
        self.fund(VAULT, self.user.wallet, 500 * WAD)

    def test_one_batch_creates_the_account_deposits_and_subscribes(self):
        batch = services.prepare_subscribe(self.viewer(self.user), 'annual',
                                           [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)
        target = self.chain.predict_address(self.user.wallet)
        self.assertEqual(batch.kind, 'smart_subscribe')
        self.assertEqual(batch.calls[0], abi.call(FACTORY, abi.encode_call('createAccount')))
        self.assertEqual(batch.calls[1], abi.transfer_call(VAULT, target, 200 * WAD))
        name, args = abi.decode_call(batch.calls[2]['data'])
        self.assertEqual((name, args[0], args[1]), ('subscribe', abi.PLAN_ANNUAL, self.chain.fees['annual']))
        self.assertEqual(batch.calls[2]['to'], target)
        self.assertEqual(batch.summary[0], 'Plan anual · US$149.99')
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertIn('disclosures_accepted_at', action.payload)
        # Nothing is mirrored from a prepare step.
        self.assertFalse(SmartAccount.objects.filter(owner_user=self.user).exists())
        from cusd_plus import sponsor_7702
        sponsor_7702.validate_policy(batch.calls, self.user, self.user.wallet, request_id=batch.request_id + '_a0')

    def test_refusals(self):
        viewer = self.viewer(self.user)
        code = lambda *a: self._code(services.prepare_subscribe, viewer, *a)  # noqa: E731
        self.assertEqual(code('annual', [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], False),
                         'disclosures_required')
        self.assertEqual(code('weekly', [], True), 'bad_plan')
        self.assertEqual(code('annual', [{'asset_key': 'cusd_plus', 'units': str(100 * WAD)}], True),
                         'first_fee_short')
        self.assertEqual(code('monthly', [{'asset_key': 'cusd_plus', 'units': str(900 * WAD)}], True),
                         'insufficient_balance')
        self.assertEqual(code('monthly', [{'asset_key': 'usdt', 'units': '5'}], True), 'bad_asset')
        self.make_account(self.user)
        self.assertEqual(code('monthly', [], True), 'already_subscribed')

    def _code(self, fn, *args):
        with self.assertRaises(services.PrepareError) as raised:
            fn(*args)
        return raised.exception.code

    def test_exits_are_not_gated_by_the_feature_flag(self):
        account = self.make_account(self.user)
        self.fund(VAULT, account.contract_address, 50 * WAD)
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            batch = services.prepare_withdraw(self.viewer(self.user), 'cusd_plus', 'max')
            self.assertEqual(abi.decode_call(batch.calls[0]['data'])[0], 'withdrawAll')
            services.prepare_cancel(self.viewer(self.user))
            self.assertEqual(self._code(services.prepare_deposit, self.viewer(self.user),
                                        [{'asset_key': 'cusd_plus', 'units': '1'}]), 'disabled')

    def test_first_deposit_preview_reads_the_wallet_before_the_account_exists(self):
        # The subscribe (fund) screen asks before there is any account: it
        # must see the personal wallet, never "no_account" shown as $0.
        self.fund(CUSD, self.user.wallet, 3 * WAD)
        self.assertEqual(self._code(services.move_preview, self.viewer(self.user), 'in'), 'no_account')
        preview = services.move_preview(self.viewer(self.user), 'in', require_account=False)
        self.assertIsNone(preview['own'])
        self.assertIn('cusd', [a.key for a in preview['included']])
        # Moving still needs the account.
        self.assertEqual(self._code(services.prepare_move_everything, self.viewer(self.user), 'in', 0),
                         'no_account')

    def test_move_everything_lists_and_splits(self):
        account = self.make_account(self.user)
        self.fund(CUSD, self.user.wallet, 3 * WAD)
        preview = services.move_preview(self.viewer(self.user), 'in')
        self.assertEqual([a.key for a in preview['included']], ['cusd_plus', 'cusd'])
        self.assertEqual(preview['batches'], 1)
        self.assertEqual({n['key'] for n in preview['notes']}, {'presale_locked', 'perps'})
        batch = services.prepare_move_everything(self.viewer(self.user), 'in', 0)
        self.assertEqual(batch.calls, [abi.transfer_call(VAULT, account.contract_address, 500 * WAD),
                                       abi.transfer_call(CUSD, account.contract_address, 3 * WAD)])
        self.assertEqual(self._code(services.prepare_move_everything, self.viewer(self.user), 'in', 1),
                         'bad_batch_index')
        self.fund(VAULT, account.contract_address, 7 * WAD)
        out = services.prepare_move_everything(self.viewer(self.user), 'out', 0)
        name, args = abi.decode_call(out.calls[0]['data'])
        self.assertEqual((name, [a.lower() for a in args[0]]), ('withdrawAll', [VAULT]))


class DesignationTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.account = self.make_account(self.owner)

    def _code(self, fn, *args, **kwargs):
        with self.assertRaises(services.PrepareError) as raised:
            fn(*args, **kwargs)
        return raised.exception.code

    def _designate(self, **kwargs):
        args = dict(beneficiary_handle='heir', window_days=180, disclosure_accepted=True)
        args.update(kwargs)
        return services.prepare_designation(self.viewer(self.owner), **args)

    def test_checks_at_designation(self):
        self.assertEqual(self._code(self._designate, disclosure_accepted=False), 'disclosure_required')
        self.assertEqual(self._code(self._designate, window_days=30), 'bad_window')
        self.assertEqual(self._code(self._designate, beneficiary_handle='nobody'), 'beneficiary_not_found')
        self.assertEqual(self._code(self._designate, beneficiary_handle='owner'), 'beneficiary_is_self')
        self.unverified.add(self.heir.pk)
        self.assertEqual(self._code(self._designate), 'beneficiary_unverified')
        self.unverified.clear()
        self.residence[self.heir.pk] = 'us_resident'
        self.assertEqual(self._code(self._designate), 'beneficiary_ineligible')
        self.residence.clear()
        self.holds[self.heir.pk] = 'hold'
        self.assertEqual(self._code(self._designate), 'beneficiary_on_hold')
        self.holds.clear()
        self.chain.inheritance = False
        self.assertEqual(self._code(self._designate), 'beneficiary_disabled')
        self.chain.inheritance = True
        with override_settings(SMART_ACCOUNT_BENEFICIARY_ENABLED=False):
            self.assertEqual(self._code(self._designate), 'beneficiary_disabled')
            with override_settings(SMART_ACCOUNT_BENEFICIARY_ALLOWED_USER_IDS=str(self.owner.pk)):
                self._designate()
        # Nothing was prepared or drafted by any refusal above.
        self.assertEqual(SmartAccountBeneficiary.objects.count(), 1)
        self.assertEqual(SmartAccountPreparedAction.objects.filter(kind='smart_beneficiary').count(), 1)

    def test_residence_check_blocks_us_residents(self):
        check = self.real_residence_check   # the fixture replaces services.residence_check
        with mock.patch('security.geo.country_of', return_value='US'):
            self.assertEqual(check(self.heir), 'us_resident')
        with mock.patch('security.geo.country_of', return_value='CO'), \
                mock.patch('security.geo.residence_country_for', return_value='USA'):
            self.assertEqual(check(self.heir), 'us_resident')
        with mock.patch('security.geo.country_of', return_value='CO'), \
                mock.patch('security.geo.residence_country_for', return_value='COL'):
            self.assertEqual(check(self.heir), 'ok')

    def test_designation_prepares_a_draft_with_the_disclosure_time(self):
        before = timezone.now()
        batch = self._designate()
        row = SmartAccountBeneficiary.objects.get()
        self.assertEqual(row.state, 'draft')
        self.assertTrue(row.verified_at_designation)
        self.assertEqual(row.residence_check, 'ok')
        self.assertGreaterEqual(row.disclosure_accepted_at, before)
        self.assertIsNone(row.designated_at)   # set from BeneficiaryNamed, not from the mutation
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[0].lower(), args[1]), ('setBeneficiary', self.heir.wallet, 180 * 86400))
        self.assertEqual(batch.kind, 'smart_beneficiary')

    def test_handle_may_be_a_full_phone_number(self):
        with mock.patch('users.phone_utils.find_user_by_phone', return_value=self.heir) as lookup:
            self.assertEqual(services.resolve_handle('+573001112233'), self.heir)
            lookup.assert_called_once_with('+573001112233')
            self.assertIsNone(services.resolve_handle('3001112233'))   # no calling code: never guessed
        self.assertEqual(services.resolve_handle('@Heir'), self.heir)

    def _pending(self):
        return SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=180 * 86400, state='pending_acceptance', designated_at=timezone.now(),
            expires_at=timezone.now() + timezone.timedelta(days=30), verified_at_designation=True)

    def test_checks_are_rerun_at_acceptance(self):
        row = self._pending()
        viewer = self.viewer(self.heir)
        batch = services.prepare_acceptance(viewer, str(row.designation_id))
        self.assertEqual(abi.decode_call(batch.calls[0]['data'])[0], 'acceptBeneficiary')
        row.refresh_from_db()
        self.assertIsNotNone(row.acceptance_checked_at)
        self.unverified.add(self.heir.pk)
        self.assertEqual(self._code(services.prepare_acceptance, viewer, str(row.designation_id)),
                         'beneficiary_unverified')
        self.unverified.clear()
        self.residence[self.heir.pk] = 'us_resident'
        self.assertEqual(self._code(services.prepare_acceptance, viewer, str(row.designation_id)),
                         'beneficiary_ineligible')
        self.residence.clear()
        stranger = self.make_user('stranger')
        self.assertEqual(self._code(services.prepare_acceptance, self.viewer(stranger), str(row.designation_id)),
                         'designation_not_found')
        SmartAccountBeneficiary.objects.filter(pk=row.pk).update(expires_at=timezone.now())
        self.assertEqual(self._code(services.prepare_acceptance, viewer, str(row.designation_id)),
                         'designation_expired')

    def test_decline_records_the_time_tells_the_owner_and_sends_nothing(self):
        row = self._pending()
        prepared = SmartAccountPreparedAction.objects.count()
        with mock.patch('smart_account.notifications.beneficiary_declined') as told:
            result = schema.DeclineBeneficiaryDesignation.mutate(
                None, self.info(self.heir), designation_id=str(row.designation_id))
        self.assertTrue(result.success)
        row.refresh_from_db()
        self.assertEqual(row.state, 'declined')
        self.assertIsNotNone(row.declined_at)
        told.assert_called_once()
        self.assertEqual(SmartAccountPreparedAction.objects.count(), prepared)
        again = schema.DeclineBeneficiaryDesignation.mutate(
            None, self.info(self.heir), designation_id=str(row.designation_id))
        self.assertEqual(again.error_code, 'designation_not_pending')

    def test_window_change_renames_the_current_beneficiary(self):
        row = self._pending()
        SmartAccountBeneficiary.objects.filter(pk=row.pk).update(state='active', accepted_at=timezone.now())
        batch = services.prepare_window_change(self.viewer(self.owner), 365)
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[0].lower(), args[1]), ('setBeneficiary', self.heir.wallet, 365 * 86400))


PAYOUTS_ON = dict(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True,
                  **INFINIA_SWITCHES)


class PayoutRuleTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        from payment_accounts.models import PayoutDestination
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.personal = self.account.owner_account
        self.destination = PayoutDestination.objects.create(
            confio_account=self.personal, provider='infinia', kind='bank_account', country='MEX', asset='MXN',
            label='CLABE · 002180000000004322', holder_name='Ana P.', status='active',
            details={'type': 'CLABE', 'clabe': '002180000000004322', 'reference': 'Confio'},
            provider_data={'method_id': 'mx_clabe', 'validation': {
                'id': 'v1', 'status': 'VERIFIED', 'holder_name': 'Ana P.',
                'checked_at': timezone.now().isoformat()}})
        for p in (mock.patch('payment_accounts.local_money.verification_state', return_value='verified'),
                  mock.patch('payment_accounts.local_money.checked_recently', return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        priced = priced_payout()
        priced.start()
        self.addCleanup(priced.stop)
        self.face = mock.patch('payment_accounts.services.require_outgoing_face', return_value='face-key-1')
        self.face_mock = self.face.start()
        self.addCleanup(self.face.stop)
        self.applies = mock.patch('security.face_step_up.step_up_applies', return_value=True)
        self.applies.start()
        self.addCleanup(self.applies.stop)

    def _prepare(self, **kwargs):
        args = dict(rule_id=None, payout_method_id=str(self.destination.internal_id), amount_usd='50.00',
                    frequency='monthly')
        args.update(kwargs)
        return services.prepare_payout_rule(self.viewer(self.owner), **args)

    def _code(self, **kwargs):
        with self.assertRaises(services.PrepareError) as raised:
            self._prepare(**kwargs)
        return raised.exception.code

    def test_a_rail_not_confirmed_for_unattended_payouts_is_not_offered(self):
        self.assertEqual(offer.payout_rails(), [])
        self.assertEqual(self._code(), 'payout_not_available')
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe', **INFINIA_SWITCHES):
            self.assertEqual(offer.payout_rails(), [])   # listed but the adapter is unverified
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='br_pix', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True,
                               **INFINIA_SWITCHES):
            self.assertEqual(self._code(), 'payout_rail_not_available')
            methods = schema.Query.resolve_smart_account_payout_methods(None, self.info(self.owner))
            self.assertEqual([(m.rail, m.available) for m in methods], [('mx_clabe', False)])

    @override_settings(**PAYOUTS_ON)
    def test_standing_authorization_is_created_with_face_and_bound(self):
        batch = self._prepare()
        authorization = SmartAccountStandingAuthorization.objects.get()
        self.assertEqual(authorization.face_action_key, 'face-key-1')
        self.assertEqual(authorization.binding_hash,
                         payouts.binding_hash(self.destination, Decimal('50.00'), 'monthly'))
        self.assertNotEqual(authorization.binding_hash,
                            payouts.binding_hash(self.destination, Decimal('51.00'), 'monthly'))
        self.assertNotEqual(authorization.binding_hash,
                            payouts.binding_hash(self.destination, Decimal('50.00'), 'weekly'))
        namespace, identifier, payload = self.face_mock.call_args[0][1:4]
        self.assertEqual(namespace, 'smart_account_payout_rule')
        # Bound to the terms AND this authorization row (a fresh Face per rule).
        self.assertEqual(identifier, payouts.face_identifier(authorization.binding_hash, authorization.pk))
        self.assertEqual(payload['destination'], str(self.destination.internal_id))
        rule = SmartAccountRule.objects.get()
        self.assertEqual((rule.state, rule.active, rule.standing_authorization), ('draft', False, authorization))
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual(name, 'createRule')
        self.assertEqual(args[0][0], abi.RULE_PAYOUT)
        self.assertEqual('0x' + bytes(args[0][5]).hex(), rule.payout_ref)
        self.assertEqual(int(args[0][4], 16), 0)   # no address is ever bound on-chain for a payout

    @override_settings(**PAYOUTS_ON)
    def test_no_authorization_without_face(self):
        self.face_mock.return_value = ''
        self.assertEqual(self._code(), 'face_required')
        from payment_accounts.services import PaymentAccountError
        self.face_mock.side_effect = PaymentAccountError('Confirma con Confío Face')
        self.assertEqual(self._code(), 'face_required')
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())
        self.assertFalse(SmartAccountRule.all_objects.exists())

    @override_settings(**PAYOUTS_ON)
    def test_a_payout_method_that_is_not_the_viewers_is_refused(self):
        other = self.make_user('other')
        self.make_account(other)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_payout_rule(self.viewer(other), None, str(self.destination.internal_id),
                                         '50.00', 'monthly')
        self.assertEqual(raised.exception.code, 'payout_method_not_found')
        self.assertEqual(self._code(payout_method_id='not-a-uuid'), 'payout_method_not_found')

    def _onchain_rule(self):
        self._prepare()
        rule = SmartAccountRule.objects.get()
        rule.state, rule.active, rule.onchain_id = 'onchain', True, 1
        rule.scheduled_for = rule.next_run_at = timezone.now()
        rule.save()
        return rule

    @override_settings(**PAYOUTS_ON)
    def test_an_edited_or_deleted_method_deactivates_its_rule(self):
        rule = self._onchain_rule()
        self.assertIsNone(payouts.authorization_problem(rule))
        self.destination.details = {'type': 'CLABE', 'clabe': '012180000000001234', 'reference': 'Confio'}
        self.destination.save()
        rule.refresh_from_db()
        self.assertEqual(payouts.authorization_problem(rule), 'destination_changed')
        with mock.patch('smart_account.notifications.rule_deactivated') as told:
            self.assertEqual(payouts.deactivate_changed_rules(), 1)
        rule.refresh_from_db()
        self.assertFalse(rule.active)
        self.assertEqual(rule.deactivated_reason, 'destination_changed')
        told.assert_called_once()
        SmartAccountRule.objects.filter(pk=rule.pk).update(active=True)
        self.destination.status = 'closed'
        self.destination.save()
        rule.refresh_from_db()
        self.assertEqual(payouts.authorization_problem(rule), 'destination_deleted')

    @override_settings(**PAYOUTS_ON)
    def test_a_run_outside_the_rules_limits_is_skipped_never_forced(self):
        rule = self._onchain_rule()
        SmartAccountStandingAuthorization.objects.filter(pk=rule.standing_authorization_id).update(
            reference_fx_rate=Decimal('4000'))
        rule.refresh_from_db()
        run = SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=rule.scheduled_for)
        plan = payouts.PayoutPlan(deposit_address='0x' + '44' * 20, min_usdt_out=1, bridge_cost_bps=400)

        def opened(rule, run, usdt, exit_=None, window=None):
            # A cUSD+ rule (this account's dollar): the adapter sizes its
            # deposit from the exact exit it is handed.
            plan.min_usdt_out = usdt
            return plan
        with mock.patch.object(payouts.InfiniaAdapter, 'open', side_effect=opened), \
                mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=vault_preview()):
            with self.assertRaises(payouts.PayoutSkip) as raised:
                payouts.plan_run(rule, run, 49 * WAD)
            self.assertEqual(raised.exception.code, 'bridge_cost_above_limit')
            plan.bridge_cost_bps, plan.fx_rate = 50, Decimal('3500')
            with self.assertRaises(payouts.PayoutSkip) as raised:
                payouts.plan_run(rule, run, 49 * WAD)
            self.assertEqual(raised.exception.code, 'fx_rate_below_limit')
            plan.fx_rate = Decimal('3990')
            planned = payouts.plan_run(rule, run, 49 * WAD)
            self.assertEqual(planned.deposit_address, '0x' + '44' * 20)
            # The Infinia rail's cUSD+ run carries the exact exit too.
            self.assertEqual((planned.min_usdt_out, planned.gross_wei),
                             (payouts.net_for_gross(planned.gross_wei, 90), planned.gross_wei))
            self.assertLessEqual(planned.gross_wei, 50 * WAD)

    @override_settings(**PAYOUTS_ON)
    def test_the_unverified_provider_path_refuses_to_run(self):
        rule = self._onchain_rule()
        run = SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=rule.scheduled_for)
        # A rail with no adapter (Bre-B): refused even if something offered it.
        rule.payout_rail = 'co_breb'
        with self.assertRaises(payouts.PayoutSkip) as raised, \
                mock.patch('smart_account.payouts.rail_ready', return_value=True), \
                mock.patch('smart_account.payouts.authorization_problem', return_value=None), \
                mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=vault_preview()):
            payouts.plan_run(rule, run, 49 * WAD)
        self.assertEqual(raised.exception.code, 'provider_path_unverified')
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS=''):
            with self.assertRaises(payouts.PayoutSkip) as raised:
                payouts.plan_run(rule, run, 49 * WAD)
            self.assertEqual(raised.exception.code, 'payouts_disabled')
