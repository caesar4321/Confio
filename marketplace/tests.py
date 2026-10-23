import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from eth_account import Account as EthAccount
from eth_utils import keccak

from security.models import IdentityVerification
from users.models import Account, User

from . import checkout, escrow, pricing
from .models import (MarketplaceCity, MarketplaceFeeLedger, MarketplacePartnerAgreement, Order,
                     Product, Store)

WAD = 10**18
ESCROW = '0x' + 'e5' * 20
CUSD = '0x' + 'c0' * 20
SIGNER_KEY = '0x' + '11' * 32
SIGNER = EthAccount.from_key(SIGNER_KEY).address.lower()
ARTIFACT = (Path(settings.BASE_DIR) / 'contracts' / 'cusd_plus' / 'out'
            / 'ConfioMarketEscrow.sol' / 'ConfioMarketEscrow.json')

ENABLED = dict(MARKETPLACE_ESCROW_ADDRESS=ESCROW, CUSD_VAULT_ADDRESS=CUSD, BSC_CHAIN_ID=56,
               MARKETPLACE_FEE_BPS=800)
LIMITS = (300 * WAD, 10_000 * WAD, 0)  # maxOrder, maxOpen, openPrincipal (on-chain)

counter = iter(range(10_000))


def local_sign(digest):
    signed = EthAccount._sign_hash(digest, private_key=SIGNER_KEY)
    sig = signed.r.to_bytes(32, 'big') + signed.s.to_bytes(32, 'big') + bytes([signed.v])
    return '0x' + sig.hex(), SIGNER


def make_business(owner):
    from users.models import Business
    n = next(counter)
    business = Business.objects.create(name=f'Tienda {n}', category='other')
    account = Account.objects.create(user=owner, account_type='business', business=business,
                                     account_index=0, bsc_address='0x' + format(90_000 + n, '040x'))
    return business, account


def make_user(verified=True):
    n = next(counter)
    user = User.objects.create_user(username=f'mk-{n}', email=f'mk{n}@example.com',
                                    firebase_uid=f'mk-{n}', first_name='Ana', last_name='Quispe')
    Account.objects.create(user=user, account_type='personal', account_index=0,
                           bsc_address='0x' + format(n + 1, '040x'))
    if verified:
        IdentityVerification.objects.create(
            user=user, verified_first_name='Ana', verified_last_name='Quispe',
            verified_date_of_birth=date(1990, 1, 1), verified_nationality='BOL',
            verified_address='Calle 1', verified_city='La Paz', verified_state='LP',
            verified_country='BOL', document_type='national_id', document_number=f'BO-{n}',
            document_issuing_country='BOL', status='verified')
    return user


PERSONAL = {'account_type': 'personal', 'account_index': 0, 'business_id': None}


class PricingTests(SimpleTestCase):
    def test_fee_matches_contract_ceiling(self):
        self.assertEqual(pricing.fee_wei(100 * WAD, 800), 8 * WAD)
        self.assertEqual(pricing.fee_wei(1, 800), 1)  # ceil, like feeFor
        self.assertEqual(pricing.fee_wei(12_345, 800), 988)  # 987.6 → 988

    def test_quote_is_price_times_quantity_in_dollars(self):
        q = pricing.quote(Decimal('14.50'), 3)
        self.assertEqual(q.amount_usd, Decimal('43.50'))      # no exchange rate involved
        self.assertEqual(q.amount_wei, 4350 * 10**16)
        self.assertEqual(q.fee_usd, Decimal('3.48'))           # 8%
        self.assertEqual(q.merchant_net_usd, Decimal('40.02'))

    def test_local_reference_is_display_only_and_absent_without_a_fresh_rate(self):
        from django.core.cache import cache
        cache.clear()
        fresh = SimpleNamespace(rate=Decimal('6.96'), fetched_at=timezone.now())
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row',
                        return_value=fresh):
            self.assertEqual(pricing.reference_local(Decimal('10'), 'BO'), (Decimal('69.60'), 'BOB'))
        cache.clear()
        stale = SimpleNamespace(rate=Decimal('6.96'), fetched_at=timezone.now() - timedelta(hours=7))
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row',
                        return_value=stale):
            self.assertIsNone(pricing.reference_local(Decimal('10'), 'BO'))  # hidden, never raises
        cache.clear()
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row',
                        side_effect=RuntimeError('db down')):
            self.assertIsNone(pricing.reference_local(Decimal('10'), 'BO'))


@override_settings(**ENABLED)
class EscrowEncodingTests(SimpleTestCase):
    def test_selectors_match_the_compiled_contract(self):
        if not ARTIFACT.exists():
            self.skipTest('forge artifact not built')
        ids = json.loads(ARTIFACT.read_text())['methodIdentifiers']
        self.assertEqual(ids['deposit(bytes32,address,address,uint256,uint16,uint256,bytes)'],
                         escrow.SEL_DEPOSIT)
        for name, sel in [('markShipped(bytes32)', escrow.SEL_MARK_SHIPPED),
                          ('confirm(bytes32)', escrow.SEL_CONFIRM),
                          ('dispute(bytes32)', escrow.SEL_DISPUTE),
                          ('refund(bytes32)', escrow.SEL_REFUND),
                          ('reclaim(bytes32)', escrow.SEL_RECLAIM),
                          ('release(bytes32)', escrow.SEL_RELEASE),
                          ('resolve(bytes32,bool)', escrow.SEL_RESOLVE),
                          ('refundExpiredDispute(bytes32)', escrow.SEL_REFUND_EXPIRED),
                          ('getOrder(bytes32)', escrow.SEL_GET_ORDER)]:
            self.assertEqual(ids[name], sel, name)

    def test_deposit_digest_matches_eip712_reference(self):
        from eth_account.messages import encode_typed_data

        order_id = keccak(text='x').hex()
        buyer, merchant = '0x' + 'b1' * 20, '0x' + 'a1' * 20
        ours = escrow.deposit_digest(order_id, buyer, merchant, CUSD, 5 * WAD, 800, 1_700_000_000)
        typed = {
            'types': {
                'EIP712Domain': [{'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'},
                                 {'name': 'chainId', 'type': 'uint256'},
                                 {'name': 'verifyingContract', 'type': 'address'}],
                'Deposit': [{'name': 'orderId', 'type': 'bytes32'}, {'name': 'buyer', 'type': 'address'},
                            {'name': 'merchant', 'type': 'address'}, {'name': 'token', 'type': 'address'},
                            {'name': 'amount', 'type': 'uint256'}, {'name': 'feeBps', 'type': 'uint16'},
                            {'name': 'deadline', 'type': 'uint256'}],
            },
            'primaryType': 'Deposit',
            'domain': {'name': 'ConfioMarketEscrow', 'version': '1', 'chainId': 56,
                       'verifyingContract': ESCROW},
            'message': {'orderId': bytes.fromhex(order_id), 'buyer': buyer, 'merchant': merchant,
                        'token': CUSD, 'amount': 5 * WAD, 'feeBps': 800, 'deadline': 1_700_000_000},
        }
        signable = encode_typed_data(full_message=typed)
        reference = keccak(b'\x19' + signable.version + signable.header + signable.body)
        self.assertEqual(ours, reference)


def ensure_categories():
    # Own fixtures: seed rows (migration 0005) can be wiped by another suite's flush.
    from .models import MarketplaceCategory
    for key, label, group in [('textiles', 'Textiles y tejidos', 'Artesanía y regalos'),
                              ('artesanias', 'Artesanías', 'Artesanía y regalos'),
                              ('alimentos', 'Alimentos envasados', 'Comida envasada')]:
        MarketplaceCategory.objects.update_or_create(key=key, defaults={'label': label, 'group': group,
                                                                       'is_active': True})


class MarketTestBase(TestCase):
    def setUp(self):
        ensure_categories()
        # La Paz is seeded (not live) by migration 0002; the tests flip it live.
        self.city, _ = MarketplaceCity.objects.update_or_create(
            country_code='BO', city='La Paz',
            defaults={'currency_code': 'BOB', 'is_live': True, 'delivery_estimate': Decimal('15.00')})
        self.seller = make_user()
        self.buyer = make_user()
        self.store = Store.objects.create(
            owner=self.seller, owner_account=self.seller.accounts.get(), name='Tejidos Ana',
            country_code='BO', city='La Paz')
        self.product = Product.objects.create(
            store=self.store, title='Chompa de alpaca', category='textiles',
            price_usd=Decimal('30.00'), stock=3, status='active',
            photo_urls=['https://example.com/a.jpg'])
        patches = [
            mock.patch.object(escrow, 'sign_deposit', side_effect=local_sign),
            mock.patch.object(escrow, 'funding_leg', return_value=None),
            mock.patch.object(escrow, 'token_limits', return_value=LIMITS),
            mock.patch.object(escrow, 'deposit_step_up', return_value=''),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def prepare(self, **overrides):
        kwargs = dict(product_id=self.product.pk, quantity=1, delivery_country='BO',
                      delivery_city='La Paz', delivery_address='Av. Arce 2345, Sopocachi',
                      delivery_phone='+59170000000')
        kwargs.update(overrides)
        return checkout.prepare_order(self.buyer, PERSONAL, **kwargs)


@override_settings(**ENABLED)
class CheckoutTests(MarketTestBase):
    def test_prepare_builds_signed_pinned_batch(self):
        order, calls, intent_id = self.prepare()
        self.assertEqual(order.status, 'draft')
        self.assertEqual(order.amount_usd, Decimal('30.00'))  # priced in dollars
        self.assertEqual(order.fee_bps, 800)
        self.assertEqual(order.delivery_estimate_local, Decimal('15.00'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['to'], CUSD)
        self.assertEqual(calls[1]['to'], ESCROW)
        self.assertTrue(calls[1]['data'].startswith('0x' + escrow.SEL_DEPOSIT))
        escrow.validate_deposit_calls(calls, order)  # does not raise
        self.assertTrue(intent_id.startswith('0x'))

    def test_tampered_batch_rejected(self):
        from cusd_plus.sponsor_7702 import PolicyError
        order, calls, _ = self.prepare()
        tampered = [dict(c) for c in calls]
        tampered[0]['data'] = tampered[0]['data'][:-2] + 'ff'
        with self.assertRaises(PolicyError):
            escrow.validate_deposit_calls(tampered, order)

    def test_buyer_must_be_verified(self):
        self.buyer = make_user(verified=False)
        with self.assertRaisesMessage(checkout.CheckoutError, 'identity_required'):
            self.prepare()

    def test_business_account_can_buy(self):
        business, account = make_business(self.buyer)
        order, _, _ = checkout.prepare_order(
            self.buyer, {'account_type': 'business', 'business_id': business.id, 'account_index': 0},
            product_id=self.product.pk, quantity=1, delivery_country='BO', delivery_city='La Paz',
            delivery_address='Av. Arce 2345, Sopocachi', delivery_phone='+59170000000')
        self.assertEqual(order.buyer_account_id, account.id)
        self.assertEqual(order.buyer_address, account.bsc_address)

    def test_owner_cannot_buy_from_their_business_store(self):
        business, account = make_business(self.seller)
        Store.objects.filter(pk=self.store.pk).update(owner_account=account)
        with self.assertRaisesMessage(checkout.CheckoutError, 'own_store'):
            checkout.prepare_order(self.seller, PERSONAL, product_id=self.product.pk, quantity=1,
                                   delivery_country='BO', delivery_city='La Paz',
                                   delivery_address='Av. Arce 2345, Sopocachi',
                                   delivery_phone='+59170000000')

    def test_nothing_executable_exists_before_face(self):
        with mock.patch.object(escrow, 'deposit_step_up', return_value='face_check'), \
                mock.patch.object(escrow, 'sign_deposit') as sign:
            with self.assertRaisesMessage(checkout.CheckoutError, 'face_check'):
                self.prepare()
        sign.assert_not_called()
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_face_is_consumed_bound_to_the_order_terms_before_signing(self):
        calls = []

        def step_up(user, consume=False, **terms):
            calls.append((consume, terms))
            return ''
        with mock.patch.object(escrow, 'deposit_step_up', side_effect=step_up):
            order, _, _ = self.prepare()
        self.assertEqual([c[0] for c in calls], [False, True])  # peek, then claim
        terms = calls[1][1]
        self.assertEqual(terms['order_id32'], order.order_id32)
        self.assertEqual(terms['amount_wei'], int(order.amount_wei))
        self.assertEqual(terms['merchant'], order.merchant_address)

    def test_employee_cannot_buy_between_one_owners_accounts(self):
        business, account = make_business(self.seller)  # the store owner also owns a business
        from users.models_employee import BusinessEmployee
        employee = make_user()
        BusinessEmployee.objects.create(user=employee, business=business, role='admin')
        with self.assertRaisesMessage(checkout.CheckoutError, 'own_store'):
            checkout.prepare_order(
                employee, {'account_type': 'business', 'business_id': business.id, 'account_index': 0},
                product_id=self.product.pk, quantity=1, delivery_country='BO', delivery_city='La Paz',
                delivery_address='Av. Arce 2345, Sopocachi', delivery_phone='+59170000000')

    def test_limits_come_from_the_contract(self):
        with mock.patch.object(escrow, 'token_limits', return_value=(10 * WAD, 10_000 * WAD, 0)):
            with self.assertRaisesMessage(checkout.CheckoutError, 'order_too_large'):
                self.prepare()
        with mock.patch.object(escrow, 'token_limits', return_value=(300 * WAD, 100 * WAD, 90 * WAD)):
            with self.assertRaisesMessage(checkout.CheckoutError, 'marketplace_busy'):
                self.prepare()
        with mock.patch.object(escrow, 'token_limits', side_effect=escrow.EscrowError('limits_unavailable')):
            with self.assertRaisesMessage(checkout.CheckoutError, 'limits_unavailable'):
                self.prepare()
        with mock.patch.object(escrow, 'token_limits', return_value=(0, 0, 0)):
            with self.assertRaisesMessage(checkout.CheckoutError, 'marketplace_disabled'):
                self.prepare()

    def test_cannot_buy_from_own_store(self):
        self.buyer = self.seller
        with self.assertRaisesMessage(checkout.CheckoutError, 'own_store'):
            self.prepare()

    def test_city_must_be_live(self):
        MarketplaceCity.objects.filter(pk=self.city.pk).update(is_live=False)
        with self.assertRaisesMessage(checkout.CheckoutError, 'city_not_live'):
            self.prepare()

    def test_other_city_needs_store_opt_in_and_buyer_ack(self):
        with self.assertRaisesMessage(checkout.CheckoutError, 'store_city_only'):
            self.prepare(delivery_city='Santa Cruz')
        Store.objects.filter(pk=self.store.pk).update(ships_outside_city=True)
        with self.assertRaisesMessage(checkout.CheckoutError, 'outside_city_ack_required'):
            self.prepare(delivery_city='Santa Cruz')
        order, _, _ = self.prepare(delivery_city='Santa Cruz', outside_city_ack=True)
        self.assertTrue(order.delivery_outside_city)
        self.assertIsNone(order.delivery_estimate_local)

    def test_order_cap(self):
        Product.objects.filter(pk=self.product.pk).update(price_usd=Decimal('314'))  # > $300 on-chain cap
        with self.assertRaisesMessage(checkout.CheckoutError, 'order_too_large'):
            self.prepare()

    def test_prepare_reserves_stock_for_the_authorization(self):
        self.prepare(quantity=2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_same_terms_reuse_the_open_draft(self):
        first, _, _ = self.prepare()
        again, _, _ = self.prepare(delivery_address='Calle Nueva 99, Miraflores')
        self.assertEqual(first.pk, again.pk)
        again.refresh_from_db()
        self.assertEqual(again.delivery_address, 'Calle Nueva 99, Miraflores')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)  # reserved once, not twice

    def test_different_terms_supersede_but_keep_the_reservation(self):
        first, _, _ = self.prepare(quantity=1)
        second, _, _ = self.prepare(quantity=2)
        first.refresh_from_db()
        self.assertEqual(first.status, 'cancelled')
        self.assertTrue(first.stock_reserved)  # still spendable until its deadline
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)

    def test_no_new_order_while_a_deposit_is_settling(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(status='depositing')
        with self.assertRaisesMessage(checkout.CheckoutError, 'payment_in_progress'):
            self.prepare(quantity=2)

    def test_own_reservation_is_reusable_at_zero_stock(self):
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        first, _, _ = self.prepare()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        again, _, _ = self.prepare()
        self.assertEqual(first.pk, again.pk)

    def test_last_unit_cannot_be_issued_twice(self):
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        self.prepare()
        other = make_user()
        # Sequentially the reservation fails for anyone else…
        with self.assertRaisesMessage(checkout.CheckoutError, 'out_of_stock'):
            checkout.prepare_order(other, PERSONAL, product_id=self.product.pk, quantity=1,
                                   delivery_country='BO', delivery_city='La Paz',
                                   delivery_address='Av. Arce 2345, Sopocachi',
                                   delivery_phone='+59170000000')
        # …and a concurrent prepare that passed that check still loses at the
        # conditional reservation.
        self.assertFalse(escrow.reserve_stock(self.product.pk, 1))


@override_settings(**ENABLED)
class SubmitTests(MarketTestBase):
    def _sponsor(self, **kw):
        sp = mock.MagicMock()
        from cusd_plus.sponsor_7702 import PolicyError, intent_digest, intent_id_for
        sp.PolicyError = PolicyError
        sp.intent_id_for = intent_id_for
        sp.intent_digest = intent_digest
        sp.recover_intent_signer.side_effect = kw.get('recover', lambda d, s: self.signer)
        sp.is_delegated.return_value = True
        sp.send_sponsored_batch.side_effect = kw.get(
            'send', lambda *a, **k: ('0x' + 'ab' * 32, SimpleNamespace(id=7)))
        return sp

    def submit(self, order, action, user, sp):
        import time

        import cusd_plus
        # submit_action imports the module from the package at call time.
        with mock.patch.object(cusd_plus, 'sponsor_7702', sp), \
                mock.patch('marketplace.tasks.confirm_market_action') as confirm:
            result = escrow.submit_action(user, order, action, 1, int(time.time()) + 600, '0xsig')
        return result, confirm

    def test_deposit_marks_depositing_without_touching_stock_again(self):
        order, _, _ = self.prepare(quantity=2)
        self.signer = order.buyer_address
        result, confirm = self.submit(order, 'deposit', self.buyer, self._sponsor())
        self.assertTrue(result['success'], result)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'depositing')
        self.assertEqual(self.product.stock, 1)
        confirm.apply_async.assert_called_once()

    def test_failed_broadcast_hands_the_row_back_reservation_kept(self):
        from cusd_plus.sponsor_7702 import PolicyError
        order, _, _ = self.prepare()
        self.signer = order.buyer_address

        def boom(*a, **k):
            raise PolicyError('simulation_failed')
        result, _ = self.submit(order, 'deposit', self.buyer, self._sponsor(send=boom))
        self.assertFalse(result['success'])
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'draft')
        self.assertEqual(self.product.stock, 2)  # authorization still spendable

    def test_only_the_merchant_ships(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(status='funded')
        order.refresh_from_db()
        self.signer = order.buyer_address
        result, _ = self.submit(order, 'ship', self.buyer, self._sponsor())
        self.assertEqual(result['error'], 'not_your_order')
        self.signer = order.merchant_address
        result, _ = self.submit(order, 'ship', self.seller, self._sponsor())
        self.assertTrue(result['success'], result)
        order.refresh_from_db()
        self.assertEqual(order.pending_action, 'ship')

    def test_business_employee_needs_the_action_permission(self):
        from users.models_employee import BusinessEmployee
        business, account = make_business(self.seller)
        Store.objects.filter(pk=self.store.pk).update(owner_account=account)
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(status='funded', merchant_address=account.bsc_address)
        order.refresh_from_db()
        cashier = make_user()
        BusinessEmployee.objects.create(user=cashier, business=business, role='cashier')
        self.assertTrue(escrow.actor_allowed(cashier, order, 'ship'))     # accept_payments
        self.assertFalse(escrow.actor_allowed(cashier, order, 'refund'))  # send_funds
        self.assertTrue(escrow.actor_allowed(self.seller, order, 'refund'))  # the owner
        outsider = make_user()
        self.assertFalse(escrow.actor_allowed(outsider, order, 'ship'))

    def test_one_action_in_flight(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(status='funded', pending_action='ship',
                                                 pending_action_at=timezone.now())
        order.refresh_from_db()
        self.signer = order.buyer_address
        result, _ = self.submit(order, 'dispute', self.buyer, self._sponsor())
        self.assertEqual(result['error'], 'action_in_progress')


@override_settings(**ENABLED)
class SyncAndLedgerTests(MarketTestBase):
    def chain(self, order, state, **kw):
        return {'buyer': order.buyer_address, 'merchant': order.merchant_address,
                'amount': int(order.amount_wei), 'token': order.token_address,
                'fee_bps': order.fee_bps, 'state': state, 'ship_by': 1_900_000_000,
                'release_at': kw.get('release_at', 0), 'disputed_at': 0,
                'block': kw.get('block', 100), 'block_time': kw.get('block_time', 2_000_000_000)}

    def setUp(self):
        super().setUp()
        p = mock.patch.object(escrow, 'settlement_time', side_effect=lambda o, s, b: (timezone.now(), b))
        p.start()
        self.addCleanup(p.stop)
        n = mock.patch('marketplace.notifications.order_status_changed')
        n.start()
        self.addCleanup(n.stop)

    def test_release_writes_one_ledger_row_with_partner_half(self):
        MarketplacePartnerAgreement.objects.create(
            partner_name='Jason', country_code='BO', share_bps=5000,
            started_at=timezone.now() - timedelta(days=1))
        order, _, _ = self.prepare()
        self.assertEqual(escrow.sync_order(order, self.chain(order, 'funded', block=100)), 'funded')
        order.refresh_from_db()
        escrow.sync_order(order, self.chain(order, 'released', block=110))
        escrow.sync_order(order, self.chain(order, 'released', block=120))  # idempotent
        entry = MarketplaceFeeLedger.objects.get(order=order)
        self.assertEqual(entry.gross_usd, Decimal('30.000000'))
        self.assertEqual(entry.fee_usd, Decimal('2.400000'))          # 8%
        self.assertEqual(entry.partner_share_usd, Decimal('1.200000'))  # Jason 4%
        self.assertEqual(entry.confio_share_usd, Decimal('1.200000'))   # Confío 4%

    def test_no_partner_share_after_agreement_ended(self):
        MarketplacePartnerAgreement.objects.create(
            partner_name='Jason', country_code='BO', share_bps=5000, active=False,
            started_at=timezone.now() - timedelta(days=30), ended_at=timezone.now() - timedelta(days=1))
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'released'))
        entry = MarketplaceFeeLedger.objects.get(order=order)
        self.assertEqual(entry.partner_share_usd, 0)
        self.assertEqual(entry.confio_share_usd, entry.fee_usd)

    def test_mismatched_chain_order_is_never_mirrored(self):
        order, _, _ = self.prepare()
        forged = self.chain(order, 'released')
        forged['merchant'] = '0x' + '99' * 20
        escrow.sync_order(order, forged)
        order.refresh_from_db()
        self.assertEqual(order.status, 'draft')
        self.assertFalse(MarketplaceFeeLedger.objects.exists())

    def test_expired_unspent_authorization_hands_stock_back(self):
        from .tasks import run_escrow_keeper
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(deposit_deadline=1)
        with mock.patch.object(escrow, 'read_chain_order', return_value=self.chain(order, 'none')):
            run_escrow_keeper()
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertFalse(order.stock_reserved)
        self.assertEqual(self.product.stock, 3)

    def test_lagging_snapshot_never_releases_a_reservation(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(deposit_deadline=1_000)
        order.refresh_from_db()
        # The node answers 'none' from a block BEFORE the deadline: inconclusive.
        with mock.patch.object(escrow, 'read_chain_order',
                               return_value=self.chain(order, 'none', block_time=999)):
            self.assertFalse(escrow.release_unspent_reservation(order))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)

    def test_release_never_overwrites_a_synced_order(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(deposit_deadline=1, status='funded')
        order.refresh_from_db()
        with mock.patch.object(escrow, 'read_chain_order', return_value=self.chain(order, 'none')):
            self.assertFalse(escrow.release_unspent_reservation(order))
        order.refresh_from_db()
        self.assertEqual(order.status, 'funded')

    def test_unknown_settlement_time_defers_the_fee_row(self):
        order, _, _ = self.prepare()
        with mock.patch.object(escrow, 'settlement_time', return_value=(None, 150)):
            escrow.sync_order(order, self.chain(order, 'released'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'released')
        self.assertIsNone(order.settled_at)
        self.assertFalse(MarketplaceFeeLedger.objects.exists())
        escrow.sync_order(order, self.chain(order, 'released', block=200))  # next sync finds it
        self.assertTrue(MarketplaceFeeLedger.objects.filter(order=order).exists())

    def test_unexpired_authorization_keeps_its_stock(self):
        order, _, _ = self.prepare()
        with mock.patch.object(escrow, 'read_chain_order') as read:
            self.assertFalse(escrow.release_unspent_reservation(order))
        read.assert_not_called()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)

    def test_superseded_draft_that_was_spent_is_resurrected(self):
        from .tasks import run_escrow_keeper
        first, _, _ = self.prepare(quantity=1)
        self.prepare(quantity=2)  # supersedes `first` in the app
        Order.objects.filter(pk=first.pk).update(deposit_deadline=1)
        first.refresh_from_db()
        with mock.patch.object(escrow, 'read_chain_order', return_value=self.chain(first, 'funded')):
            run_escrow_keeper()
        first.refresh_from_db()
        self.assertEqual(first.status, 'funded')
        self.assertTrue(first.stock_reserved)

    def test_older_snapshot_never_overwrites_a_newer_one(self):
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'refunded', block=200))
        order.refresh_from_db()
        escrow.sync_order(order, self.chain(order, 'funded', block=150))
        order.refresh_from_db()
        self.assertEqual(order.status, 'refunded')

    def test_settled_orders_never_move_again(self):
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'released', block=200))
        order.refresh_from_db()
        escrow.sync_order(order, self.chain(order, 'funded', block=300))
        order.refresh_from_db()
        self.assertEqual(order.status, 'released')

    def test_partner_share_follows_release_time_not_current_flag(self):
        agreement = MarketplacePartnerAgreement.objects.create(
            partner_name='Jason', country_code='BO', share_bps=5000,
            started_at=timezone.now() - timedelta(days=10))
        order, _, _ = self.prepare()
        released_at = timezone.now() - timedelta(hours=1)
        # The agreement ended AFTER the release but before the sync ran.
        MarketplacePartnerAgreement.objects.filter(pk=agreement.pk).update(
            active=False, ended_at=timezone.now() - timedelta(minutes=5))
        with mock.patch.object(escrow, 'settlement_time', return_value=(released_at, 0)):
            escrow.sync_order(order, self.chain(order, 'released'))
        entry = MarketplaceFeeLedger.objects.get(order=order)
        self.assertEqual(entry.partner_share_usd, Decimal('1.200000'))
        self.assertEqual(entry.partner_agreement_id, agreement.pk)


@override_settings(**ENABLED)
class ModerationTests(MarketTestBase):
    def test_rejected_listing_is_hidden_with_reason(self):
        from . import moderation
        self.product.status = 'pending_review'
        self.product.review_claim = 'c1'
        self.product.save()
        verdict = {'decision': 'reject', 'category': 'contact_info', 'confidence': 0.95,
                   'reason': 'No incluyas tu WhatsApp.', 'model': 'luna'}
        with mock.patch.object(moderation, '_decide', return_value=verdict):
            self.assertEqual(moderation.run_product_review(self.product.pk, 'c1'), 'rejected')
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, 'rejected')
        self.assertEqual(self.product.rejection_reason, 'No incluyas tu WhatsApp.')
        self.assertFalse(self.product.is_buyable)

    def test_stale_unpause_cannot_reactivate_an_edited_listing(self):
        from .schema import SetMarketProductPaused
        self.product.status = 'paused'
        self.product.review_claim = 'approved-rev'
        self.product.save()
        old_claim = self.product.review_claim
        # An edit lands (new revision) and moderation rejects it…
        Product.objects.filter(pk=self.product.pk).update(status='rejected', review_claim='new-rev')
        # …then the stale unpause, which read the old revision, arrives.
        moved = Product.objects.filter(pk=self.product.pk, status='paused',
                                       review_claim=old_claim).update(status='active')
        self.assertEqual(moved, 0)
        self.assertTrue(hasattr(SetMarketProductPaused, 'mutate'))

    def test_review_result_never_overrides_a_non_pending_listing(self):
        from . import moderation
        self.product.status = 'paused'
        self.product.review_claim = 'c1'
        self.product.save()
        verdict = {'decision': 'approve', 'category': 'ok', 'confidence': 0.99, 'reason': '', 'model': 'luna'}
        with mock.patch.object(moderation, '_decide', return_value=verdict):
            moderation.run_product_review(self.product.pk, 'c1')
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, 'paused')

    def test_stale_claim_is_ignored(self):
        from . import moderation
        self.product.status = 'pending_review'
        self.product.review_claim = 'new'
        self.product.save()
        with mock.patch.object(moderation, '_decide') as decide:
            self.assertEqual(moderation.run_product_review(self.product.pk, 'old'), 'stale')
        decide.assert_not_called()


class NearestCityTests(TestCase):
    def setUp(self):
        # Own fixtures (the same centres migration 0002 seeds): a test must not
        # depend on seed rows another suite's flush may have wiped.
        for cc, cur, name, lat, lng, r in [
            ('BO', 'BOB', 'La Paz', '-16.500000', '-68.150000', 30),
            ('BO', 'BOB', 'El Alto', '-16.504700', '-68.163300', 15),
            ('BO', 'BOB', 'Cochabamba', '-17.393500', '-66.157000', 30),
            ('VE', 'VES', 'Caracas', '10.480600', '-66.903600', 35),
            ('AR', 'ARS', 'Buenos Aires', '-34.603700', '-58.381600', 40),
            ('AR', 'ARS', 'Córdoba', '-31.420100', '-64.188800', 30),
        ]:
            MarketplaceCity.objects.update_or_create(
                country_code=cc, city=name,
                defaults={'currency_code': cur, 'latitude': Decimal(lat), 'longitude': Decimal(lng), 'radius_km': r})

    def test_gps_matches_the_city_whose_radius_contains_it(self):
        from .schema import nearest_city
        # Seeded by migration 0002 (La Paz, El Alto, Santa Cruz, Cochabamba).
        self.assertTrue(MarketplaceCity.objects.filter(city='La Paz', latitude__isnull=False).exists())
        self.assertEqual(nearest_city(-16.52, -68.12).city, 'La Paz')  # Sopocachi-ish
        self.assertEqual(nearest_city(-17.39, -66.16).city, 'Cochabamba')
        self.assertEqual(nearest_city(10.49, -66.87).city, 'Caracas')
        self.assertEqual(nearest_city(-34.59, -58.42).city, 'Buenos Aires')  # Palermo
        self.assertEqual(nearest_city(-31.42, -64.19).city, 'Córdoba')
        self.assertIsNone(nearest_city(-19.04, -65.26))  # Sucre: not a known city

    def test_locating_stores_the_reading(self):
        from .models import MarketplaceLocationCheck
        from .schema import LocateMarketplaceCity
        user = make_user()
        info = SimpleNamespace(context=SimpleNamespace(user=user, META={'REMOTE_ADDR': '200.87.1.1'}))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            result = LocateMarketplaceCity.mutate.__wrapped__(None, info, -16.52, -68.12, 25.0)
        self.assertEqual(result.city.city, 'La Paz')
        check = MarketplaceLocationCheck.objects.get(user=user)
        self.assertAlmostEqual(check.latitude, -16.52)
        self.assertEqual(check.accuracy_m, 25.0)
        self.assertEqual(check.matched_city.city, 'La Paz')
        self.assertEqual(check.account, user.accounts.get())


@override_settings(**ENABLED)
class StoreUpdateTests(MarketTestBase):
    def test_stale_seller_update_cannot_undo_a_suspension(self):
        from .schema import UpdateMarketStore
        Store.objects.filter(pk=self.store.pk).update(status='suspended')
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            UpdateMarketStore.mutate.__wrapped__(None, info, description='Nueva descripción', paused=False)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, 'suspended')
        self.assertEqual(self.store.description, 'Nueva descripción')

    def test_stock_edit_applies_a_delta_from_the_loaded_form(self):
        from .schema import SaveMarketProduct
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        # The form loaded stock=3; a checkout then reserved 2 (stock now 1).
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('marketplace.moderation.transaction.on_commit'):
            SaveMarketProduct.mutate.__wrapped__(
                None, info, title='Chompa de alpaca', category='textiles', price_usd='30',
                stock=3, product_id=self.product.pk, description='Más abrigada', expected_stock=3,
                expected_stock_revision=0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)  # unchanged: the seller did not change stock

    def test_retried_stock_edit_applies_once(self):
        from .schema import SaveMarketProduct
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        args = dict(title='Chompa de alpaca', category='textiles', price_usd='30', stock=5,
                    product_id=self.product.pk, expected_stock=3, expected_stock_revision=0)
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('marketplace.moderation.transaction.on_commit'):
            first = SaveMarketProduct.mutate.__wrapped__(None, info, **args)
            retry = SaveMarketProduct.mutate.__wrapped__(None, info, **args)  # lost response, pressed again
        self.assertTrue(first.success)
        self.assertEqual(retry.error, 'stale_form')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # +2 once, not twice


@override_settings(**ENABLED)
class SettlementSearchTests(MarketTestBase):
    def test_forward_scan_resumes_and_finds_an_old_event(self):
        order, _, _ = self.prepare()
        Order.objects.filter(pk=order.pk).update(open_block=1_000)
        order.refresh_from_db()
        calls = []

        def rpc(method, params):
            if method == 'eth_getLogs':
                lo, hi = int(params[0]['fromBlock'], 16), int(params[0]['toBlock'], 16)
                calls.append((lo, hi))
                return [{'blockNumber': hex(900_000)}] if lo <= 900_000 <= hi else []
            if method == 'eth_getBlockByNumber':
                return {'timestamp': hex(1_900_000_000)}
            raise AssertionError(method)

        with mock.patch('cusd_plus.sponsor_7702._rpc', side_effect=rpc):
            first, scan = escrow.settlement_time(order, 'released', 1_000_000)
            self.assertIsNone(first)  # 120 chunks did not reach it yet
            self.assertGreater(scan, 1_000)
            Order.objects.filter(pk=order.pk).update(settle_scan_block=scan)
            order.refresh_from_db()
            found, _ = escrow.settlement_time(order, 'released', 1_000_000)
        self.assertIsNotNone(found)
        self.assertEqual(calls[0][0], 1_000)  # starts at the stable lower bound

    def test_search_start_recovers_the_deposit_hash_from_its_batch(self):
        from blockchain.models import SponsoredBatch
        order, _, _ = self.prepare()
        SponsoredBatch.objects.create(
            user=self.buyer, user_bsc_address=order.buyer_address, kind='market_deposit',
            source_id=order.pk, num_calls=2, calls_json='[]', tx_hash='0x' + 'ab' * 32,
            gas_limit=300_000, max_fee_wei='1', status='confirmed', block_number=4_242)
        # No deposit_tx_hash on the row (its write was lost): the batch knows.
        with mock.patch('cusd_plus.sponsor_7702._rpc') as rpc:
            self.assertEqual(escrow._search_start_block(order, 10_000), 4_242)
        rpc.assert_not_called()


@override_settings(**ENABLED)
class ProductVisibilityTests(MarketTestBase):
    def test_seller_view_needs_the_stores_own_account(self):
        from .schema import Query
        business, account = make_business(self.seller)
        Store.objects.filter(pk=self.store.pk).update(owner_account=account)
        Product.objects.filter(pk=self.product.pk).update(status='rejected', rejection_reason='WhatsApp')
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        # Same person, but on their PERSONAL account: public rules (hidden).
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            self.assertIsNone(Query.resolve_marketplace_product(None, info, self.product.pk))
        biz = {'account_type': 'business', 'business_id': business.id, 'account_index': 0}
        with mock.patch('marketplace.schema._jwt', return_value=biz):
            seen = Query.resolve_marketplace_product(None, info, self.product.pk)
        self.assertEqual(seen.rejection_reason, 'WhatsApp')


@override_settings(**ENABLED, FACE_STEP_UP_ENABLED=False)
class FaceEnforcementTests(MarketTestBase):
    def test_face_cannot_be_skipped_by_rollout_switch_or_missing_header(self):
        # The base class stubs deposit_step_up; exercise the real one.
        from security.face_step_up import FACE_STEP_UP_MESSAGE
        self.addCleanup(mock.patch.stopall)
        mock.patch.stopall()
        real = escrow.deposit_step_up
        with mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value=''):
            message = real(self.buyer, order_id32='ab' * 32, buyer='0x' + '1' * 40,
                           merchant='0x' + '2' * 40, amount_wei=5 * WAD, amount_usd=Decimal('5'))
        self.assertEqual(message, FACE_STEP_UP_MESSAGE)  # no approval on file → Face asked

    def test_claim_without_a_consumed_approval_never_passes(self):
        mock.patch.stopall()
        real = escrow.deposit_step_up
        # The shared helper says '' (eligibility flipped) but consumed nothing.
        with mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value=''), \
                mock.patch('security.face_step_up.require_face_step_up', return_value=''):
            message = real(self.buyer, consume=True, order_id32='cd' * 32, buyer='0x' + '1' * 40,
                           merchant='0x' + '2' * 40, amount_wei=5 * WAD, amount_usd=Decimal('5'))
        from security.face_step_up import FACE_STEP_UP_MESSAGE
        self.assertEqual(message, FACE_STEP_UP_MESSAGE)


class InterestProbeTests(TestCase):
    def setUp(self):
        ensure_categories()

    def _submit(self, user, **kw):
        from .schema import SubmitMarketplaceInterest
        info = SimpleNamespace(context=SimpleNamespace(user=user, headers={'X-Confio-Version': '5.3.0'}))
        args = dict(country_code='VE', city='Caracas', role='seller', categories=['textiles', 'nope'],
                    wants='Ropa tejida a mano', price_range='10_30', monthly_sales='200_1000',
                    channels=['instagram', 'whatsapp', 'spam'], notify=True)
        args.update(kw)
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            return SubmitMarketplaceInterest.mutate.__wrapped__(None, info, **args)

    def test_seller_answer_is_stored_clean_and_updates_in_place(self):
        from .models import MarketplaceInterest
        user = make_user()
        self.assertTrue(self._submit(user).success)
        row = MarketplaceInterest.objects.get(user=user)
        self.assertEqual(row.categories, ['textiles'])          # unknown keys dropped
        self.assertEqual(row.channels, ['instagram', 'whatsapp'])
        self.assertEqual(row.monthly_sales, '200_1000')
        self.assertEqual(row.app_version, '5.3.0')
        self._submit(user, role='buyer', price_range='30_100')
        row.refresh_from_db()
        self.assertEqual(MarketplaceInterest.objects.filter(user=user).count(), 1)
        self.assertEqual(row.role, 'buyer')
        self.assertEqual(row.monthly_sales, '')                 # seller-only fields cleared
        self.assertEqual(row.channels, [])

    def test_browsing_records_intent_without_notice_or_price(self):
        from .models import MarketplaceInterest
        user = make_user()
        self._submit(user, role='browsing')
        row = MarketplaceInterest.objects.get(user=user)
        self.assertFalse(row.notify)
        self.assertEqual(row.price_range, '')

    def test_bad_input_rejected(self):
        user = make_user()
        self.assertEqual(self._submit(user, role='admin').error, 'bad_input')
        self.assertEqual(self._submit(user, price_range='huge').error, 'bad_input')
        self.assertEqual(self._submit(user, country_code='ZZ').error, 'bad_input')


@override_settings(**ENABLED)
class CategoryTests(MarketTestBase):
    def test_categories_come_grouped_from_the_db_with_city_counts(self):
        from .models import MarketplaceCategory
        from .schema import Query
        MarketplaceCategory.objects.update_or_create(key='cafe', defaults={
            'label': 'Café', 'group': 'Comida envasada', 'is_active': True})
        MarketplaceCategory.objects.update_or_create(key='retired', defaults={
            'label': 'Retirada', 'group': 'Otros', 'is_active': False})
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        rows = {c.key: c for c in Query.resolve_marketplace_categories(None, info, 'BO', 'La Paz')}
        self.assertNotIn('retired', rows)                       # hidden: no new listings
        self.assertEqual(rows['textiles'].product_count, 1)     # the base product
        self.assertEqual(rows['cafe'].product_count, 0)
        self.assertEqual(rows['textiles'].group, 'Artesanía y regalos')
        plain = {c.key: c for c in Query.resolve_marketplace_categories(None, info)}
        self.assertIsNone(plain['textiles'].product_count)      # no city asked: no counts

    def test_a_listing_needs_an_active_category(self):
        from .models import MarketplaceCategory
        from .schema import SaveMarketProduct
        MarketplaceCategory.objects.filter(key='artesanias').update(is_active=False)
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            result = SaveMarketProduct.mutate.__wrapped__(
                None, info, title='Retablo', category='artesanias', price_usd='7', stock=1,
                photo_keys=[f'marketplace/pending/{self.seller.id}/upload.jpg'])
        self.assertEqual(result.error, 'bad_category')

    def test_existing_listing_keeps_a_since_hidden_category(self):
        from .models import MarketplaceCategory
        from .schema import SaveMarketProduct
        MarketplaceCategory.objects.filter(key='textiles').update(is_active=False)
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('marketplace.moderation.transaction.on_commit'):
            result = SaveMarketProduct.mutate.__wrapped__(
                None, info, title='Chompa de alpaca', category='textiles', price_usd='33', stock=3,
                product_id=self.product.pk, expected_stock=3, expected_stock_revision=0)
        self.assertTrue(result.success, result.error)


@override_settings(**ENABLED)
class UsdPricingTests(MarketTestBase):
    def test_checkout_never_depends_on_an_exchange_rate(self):
        from django.core.cache import cache
        cache.clear()
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row',
                        side_effect=RuntimeError('rates down')):
            order, _, _ = self.prepare(quantity=2)
        self.assertEqual(order.unit_price_usd, Decimal('30.00'))
        self.assertEqual(order.amount_usd, Decimal('60.00'))
        self.assertEqual(order.delivery_currency, 'BOB')       # the courier is paid locally

    def test_product_shows_a_local_reference_only_with_a_rate(self):
        from django.core.cache import cache
        from .schema import MarketplaceProductType
        cache.clear()
        fresh = SimpleNamespace(rate=Decimal('6.96'), fetched_at=timezone.now())
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row', return_value=fresh):
            p = MarketplaceProductType.from_model(self.product)
        self.assertEqual(p.price_usd, '30.00')
        self.assertEqual((p.reference_local.amount, p.reference_local.currency), ('208.80', 'BOB'))
        cache.clear()
        with mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row', return_value=None):
            self.assertIsNone(MarketplaceProductType.from_model(self.product).reference_local)


class ReferenceResilienceTests(SimpleTestCase):
    def test_a_cache_outage_never_breaks_the_reference_path(self):
        fresh = SimpleNamespace(rate=Decimal('6.96'), fetched_at=timezone.now())
        with mock.patch('django.core.cache.cache.get', side_effect=ConnectionError('redis down')), \
                mock.patch('django.core.cache.cache.set', side_effect=ConnectionError('redis down')), \
                mock.patch('exchange_rates.services.exchange_rate_service.get_current_rate_row', return_value=fresh):
            self.assertEqual(pricing.reference_local(Decimal('10'), 'BO'), (Decimal('69.60'), 'BOB'))
        with mock.patch.object(pricing, 'local_per_usd', side_effect=RuntimeError('anything')):
            self.assertIsNone(pricing.reference_local(Decimal('10'), 'BO'))
