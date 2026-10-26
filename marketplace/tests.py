from django.core.management import call_command
import io
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
from .models import (DeliveryAddress, MarketplaceCity, MarketplaceFeeLedger, MarketplacePartnerAgreement, Order,
                     OrderRating, Product, Store)

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
        # Delivery is the store's price inside the total, not a courier estimate.
        self.assertIsNone(order.delivery_estimate_local)
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

    def test_other_city_needs_the_stores_other_cities_price_and_pays_it_in_the_total(self):
        with self.assertRaisesMessage(checkout.CheckoutError, 'store_city_only'):
            self.prepare(delivery_city='Santa Cruz')
        Store.objects.filter(pk=self.store.pk).update(outside_delivery_price_usd=Decimal('4.00'),
                                                      ships_outside_city=True)
        order, _, _ = self.prepare(delivery_city='Santa Cruz')  # nothing to acknowledge any more
        self.assertTrue(order.delivery_outside_city)
        self.assertEqual((order.delivery_usd, order.amount_usd), (Decimal('4.00'), Decimal('34.00')))

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

    def _month(self, user):
        from zoneinfo import ZoneInfo
        from users.cashflow import summarize
        now = timezone.now()
        return summarize(user, user.accounts.get(), 'personal', None, now.year, now.month, ZoneInfo('UTC')).current

    def _history(self, user):
        from users.graphql_views import account_unified_queryset
        return set(account_unified_queryset(user, user.accounts.get(), 'personal', None)
                   .values_list('payment_reference_id', flat=True))

    def test_purchase_and_sale_reach_history_and_tu_mes(self):
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'funded', block=100))
        buy = f'comprar:{order.pk}:buy'
        self.assertEqual(self._history(self.buyer), {buy})
        # Held in escrow: nothing is the seller's yet.
        self.assertEqual(self._history(self.seller), set())
        self.assertEqual(self._month(self.buyer).spending, Decimal('30.00'))
        self.assertEqual(self._month(self.buyer).spending_by_category, {'shopping': Decimal('30.00')})

        order.refresh_from_db()
        escrow.sync_order(order, self.chain(order, 'released', block=110))
        escrow.sync_order(order, self.chain(order, 'released', block=120))  # idempotent
        self.assertEqual(self._history(self.seller), {f'comprar:{order.pk}:sale'})
        self.assertEqual(self._history(self.buyer), {buy})
        self.assertEqual(self._month(self.seller).income, Decimal('27.60'))  # net of the 8% fee
        self.assertEqual(self._month(self.buyer).spending, Decimal('30.00'))
        from zoneinfo import ZoneInfo
        from users.cashflow import comprar_month, summarize
        now, utc = timezone.now(), ZoneInfo('UTC')
        for user, expected in ((self.buyer, (Decimal('30.00'), 1, Decimal('0'), 0)),
                               (self.seller, (Decimal('0'), 0, Decimal('27.60'), 1))):
            c = comprar_month(user, user.accounts.get(), 'personal', None, now.year, now.month, utc)
            self.assertEqual((c.purchases, c.purchase_count, c.sales, c.sale_count), expected)
            # Its own section: never a "Con quién" line.
            month = summarize(user, user.accounts.get(), 'personal', None, now.year, now.month, utc)
            self.assertEqual(month.counterparties, [])

    def test_refund_shows_in_history_and_nets_out_of_tu_mes(self):
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'funded', block=100))
        order.refresh_from_db()
        escrow.sync_order(order, self.chain(order, 'refunded', block=110))
        self.assertEqual(self._history(self.buyer), {f'comprar:{order.pk}:buy', f'comprar:{order.pk}:refund'})
        self.assertEqual(self._history(self.seller), set())
        totals = self._month(self.buyer)
        self.assertEqual((totals.spending, totals.income), (Decimal('0'), Decimal('0')))

    def test_ledger_failure_never_undoes_the_sync(self):
        order, _, _ = self.prepare()
        with mock.patch('marketplace.ledger._write', side_effect=RuntimeError('boom')):
            self.assertEqual(escrow.sync_order(order, self.chain(order, 'funded', block=100)), 'funded')
        order.refresh_from_db()
        self.assertEqual(order.status, 'funded')

    def test_keeper_heals_a_settlement_row_whose_mirror_failed(self):
        from marketplace.ledger import heal_missing
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'funded', block=100))
        order.refresh_from_db()
        with mock.patch('marketplace.ledger._write', side_effect=RuntimeError('boom')):
            escrow.sync_order(order, self.chain(order, 'released', block=110))
        self.assertNotIn(f'comprar:{order.pk}:sale', self._history(self.seller))
        self.assertEqual(heal_missing(), 1)
        self.assertEqual(self._history(self.seller), {f'comprar:{order.pk}:sale'})
        self.assertEqual(heal_missing(), 0)  # nothing left to heal
        # A settlement time found later, whose correction also failed.
        exact = timezone.now() - timedelta(hours=3)
        Order.objects.filter(pk=order.pk).update(settled_at=exact)
        self.assertEqual(heal_missing(), 1)
        from users.models_unified import UnifiedTransactionTable as U
        row = U.objects.get(payment_reference_id=f'comprar:{order.pk}:sale')
        self.assertEqual((row.transaction_date, row.created_at), (exact, exact))
        self.assertEqual(heal_missing(), 0)

    def test_late_rows_sit_at_the_money_movement_in_history(self):
        from users.models_unified import UnifiedTransactionTable as U
        order, _, _ = self.prepare()
        escrow.sync_order(order, self.chain(order, 'funded', block=100))
        funded_at = timezone.now() - timedelta(days=40)
        Order.objects.filter(pk=order.pk).update(funded_at=funded_at)
        U.objects.filter(payment_reference_id=f'comprar:{order.pk}:buy').delete()
        call_command('backfill_comprar_ledger', stdout=io.StringIO())
        row = U.objects.get(payment_reference_id=f'comprar:{order.pk}:buy')
        self.assertEqual((row.created_at, row.transaction_date), (funded_at, funded_at))
        self.assertTrue(row.description.startswith('Comprar: '))

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


@override_settings(**ENABLED)
class PhotoUploadTypeTests(MarketTestBase):
    def request(self, content_type):
        from .schema import RequestMarketPhotoUpload
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        presign = mock.Mock(return_value={'url': 'https://s3', 'key': 'k', 'method': 'POST',
                                          'fields': {}, 'expires_in': 600})
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('inbox.community.take_upload_ticket', return_value=True), \
                mock.patch('security.s3_utils.generate_presigned_post', presign):
            return RequestMarketPhotoUpload.mutate.__wrapped__(None, info, content_type=content_type), presign

    def test_ios_image_jpg_label_is_accepted_as_jpeg(self):
        result, presign = self.request('image/jpg')
        self.assertTrue(result.success, result.error)
        self.assertEqual(presign.call_args.kwargs['content_type'], 'image/jpeg')
        self.assertTrue(presign.call_args.kwargs['key'].endswith('.jpg'))

    def test_unsupported_types_are_still_refused(self):
        result, presign = self.request('image/gif')
        self.assertEqual(result.error, 'bad_image_type')
        presign.assert_not_called()


@override_settings(**ENABLED)
class AddressBookTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        patcher = mock.patch('marketplace.schema._jwt', return_value=PERSONAL)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, **overrides):
        from .address_book import SaveDeliveryAddress
        args = dict(country_code='BO', city='La Paz', address='Av. Arce 2345, Sopocachi', phone='+591 70000000')
        args.update(overrides)
        return SaveDeliveryAddress.mutate.__wrapped__(None, self.info, **args)

    def book(self):
        from .address_book import resolve_my_delivery_addresses
        return resolve_my_delivery_addresses(self.info)

    def test_first_address_is_the_default_and_resaving_it_does_not_duplicate(self):
        first = self.save(label='Casa')
        self.assertTrue(first.success, first.error)
        self.assertTrue(first.address.is_default)
        again = self.save(address='av. arce  2345, SOPOCACHI', phone='59170000000', mark_used=True)
        self.assertTrue(again.success, again.error)
        self.assertEqual(again.address.id, first.address.id)
        self.assertEqual(again.address.label, 'Casa')  # a nameless re-save keeps the name
        self.assertEqual(DeliveryAddress.objects.filter(user=self.user).count(), 1)
        self.assertIsNotNone(DeliveryAddress.objects.get(user=self.user).last_used_at)

    def test_the_same_rules_as_checkout(self):
        self.assertEqual(self.save(address='Corta').error, 'delivery_address_required')
        self.assertEqual(self.save(phone='123').error, 'delivery_phone_required')
        self.assertEqual(self.save(city='').error, 'bad_city')

    def test_the_book_is_capped(self):
        for i in range(DeliveryAddress.MAX_PER_BOOK):
            self.assertTrue(self.save(address=f'Calle {i} número 100').success)
        self.assertEqual(self.save(address='Una más, número 200').error, 'address_book_full')

    def test_other_users_cannot_see_or_delete_an_address(self):
        from .address_book import DeleteDeliveryAddress
        mine = self.save()
        other = make_user()
        other_info = SimpleNamespace(context=SimpleNamespace(user=other))
        from .address_book import resolve_my_delivery_addresses
        self.assertEqual(resolve_my_delivery_addresses(other_info), [])
        res = DeleteDeliveryAddress.mutate.__wrapped__(None, other_info, address_id=mine.address.id)
        self.assertEqual(res.error, 'address_not_found')
        self.assertTrue(DeliveryAddress.objects.filter(pk=mine.address.id, deleted_at__isnull=True).exists())

    def test_the_recarga_address_is_offered_read_only_until_saved(self):
        from ramps.models import RampUserAddress
        from .address_book import DeleteDeliveryAddress
        User.objects.filter(pk=self.user.pk).update(phone_country='BO', phone_key='591:71234567')
        self.user.refresh_from_db()
        RampUserAddress.objects.create(user=self.user, address_street='Calle Jaén 711', address_neighborhood='Casco Viejo',
                                       address_city='La Paz', address_state='La Paz', address_zip_code='0000')
        [recarga] = self.book()
        self.assertEqual((recarga.source, recarga.editable), ('recarga', False))
        self.assertEqual(recarga.address, 'Calle Jaén 711, Casco Viejo')
        self.assertEqual(recarga.phone, '+59171234567')
        self.assertEqual(DeleteDeliveryAddress.mutate.__wrapped__(None, self.info, address_id='recarga').error,
                         'address_not_editable')
        # Paid to once (saved from checkout), it is a book entry, not offered twice.
        self.save(address=recarga.address, phone=recarga.phone, mark_used=True)
        self.assertEqual([a.source for a in self.book()], ['saved'])

    def test_deleting_the_default_hands_it_to_the_next_address(self):
        from .address_book import DeleteDeliveryAddress
        first = self.save()
        second = self.save(address='Calle Sagárnaga 300, Centro', mark_used=True)
        self.assertTrue(DeleteDeliveryAddress.mutate.__wrapped__(None, self.info, address_id=first.address.id).success)
        [left] = self.book()
        self.assertEqual(left.id, second.address.id)
        self.assertTrue(left.is_default)


@override_settings(**ENABLED)
class AddressBookPrivacyTests(TestCase):
    def test_the_recarga_address_is_never_offered_in_a_business_account(self):
        from ramps.models import RampUserAddress
        from users.models import Business
        from .address_book import resolve_my_delivery_addresses
        user = make_user()
        User.objects.filter(pk=user.pk).update(phone_country='BO', phone_key='591:71234567')
        RampUserAddress.objects.create(user=user, address_street='Calle Jaén 711', address_city='La Paz',
                                       address_state='La Paz', address_zip_code='0000')
        business = Business.objects.create(name='Tejidos SRL')
        Account.objects.create(user=user, account_type='business', account_index=0, business=business,
                               bsc_address='0x' + 'b' * 40)
        info = SimpleNamespace(context=SimpleNamespace(user=User.objects.get(pk=user.pk)))
        with mock.patch('marketplace.schema._jwt', return_value={'account_type': 'personal', 'account_index': 0, 'business_id': None}):
            self.assertEqual([a.source for a in resolve_my_delivery_addresses(info)], ['recarga'])
        with mock.patch('marketplace.schema._jwt', return_value={'account_type': 'business', 'account_index': 0,
                                                                 'business_id': str(business.id)}):
            self.assertEqual(resolve_my_delivery_addresses(info), [])

    def test_same_street_in_another_country_is_another_address(self):
        user = make_user()
        info = SimpleNamespace(context=SimpleNamespace(user=user))
        from .address_book import SaveDeliveryAddress
        args = dict(city='Centro', address='Calle Bolívar 100, Centro', phone='+591 70000000')
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            a = SaveDeliveryAddress.mutate.__wrapped__(None, info, country_code='BO', **args)
            b = SaveDeliveryAddress.mutate.__wrapped__(None, info, country_code='VE', **args)
        self.assertNotEqual(a.address.id, b.address.id)
        self.assertEqual(sorted(DeliveryAddress.objects.filter(user=user).values_list('country_code', flat=True)), ['BO', 'VE'])


@override_settings(**ENABLED)
class StoreReviewTests(MarketTestBase):
    def released_order(self):
        self.prepare()
        order = Order.objects.get(buyer=self.buyer, product=self.product)
        Order.objects.filter(pk=order.pk).update(status='released')
        return order

    def rate(self, order, **kwargs):
        from .schema import RateMarketOrder
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('marketplace.tasks.review_rating.apply_async') as delay, self.captureOnCommitCallbacks(execute=True):
            res = RateMarketOrder.mutate.__wrapped__(None, info, order_id=str(order.public_id), **kwargs)
        return res, delay

    def reviews(self):
        from .schema import Query
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        return Query.resolve_marketplace_store_reviews(None, info, store_id=self.store.pk)

    def test_review_text_waits_for_moderation_but_the_stars_count_at_once(self):
        order = self.released_order()
        res, delay = self.rate(order, rating=4, comment='Muy linda la chompa, llegó rápido.')
        self.assertTrue(res.success, res.error)
        rating = OrderRating.objects.get(order=order)
        self.assertEqual(rating.comment_status, 'pending')
        self.assertEqual(delay.call_args.args[0], (rating.pk,))
        [review] = self.reviews()
        self.assertEqual((review.rating, review.comment, review.author), (4, None, self.buyer.username))

    def test_stars_only_needs_no_moderation(self):
        res, delay = self.rate(self.released_order(), rating=5)
        self.assertTrue(res.success)
        delay.assert_not_called()
        self.assertEqual(OrderRating.objects.get().comment_status, 'none')

    def test_approved_text_is_published_and_rejected_text_never(self):
        from .moderation import run_rating_review
        order = self.released_order()
        self.rate(order, rating=2, comment='Tardó una semana y vino sin etiqueta.')
        rating = OrderRating.objects.get(order=order)
        with mock.patch('marketplace.moderation._decide', return_value={'decision': 'approve'}):
            self.assertEqual(run_rating_review(rating.pk), 'approved')
        self.assertEqual(self.reviews()[0].comment, 'Tardó una semana y vino sin etiqueta.')
        # Decided once: a retried task cannot flip it.
        with mock.patch('marketplace.moderation._decide', return_value={'decision': 'reject'}):
            self.assertEqual(run_rating_review(rating.pk), 'stale')
        OrderRating.objects.filter(pk=rating.pk).update(comment_status='pending')
        with mock.patch('marketplace.moderation._decide', return_value={'decision': 'reject'}):
            self.assertEqual(run_rating_review(rating.pk), 'rejected')
        self.assertIsNone(self.reviews()[0].comment)

    def test_a_stalled_review_goes_back_to_the_reviewer_once_per_interval(self):
        from datetime import timedelta
        from .tasks import requeue_stuck_reviews
        order = self.released_order()
        self.rate(order, rating=3, comment='Correcto, nada especial.')
        old = timezone.now() - timedelta(hours=2)
        OrderRating.objects.update(comment_queued_at=old)
        with mock.patch('marketplace.tasks.review_rating.apply_async') as delay:
            self.assertEqual(requeue_stuck_reviews()['ratings'], 1)
            self.assertEqual(requeue_stuck_reviews()['ratings'], 0)  # stamped: not again next run
        delay.assert_called_once()


    def test_a_verdict_only_applies_to_the_text_it_reviewed(self):
        from .moderation import run_rating_review
        order = self.released_order()
        self.rate(order, rating=5, comment='Excelente, recomendado.')
        rating = OrderRating.objects.get(order=order)

        def decide_then_text_changes(*args, **kwargs):
            OrderRating.objects.filter(pk=rating.pk).update(comment='Otro texto que nadie revisó.')
            return {'decision': 'approve'}
        with mock.patch('marketplace.moderation._decide', side_effect=decide_then_text_changes):
            self.assertEqual(run_rating_review(rating.pk), 'stale')
        self.assertEqual(OrderRating.objects.get(pk=rating.pk).comment_status, 'pending')

    def test_a_broker_failure_never_fails_a_saved_rating(self):
        order = self.released_order()
        from .schema import RateMarketOrder
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL), \
                mock.patch('marketplace.tasks.review_rating.apply_async', side_effect=ConnectionError('redis down')), \
                self.captureOnCommitCallbacks(execute=True):
            res = RateMarketOrder.mutate.__wrapped__(None, info, order_id=str(order.public_id), rating=5,
                                                     comment='Todo bien, gracias.')
        self.assertTrue(res.success)
        self.assertEqual(OrderRating.objects.get(order=order).comment_status, 'pending')

    def test_reviewers_are_never_shown_by_an_email_derived_username(self):
        order = self.released_order()
        self.rate(order, rating=4)
        with mock.patch('inbox.community.author_display_name', return_value='miembro_x1') as name:
            self.assertEqual(self.reviews()[0].author, 'miembro_x1')
        name.assert_called()


@override_settings(**ENABLED)
class AdminEarningsTests(MarketTestBase):
    def ledger_row(self, order, fee, partner, released_at, paid_at=None, agreement=None):
        return MarketplaceFeeLedger.objects.create(
            order=order, country_code='BO', gross_usd=Decimal(fee) * 12, fee_usd=Decimal(fee),
            partner_agreement=agreement, partner_share_usd=Decimal(partner),
            confio_share_usd=Decimal(fee) - Decimal(partner), released_at=released_at, partner_paid_at=paid_at)

    def test_earnings_by_month_pending_fees_and_what_the_partner_is_owed(self):
        import dataclasses
        from datetime import timedelta
        from config.admin_dashboard_sections import Window, comprar
        from users.analytics import ARG_TZ
        # A fixed mid-month clock: "this month" must not depend on when the test runs.
        now = timezone.now().astimezone(ARG_TZ).replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        window = dataclasses.replace(Window.current(), now=now, rolling_30_start=now - timedelta(days=30))
        jason = MarketplacePartnerAgreement.objects.create(
            partner_name='Jason', country_code='BO', share_bps=5000, started_at=now - timedelta(days=90))
        orders = []
        for _ in range(3):
            self.buyer = make_user()
            self.prepare()
            orders.append(Order.objects.filter(buyer=self.buyer).get())
        self.ledger_row(orders[0], '8.00', '4.00', now - timedelta(minutes=5), agreement=jason)              # unpaid
        self.ledger_row(orders[1], '2.00', '1.00', now - timedelta(days=70), paid_at=now - timedelta(days=40),
                        agreement=jason)                                                                      # paid
        Order.objects.filter(pk=orders[2].pk).update(status='funded', amount_usd=Decimal('50.00'), fee_bps=800)

        ctx = comprar(window)
        all_time = ctx['comprar_earnings'][-1]
        self.assertEqual((all_time['orders'], all_time['fee'], all_time['confio'], all_time['partner']),
                         (2, Decimal('10.00'), Decimal('5.00'), Decimal('5.00')))
        self.assertEqual(ctx['comprar_earnings'][0]['fee'], Decimal('8.00'))  # this month: only the recent one
        self.assertEqual(ctx['comprar_pending_fees']['fee'], Decimal('4.00'))  # 8% of 50 in escrow, not earned
        [row] = ctx['comprar_partner_rows']
        self.assertEqual((row['accrued'], row['paid'], row['unpaid'], row['unpaid_orders']),
                         (Decimal('5.00'), Decimal('1.00'), Decimal('4.00'), 1))
        self.assertIsNotNone(row['last_paid'])


@override_settings(**ENABLED)
class StoreDeliveryPriceTests(MarketTestBase):
    def test_the_order_total_is_product_plus_the_stores_delivery_and_the_fee_is_on_the_total(self):
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('2.20'))
        self.product.refresh_from_db()
        terms = checkout.checkout_quote(self.product, 2, 'BO', 'La Paz')
        q = terms['quote']
        self.assertEqual((q.product_usd, q.delivery_usd, q.amount_usd), (Decimal('60.00'), Decimal('2.20'), Decimal('62.20')))
        self.assertEqual(q.fee_usd, Decimal('4.976'))  # 8% of the whole order, like the contract
        self.assertEqual(q.merchant_net_usd, Decimal('62.20') - Decimal('4.976'))

    def test_another_city_pays_the_stores_other_cities_price(self):
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('2.20'),
                                                      outside_delivery_price_usd=Decimal('5.00'))
        self.product.refresh_from_db()
        q = checkout.checkout_quote(self.product, 1, 'BO', 'Cochabamba')['quote']
        self.assertEqual((q.delivery_usd, q.amount_usd), (Decimal('5.00'), Decimal('35.00')))

    def test_the_order_records_its_delivery_and_a_new_delivery_price_never_reuses_an_old_draft(self):
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('2.20'))
        first, _calls, _ = self.prepare()
        self.assertEqual((first.delivery_usd, first.amount_usd), (Decimal('2.20'), Decimal('32.20')))
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('3.00'))
        second, _calls, _ = self.prepare()
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(second.amount_usd, Decimal('33.00'))

    def test_a_store_sets_its_delivery_price_within_bounds(self):
        from .schema import UpdateMarketStore
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            ok = UpdateMarketStore.mutate.__wrapped__(None, info, delivery_price_usd='1.5')
            bad = UpdateMarketStore.mutate.__wrapped__(None, info, delivery_price_usd='-1')
            free = UpdateMarketStore.mutate.__wrapped__(None, info, delivery_price_usd='0')
        self.assertTrue(ok.success)
        self.assertEqual(bad.error, 'bad_delivery_price')
        self.assertEqual(free.store.delivery_price_usd, '0.00')

    def test_the_suggestion_converts_the_city_estimate_and_rounds_up(self):
        from .pricing import suggested_delivery_usd
        with mock.patch('marketplace.pricing.local_per_usd', return_value=Decimal('11.925')):
            self.assertEqual(suggested_delivery_usd('BO', 'La Paz'), Decimal('1.30'))  # 15 Bs ≈ 1.258 → 1.30
        with mock.patch('marketplace.pricing.local_per_usd', return_value=None):
            self.assertEqual(suggested_delivery_usd('BO', 'La Paz'), Decimal('2.00'))


@override_settings(**ENABLED)
class DeliveryCityMatchTests(MarketTestBase):
    def test_spelling_never_turns_the_same_city_into_another_one(self):
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('1.30'), ships_outside_city=True)
        self.product.refresh_from_db()
        for spelling in ('La  Paz', 'la paz', ' LA PAZ ', 'Lá Paz'):
            q = checkout.checkout_quote(self.product, 1, 'bo', spelling)['quote']
            self.assertEqual(q.delivery_usd, Decimal('1.30'), spelling)

    def test_a_new_order_records_no_courier_estimate(self):
        order, _calls, _ = self.prepare()
        self.assertIsNone(order.delivery_estimate_local)

    def test_non_finite_delivery_prices_are_refused(self):
        from .schema import _delivery_price
        for value in ('NaN', 'Infinity', '-0.01', '100.01', 'abc'):
            self.assertIsNone(_delivery_price(value), value)
        self.assertEqual(_delivery_price('0'), Decimal('0.00'))



@override_settings(**ENABLED)
class DeliveryAreaTests(MarketTestBase):
    def setUp(self):
        super().setUp()
        MarketplaceCity.objects.filter(pk=self.city.pk).update(delivery_area='BO-LA-PAZ')
        self.el_alto, _ = MarketplaceCity.objects.update_or_create(
            country_code='BO', city='El Alto',
            defaults={'currency_code': 'BOB', 'is_live': False, 'delivery_area': 'BO-LA-PAZ'})
        Store.objects.filter(pk=self.store.pk).update(delivery_price_usd=Decimal('1.30'))
        self.product.refresh_from_db()

    def test_el_alto_is_the_la_paz_area_at_the_city_price(self):
        terms = checkout.checkout_quote(self.product, 1, 'BO', 'El Alto')
        self.assertFalse(terms['outside_city'])
        self.assertEqual(terms['quote'].delivery_usd, Decimal('1.30'))
        order, _, _ = self.prepare(delivery_city='El Alto')  # a store with no other-cities price
        self.assertFalse(order.delivery_outside_city)

    def test_el_alto_buyers_see_the_la_paz_stores_and_el_alto_reads_as_live(self):
        from .schema import Query
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        products = Query.resolve_marketplace_products(None, info, country_code='BO', city='El Alto')
        self.assertIn(self.product.pk, [int(p.id) for p in products])
        self.assertTrue(Query._city_type(self.el_alto).is_live)

    def test_a_city_outside_the_area_is_still_another_city(self):
        MarketplaceCity.objects.update_or_create(country_code='BO', city='Cochabamba',
                                                 defaults={'currency_code': 'BOB', 'is_live': False})
        self.assertTrue(checkout.is_outside_city(self.store, 'BO', 'Cochabamba'))

    def test_a_store_offers_other_cities_with_a_price_and_withdraws_with_an_empty_one(self):
        from .schema import UpdateMarketStore
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            on = UpdateMarketStore.mutate.__wrapped__(None, info, outside_delivery_price_usd='4')
            self.assertEqual(on.store.outside_delivery_price_usd, '4.00')
            self.assertTrue(Store.objects.get(pk=self.store.pk).ships_outside_city)
            off = UpdateMarketStore.mutate.__wrapped__(None, info, outside_delivery_price_usd='')
        self.assertIsNone(off.store.outside_delivery_price_usd)
        self.assertFalse(Store.objects.get(pk=self.store.pk).ships_outside_city)


@override_settings(**ENABLED)
class DeliveryAreaEdgeTests(MarketTestBase):
    def setUp(self):
        super().setUp()
        MarketplaceCity.objects.filter(pk=self.city.pk).update(delivery_area='BO-LA-PAZ')
        MarketplaceCity.objects.update_or_create(
            country_code='BO', city='El Alto',
            defaults={'currency_code': 'BOB', 'is_live': False, 'delivery_area': 'BO-LA-PAZ'})

    def test_an_el_alto_store_sells_with_the_la_paz_area(self):
        Store.objects.filter(pk=self.store.pk).update(city='El Alto')
        self.product.refresh_from_db()
        from .schema import Query
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        listed = [int(p.id) for p in Query.resolve_marketplace_products(None, info, country_code='BO', city='La Paz')]
        self.assertIn(self.product.pk, listed)
        order, _, _ = self.prepare(delivery_city='La Paz')  # not city_not_live
        self.assertFalse(order.delivery_outside_city)

    def test_another_country_is_never_quoted_at_the_domestic_price(self):
        Store.objects.filter(pk=self.store.pk).update(outside_delivery_price_usd=Decimal('4.00'))
        self.product.refresh_from_db()
        with self.assertRaisesMessage(checkout.CheckoutError, 'store_country_only'):
            checkout.checkout_quote(self.product, 1, 'AR', 'Buenos Aires')

    def test_an_older_builds_bare_other_cities_switch_asks_for_a_price(self):
        from .schema import UpdateMarketStore
        info = SimpleNamespace(context=SimpleNamespace(user=self.seller))
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            res = UpdateMarketStore.mutate.__wrapped__(None, info, ships_outside_city=True)
        self.assertEqual(res.error, 'outside_delivery_price_required')



class ReviewerLanguageTests(SimpleTestCase):
    """Comprar replaces Comunidad's policy when it calls the shared reviewer,
    and with it Comunidad's "reason in Spanish" rule: each Comprar policy must
    carry its own (sellers saw English rejection reasons until 2026-10-23)."""

    def test_every_comprar_policy_asks_for_the_reason_in_spanish(self):
        from .moderation import PRODUCT_POLICY, REVIEW_POLICY
        for policy in (PRODUCT_POLICY, REVIEW_POLICY):
            self.assertIn('Latin American Spanish', policy)
            self.assertIn('"reason"', policy)

    def test_both_passes_send_the_exact_comprar_policy_for_listings_and_reviews(self):
        from . import moderation
        for policy in (moderation.PRODUCT_POLICY, moderation.REVIEW_POLICY):
            with mock.patch('inbox.community._call_reviewer', return_value={'decision': 'escalate'}) as call, \
                    mock.patch('inbox.community._needs_escalation', return_value=True):
                moderation._decide('Title: Chompa', object(), policy=policy)
            self.assertEqual(call.call_count, 2)  # first pass + escalation
            self.assertTrue(all(c.kwargs['policy'] is policy for c in call.call_args_list))

    def test_every_comprar_policy_keeps_the_untrusted_content_rule(self):
        from .moderation import PRODUCT_POLICY, REVIEW_POLICY
        for policy in (PRODUCT_POLICY, REVIEW_POLICY):
            self.assertIn('UNTRUSTED USER CONTENT', policy)


@override_settings(**ENABLED)
class DeliveryPinTests(MarketTestBase):
    LA_PAZ = (-16.4955, -68.1336)       # Sopocachi
    COCHABAMBA = (-17.3935, -66.1570)

    def setUp(self):
        super().setUp()
        MarketplaceCity.objects.filter(pk=self.city.pk).update(
            latitude=Decimal('-16.500000'), longitude=Decimal('-68.150000'), radius_km=40)

    def test_a_pin_with_a_reference_replaces_the_written_address(self):
        order, _, _ = self.prepare(delivery_address='', delivery_note='Puerta verde frente a la tienda Rosa',
                                   delivery_latitude=self.LA_PAZ[0], delivery_longitude=self.LA_PAZ[1])
        self.assertEqual((float(order.delivery_latitude), float(order.delivery_longitude)), self.LA_PAZ)

    def test_a_pin_alone_still_needs_a_reference(self):
        with self.assertRaisesMessage(checkout.CheckoutError, 'delivery_address_required'):
            self.prepare(delivery_address='', delivery_latitude=self.LA_PAZ[0], delivery_longitude=self.LA_PAZ[1])

    def test_the_area_price_needs_a_pin_in_the_area(self):
        with self.assertRaisesMessage(checkout.CheckoutError, 'pin_outside_area'):
            self.prepare(delivery_latitude=self.COCHABAMBA[0], delivery_longitude=self.COCHABAMBA[1])

    def test_nonsense_coordinates_are_refused(self):
        for lat, lng in ((91, 0), (0, 181), ('NaN', 0), (1, None)):
            with self.assertRaisesMessage(checkout.CheckoutError, 'bad_location_pin'):
                checkout.clean_pin(lat, lng)

    def test_two_pin_only_book_entries_in_one_city_are_two_places(self):
        from .address_book import SaveDeliveryAddress
        info = SimpleNamespace(context=SimpleNamespace(user=self.buyer))
        args = dict(country_code='BO', city='La Paz', address='', phone='+591 70000000', note='Casa de la abuela')
        with mock.patch('marketplace.schema._jwt', return_value=PERSONAL):
            a = SaveDeliveryAddress.mutate.__wrapped__(None, info, latitude=-16.4955, longitude=-68.1336, **args)
            b = SaveDeliveryAddress.mutate.__wrapped__(None, info, latitude=-16.5200, longitude=-68.1100, **args)
        self.assertTrue(a.success and b.success, (a.error, b.error))
        self.assertNotEqual(a.address.id, b.address.id)
        self.assertEqual(a.address.latitude, -16.4955)


    def test_another_city_needs_the_pin_in_that_city_or_at_least_the_country(self):
        Store.objects.filter(pk=self.store.pk).update(outside_delivery_price_usd=Decimal('4.00'))
        MarketplaceCity.objects.update_or_create(
            country_code='BO', city='Cochabamba',
            defaults={'currency_code': 'BOB', 'is_live': False, 'latitude': Decimal('-17.393500'),
                      'longitude': Decimal('-66.157000'), 'radius_km': 40})
        order, _, _ = self.prepare(delivery_city='Cochabamba', delivery_latitude=self.COCHABAMBA[0],
                                   delivery_longitude=self.COCHABAMBA[1])
        self.assertTrue(order.delivery_outside_city)
        with self.assertRaisesMessage(checkout.CheckoutError, 'pin_outside_area'):  # "Cochabamba", pin in La Paz
            self.prepare(delivery_city='Cochabamba', delivery_latitude=self.LA_PAZ[0], delivery_longitude=self.LA_PAZ[1])
        with self.assertRaisesMessage(checkout.CheckoutError, 'pin_outside_area'):  # unknown town, pin in Lima
            self.prepare(delivery_city='Pueblo Nuevo', delivery_latitude=-12.0464, delivery_longitude=-77.0428)


@override_settings(**ENABLED)
class AdultsOnlyTests(MarketTestBase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        from .models import AGE_RESTRICTED_CACHE_KEY, MarketplaceCategory
        MarketplaceCategory.objects.update_or_create(key='bebidas_alcoholicas', defaults={
            'label': 'Vinos, cervezas y licores', 'group': 'Comida envasada', 'age_restricted': True})
        cache.delete(AGE_RESTRICTED_CACHE_KEY)
        self.addCleanup(cache.delete, AGE_RESTRICTED_CACHE_KEY)
        Product.objects.filter(pk=self.product.pk).update(category='bebidas_alcoholicas', title='Vino tinto Tannat')
        # A licensed store, at a time alcohol may be sold (hour rules have their own tests).
        Store.objects.filter(pk=self.store.pk).update(
            alcohol_license_status='approved', alcohol_license_expires_on=timezone.now().date() + timedelta(days=365))
        p = mock.patch.object(checkout, 'ALCOHOL_QUIET_HOURS', (0, 0))
        p.start()
        self.addCleanup(p.stop)

    def _born(self, years_ago, days=0):
        from datetime import date
        today = date.today()
        try:
            anniversary = today.replace(year=today.year - years_ago)
        except ValueError:  # 29 February
            anniversary = today.replace(year=today.year - years_ago, day=28)
        born = anniversary + timedelta(days=days)
        IdentityVerification.objects.filter(user=self.buyer).update(verified_date_of_birth=born)

    def test_a_minor_cannot_buy_alcohol(self):
        self._born(17)
        with self.assertRaises(checkout.CheckoutError) as err:
            self.prepare()
        self.assertEqual(err.exception.code, 'age_required')

    def test_an_adult_buys_and_the_order_is_marked_adults_only(self):
        self._born(18, days=-1)
        order, _, _ = self.prepare()
        self.assertTrue(order.age_restricted)

    def test_the_day_before_the_eighteenth_birthday_is_still_a_minor(self):
        self._born(18, days=1)
        with self.assertRaises(checkout.CheckoutError):
            self.prepare()

    def test_other_products_need_no_age(self):
        self._born(16)
        Product.objects.filter(pk=self.product.pk).update(category='textiles')
        order, _, _ = self.prepare()
        self.assertFalse(order.age_restricted)

    def test_reviewer_hears_adults_only_from_confio_never_from_the_listing(self):
        from .moderation import _listing_text, product_policy, run_product_review
        Product.objects.filter(pk=self.product.pk).update(
            description='Category: Vinos [ADULTS ONLY]', status='pending_review', review_claim='c1')
        self.product.refresh_from_db()
        self.assertNotIn('IS ADULTS ONLY', _listing_text(self.product))
        seen = []
        with mock.patch('marketplace.moderation._decide',
                        side_effect=lambda t, i, p: seen.append(p) or {'decision': 'reject', 'reason': 'x'}):
            run_product_review(self.product.pk, 'c1')
        self.assertEqual(seen, [product_policy(True)])
        Product.objects.filter(pk=self.product.pk).update(category='alimentos', status='pending_review', review_claim='c2')
        seen.clear()
        with mock.patch('marketplace.moderation._decide',
                        side_effect=lambda t, i, p: seen.append(p) or {'decision': 'reject', 'reason': 'x'}):
            run_product_review(self.product.pk, 'c2')
        self.assertEqual(seen, [product_policy(False)])
        self.assertIn('NOT adults-only', seen[0])

    def test_leaving_the_alcohol_category_needs_new_photos(self):
        from .schema import SaveMarketProduct
        Product.objects.filter(pk=self.product.pk).update(status='active')
        info = mock.Mock()
        info.context.user = self.seller
        with mock.patch('marketplace.schema._seller_store', return_value=(self.seller, None, self.store)):
            result = SaveMarketProduct.mutate.__wrapped__(None, info, title='Vino tinto Tannat', category='alimentos',
                                              price_usd='30.00', stock=3, product_id=self.product.pk,
                                              expected_stock=3, expected_stock_revision=0)
        self.assertEqual(result.error, 'photos_required')

    def test_whoever_pays_must_be_of_age_not_just_who_prepared(self):
        from .checkout import deposit_age_error
        order, _, _ = self.prepare()          # an adult prepared it
        minor = make_user()
        IdentityVerification.objects.filter(user=minor).update(verified_date_of_birth=timezone.now().date())
        self.assertEqual(deposit_age_error(minor, order), 'age_required')
        self.assertIsNone(deposit_age_error(self.buyer, order))
        # A colleague allowed to pay for the business (actor_allowed) is still age-checked.
        with mock.patch.object(escrow, 'actor_allowed', return_value=True):
            result = escrow.submit_action(minor, order, 'deposit', 0, int(timezone.now().timestamp()) + 600, '0x', None)
        self.assertEqual(result, {'success': False, 'error': 'age_required'})

    def test_a_category_flagged_after_checkout_still_gates_the_payment(self):
        from .checkout import deposit_age_error
        Product.objects.filter(pk=self.product.pk).update(category='alimentos')
        self._born(16)
        order, _, _ = self.prepare()
        self.assertFalse(order.age_restricted)
        Product.objects.filter(pk=self.product.pk).update(category='bebidas_alcoholicas')
        order.product.refresh_from_db()
        self.assertEqual(deposit_age_error(self.buyer, order), 'age_required')
        self._born(30)
        self.assertIsNone(deposit_age_error(self.buyer, order))
        order.refresh_from_db()
        self.assertTrue(order.age_restricted)  # the seller is told to check ID

    def test_birthdays_count_in_the_store_country_not_utc(self):
        from datetime import date, datetime, timezone as dt_tz
        from .checkout import is_of_age
        IdentityVerification.objects.filter(user=self.buyer).update(verified_date_of_birth=date(2008, 10, 27))
        # 02:00 UTC on 27 Oct is still 26 Oct (22:00) in La Paz: not yet 18 there.
        with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 10, 27, 2, 0, tzinfo=dt_tz.utc)):
            self.assertFalse(is_of_age(self.buyer, 'BO'))
        with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 10, 27, 5, 0, tzinfo=dt_tz.utc)):
            self.assertTrue(is_of_age(self.buyer, 'BO'))

    def test_seller_is_told_to_hand_it_only_to_an_adult(self):
        from notifications.models import Notification
        from .notifications import ADULTS_NOTE, order_status_changed
        order, _, _ = self.prepare()
        order.status = 'funded'
        order_status_changed(order, 'depositing')
        seller_note = Notification.objects.filter(user=self.seller).latest('id')
        self.assertTrue(seller_note.message.endswith(ADULTS_NOTE.strip()))


@override_settings(**ENABLED)
class AlcoholRulesTests(AdultsOnlyTests):
    """Ley 259: licence (art. 4/7), quiet hours (art. 17), ley seca."""

    def _adult(self):
        IdentityVerification.objects.filter(user=self.buyer).update(verified_date_of_birth=date(1990, 1, 1))

    def _code(self):
        with self.assertRaises(checkout.CheckoutError) as err:
            self.prepare()
        return err.exception.code

    def test_no_sale_without_a_current_licence(self):
        self._adult()
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_status='pending')
        self.assertEqual(self._code(), 'store_license_required')
        Store.objects.filter(pk=self.store.pk).update(
            alcohol_license_status='approved', alcohol_license_expires_on=timezone.now().date() - timedelta(days=2))
        self.assertEqual(self._code(), 'store_license_required')
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_expires_on=None)
        self.assertEqual(self._code(), 'store_license_required')  # approved needs an expiry to count

    def test_unlicensed_alcohol_is_hidden_from_buyers(self):
        from .schema import _visible_products
        Product.objects.filter(pk=self.product.pk).update(status='active')
        self.assertTrue(_visible_products().filter(pk=self.product.pk).exists())
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_status='rejected')
        self.assertFalse(_visible_products().filter(pk=self.product.pk).exists())

    def test_quiet_hours_03_to_09(self):
        from datetime import datetime, timezone as dt_tz
        self._adult()
        with mock.patch.object(checkout, 'ALCOHOL_QUIET_HOURS', (3, 9)):
            # 08:30 in La Paz (UTC-4) = 12:30 UTC: closed. 09:00 local: open.
            with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 10, 27, 12, 30, tzinfo=dt_tz.utc)):
                self.assertEqual(self._code(), 'alcohol_hours')
            with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 10, 27, 13, 0, tzinfo=dt_tz.utc)):
                self.assertTrue(self.prepare()[0].age_restricted)

    def test_ley_seca_pauses_the_city(self):
        self._adult()
        MarketplaceCity.objects.filter(pk=self.city.pk).update(alcohol_sales_paused=True)
        self.assertEqual(self._code(), 'alcohol_paused')

    def test_ley_seca_matches_any_spelling_and_unknown_destinations(self):
        from .checkout import ley_seca_error
        MarketplaceCity.objects.update_or_create(country_code='BO', city='El Alto', defaults={
            'currency_code': 'BOB', 'alcohol_sales_paused': True})
        self.assertEqual(ley_seca_error('BO', ['La Paz', 'el  ALTO']), 'alcohol_paused')
        self.assertEqual(ley_seca_error('BO', ['La Paz', 'Pueblo Desconocido']), 'alcohol_paused')
        self.assertIsNone(ley_seca_error('BO', ['La Paz']))
        self.assertEqual(ley_seca_error('BO', ['La Paz', '  ']), 'alcohol_paused')
        self.assertEqual(ley_seca_error('BO', ['La Paz', '🍷']), 'alcohol_paused')
        # One delivery area (a La Paz label may carry an El Alto pin): paused together.
        MarketplaceCity.objects.filter(country_code='BO', city__in=['La Paz', 'El Alto']).update(delivery_area='BO-LA-PAZ')
        self.assertEqual(ley_seca_error('BO', ['La Paz']), 'alcohol_paused')
        MarketplaceCity.objects.filter(country_code='BO', city__in=['La Paz', 'El Alto']).update(delivery_area='')
        MarketplaceCity.objects.filter(city='El Alto').update(alcohol_sales_paused=False)
        self.assertIsNone(ley_seca_error('BO', ['La Paz', 'Pueblo Desconocido']))

    def test_a_paid_alcohol_order_does_not_ship_during_ley_seca(self):
        from .checkout import ship_alcohol_error
        self._adult()
        order, _, _ = self.prepare()
        order.status = 'funded'
        MarketplaceCity.objects.filter(pk=self.city.pk).update(alcohol_sales_paused=True)
        self.assertEqual(ship_alcohol_error(order), 'alcohol_paused')
        with mock.patch.object(escrow, 'actor_allowed', return_value=True):
            result = escrow.submit_action(self.seller, order, 'ship', 0, int(timezone.now().timestamp()) + 600, '0x', None)
        self.assertEqual(result, {'success': False, 'error': 'alcohol_paused'})

    def test_payment_rechecks_licence_hours_and_ley_seca(self):
        from .checkout import deposit_age_error
        self._adult()
        order, _, _ = self.prepare()
        MarketplaceCity.objects.filter(pk=self.city.pk).update(alcohol_sales_paused=True)
        self.assertEqual(deposit_age_error(self.buyer, order), 'alcohol_paused')
        MarketplaceCity.objects.filter(pk=self.city.pk).update(alcohol_sales_paused=False)
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_status='rejected')
        order.store.refresh_from_db()
        self.assertEqual(deposit_age_error(self.buyer, order), 'store_license_required')

    def test_listing_alcohol_needs_the_licence(self):
        from .schema import SaveMarketProduct
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_status='none')
        self.store.refresh_from_db()
        info = mock.Mock()
        info.context.user = self.seller
        with mock.patch('marketplace.schema._seller_store', return_value=(self.seller, None, self.store)):
            result = SaveMarketProduct.mutate.__wrapped__(None, info, title='Cerveza artesanal', category='bebidas_alcoholicas',
                                                          price_usd='3.00', stock=3, photo_keys=[f'marketplace/pending/{self.seller.id}/a.jpg'])
        self.assertEqual(result.error, 'alcohol_license_required')

    def test_renewal_keeps_the_current_licence_selling(self):
        from .schema import SubmitAlcoholLicense
        info = mock.Mock()
        info.context.user = self.seller
        key = f'marketplace/pending/{self.seller.id}/licence.jpg'
        self.store.refresh_from_db()  # the licensed store from setUp
        with mock.patch('marketplace.schema._seller_store', return_value=(self.seller, None, self.store)):
            self.assertTrue(SubmitAlcoholLicense.mutate.__wrapped__(None, info, photo_key=key).success)
        self.store.refresh_from_db()
        self.assertEqual(self.store.alcohol_license_status, 'approved')
        self.assertEqual(self.store.alcohol_license_key, key)
        Store.objects.filter(pk=self.store.pk).update(alcohol_license_status='rejected')
        self.store.refresh_from_db()
        with mock.patch('marketplace.schema._seller_store', return_value=(self.seller, None, self.store)):
            self.assertTrue(SubmitAlcoholLicense.mutate.__wrapped__(None, info, photo_key=key).success)
        self.store.refresh_from_db()
        self.assertEqual(self.store.alcohol_license_status, 'pending')
        with mock.patch('marketplace.schema._seller_store', return_value=(self.seller, None, self.store)):
            self.assertEqual(SubmitAlcoholLicense.mutate.__wrapped__(None, info, photo_key='elsewhere/x.jpg').error,
                             'bad_photo')
