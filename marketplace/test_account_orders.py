"""Orders a Cuenta inteligente pays through the escrow's depositFrom (hands-off
purchases from the chat): the payer-bound digest, the order itself, and a
refund that lands back in the account — reported as such, never as money in
the wallet."""
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from eth_utils import keccak

from . import checkout, escrow
from .models import DeliveryAddress, Order
from .tests import CUSD, ENABLED, ESCROW, MarketTestBase

ACCOUNT = '0x' + '5a' * 20


@override_settings(**ENABLED)
class DepositFromDigestTests(MarketTestBase):
    def test_matches_the_eip712_reference_and_binds_the_payer(self):
        from eth_account.messages import encode_typed_data
        order_id = keccak(text='y').hex()
        buyer, merchant = '0x' + 'b1' * 20, '0x' + 'a1' * 20
        ours = escrow.deposit_from_digest(order_id, buyer, ACCOUNT, merchant, CUSD, 5 * 10**18, 800, 1_700_000_000)
        typed = {
            'types': {
                'EIP712Domain': [{'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'},
                                 {'name': 'chainId', 'type': 'uint256'},
                                 {'name': 'verifyingContract', 'type': 'address'}],
                'DepositFrom': [{'name': 'orderId', 'type': 'bytes32'}, {'name': 'buyer', 'type': 'address'},
                                {'name': 'payer', 'type': 'address'}, {'name': 'merchant', 'type': 'address'},
                                {'name': 'token', 'type': 'address'}, {'name': 'amount', 'type': 'uint256'},
                                {'name': 'feeBps', 'type': 'uint16'}, {'name': 'deadline', 'type': 'uint256'}],
            },
            'primaryType': 'DepositFrom',
            'domain': {'name': 'ConfioMarketEscrow', 'version': '1', 'chainId': 56, 'verifyingContract': ESCROW},
            'message': {'orderId': bytes.fromhex(order_id), 'buyer': buyer, 'payer': ACCOUNT, 'merchant': merchant,
                        'token': CUSD, 'amount': 5 * 10**18, 'feeBps': 800, 'deadline': 1_700_000_000},
        }
        signable = encode_typed_data(full_message=typed)
        self.assertEqual(ours, keccak(b'\x19' + signable.version + signable.header + signable.body))
        other = escrow.deposit_from_digest(order_id, buyer, '0x' + '5b' * 20, merchant, CUSD, 5 * 10**18, 800,
                                           1_700_000_000)
        self.assertNotEqual(ours, other)
        self.assertNotEqual(ours, escrow.deposit_digest(order_id, buyer, merchant, CUSD, 5 * 10**18, 800,
                                                        1_700_000_000))


@override_settings(**ENABLED)
class AccountOrderTests(MarketTestBase):
    def setUp(self):
        super().setUp()
        self.account = self.buyer.accounts.get(account_type='personal')
        self.delivery = DeliveryAddress.objects.create(
            user=self.buyer, account=self.account, country_code='BO', city='La Paz',
            address='Av. Arce 2345, Sopocachi', phone='+59170000000', is_default=True)

    def account_order(self):
        return checkout.prepare_account_order(self.buyer, self.account, payer=ACCOUNT, product_id=self.product.pk,
                                              quantity=1, delivery=self.delivery)

    def test_signed_over_deposit_from_with_the_owner_as_buyer(self):
        order = self.account_order()
        self.assertEqual((order.status, order.payer_address, order.deposit_calls), ('draft', ACCOUNT, []))
        self.assertEqual(order.buyer_address, self.account.bsc_address.lower())
        self.assertEqual(escrow.recover_signer(escrow.order_digest(order), order.deposit_signature).lower(),
                         order.deposit_signer)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)                    # reserved like any checkout

    def test_no_face_per_order_but_identity_holds_stop_it(self):
        escrow.deposit_step_up.reset_mock()
        self.account_order()
        escrow.deposit_step_up.assert_not_called()
        with mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value='identity_hold'), \
                self.assertRaisesMessage(checkout.CheckoutError, 'identity_hold'):
            self.account_order()

    def test_the_wallet_can_never_pay_an_account_order(self):
        order = self.account_order()
        out = escrow.submit_action(self.buyer, order, 'deposit', 1, int(timezone.now().timestamp()) + 300, '0x')
        self.assertEqual(out['error'], 'order_not_payable')

    def test_wallet_checkout_neither_reuses_nor_supersedes_it(self):
        account_order = self.account_order()
        order, _calls, _ = self.prepare()
        self.assertNotEqual(order.pk, account_order.pk)
        account_order.refresh_from_db()
        self.assertEqual(account_order.status, 'draft')


@override_settings(**ENABLED)
class AccountRefundTests(MarketTestBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(escrow, 'settlement_time', side_effect=lambda o, s, b: (timezone.now(), b))
        p.start()
        self.addCleanup(p.stop)
        account = self.buyer.accounts.get(account_type='personal')
        delivery = DeliveryAddress.objects.create(user=self.buyer, account=account, country_code='BO',
                                                  city='La Paz', address='Av. Arce 2345', phone='+59170000000')
        self.order = checkout.prepare_account_order(self.buyer, account, payer=ACCOUNT, product_id=self.product.pk,
                                                    quantity=1, delivery=delivery)

    def chain(self, state, block):
        o = self.order
        return {'buyer': o.buyer_address, 'merchant': o.merchant_address, 'amount': int(o.amount_wei),
                'token': o.token_address, 'fee_bps': o.fee_bps, 'state': state, 'ship_by': 1_900_000_000,
                'release_at': 0, 'disputed_at': 0, 'block': block, 'block_time': 2_000_000_000}

    def test_refund_lands_in_the_account_in_history_and_notice(self):
        from users.models_unified import UnifiedTransactionTable as U
        with mock.patch('notifications.utils.create_notification') as notify:
            escrow.sync_order(self.order, self.chain('funded', 100))
            self.order.refresh_from_db()
            escrow.sync_order(self.order, self.chain('refunded', 110))
        buy = U.objects.get(payment_reference_id=f'comprar:{self.order.pk}:buy')
        refund = U.objects.get(payment_reference_id=f'comprar:{self.order.pk}:refund')
        self.assertEqual((buy.from_address, buy.sender_address), (ACCOUNT, ACCOUNT))
        self.assertEqual((refund.to_address, refund.counterparty_address), (ACCOUNT, ACCOUNT))
        self.assertIn('Cuenta inteligente', refund.description)
        self.assertNotEqual(refund.to_address, self.order.buyer_address)
        messages = [c.kwargs['message'] for c in notify.call_args_list if c.kwargs['user'] == self.buyer]
        self.assertTrue(any('desde tu Cuenta inteligente' in m for m in messages))
        self.assertTrue(any('a tu Cuenta inteligente' in m for m in messages))
        self.assertEqual(escrow.refund_recipient(self.order), ACCOUNT)

    def test_a_wallet_order_still_refunds_the_wallet(self):
        order, _calls, _ = self.prepare()
        self.assertEqual(escrow.refund_recipient(order), order.buyer_address.lower())
        self.assertEqual(Order.objects.get(pk=order.pk).payer_address, '')



@override_settings(**ENABLED)
class AccountOrderListingTests(MarketTestBase):
    def test_no_pay_button_and_not_listed_while_the_account_has_not_paid(self):
        from .schema import MarketplaceOrderType, Query
        account = self.buyer.accounts.get(account_type='personal')
        delivery = DeliveryAddress.objects.create(user=self.buyer, account=account, country_code='BO',
                                                  city='La Paz', address='Av. Arce 2345', phone='+59170000000')
        order = checkout.prepare_account_order(self.buyer, account, payer=ACCOUNT, product_id=self.product.pk,
                                               quantity=1, delivery=delivery)
        self.assertEqual(MarketplaceOrderType.from_model(order, self.buyer, account).available_actions, [])
        with mock.patch('marketplace.schema._ctx', return_value=(self.buyer, account)):
            listed = Query().resolve_my_market_orders(None, role='buyer')
        self.assertNotIn(str(order.public_id), [str(o.id) for o in listed])
        wallet_order, _calls, _ = self.prepare()
        self.assertEqual(MarketplaceOrderType.from_model(wallet_order, self.buyer, account).available_actions,
                         ['deposit'])
