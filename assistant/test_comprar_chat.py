"""A Comprar product bought from the chat (assistant/comprar.py), through
service.ask: the model names it, code asks the total and place, and only the
exact "sí" makes the hands-off purchase (or what stands in its way)."""
import json
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from assistant import service
from assistant.tests import call_response, text_response
from marketplace.models import DeliveryAddress, MarketplaceCategory, MarketplaceCity, Product, Store
from smart_account import hands_off
from users.models import Account, User

META = {'HTTP_X_CONFIO_HOME': 'conversation', 'HTTP_X_CONFIO_VERSION': '5.4.0'}


@override_settings(OPENAI_API_KEY='test-key', MARKETPLACE_ESCROW_ADDRESS='0x' + 'e5' * 20,
                   CUSD_VAULT_ADDRESS='0x' + 'c0' * 20)
class ComprarChatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='ana_comprar', email='comprar@example.com', password='x',
                                             firebase_uid='fb-comprar', first_name='Ana', country='BO')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              bsc_address='0x' + '0a' * 20)
        seller = User.objects.create_user(username='rosa_comprar', email='rosa@example.com', password='x',
                                          firebase_uid='fb-rosa', first_name='Rosa')
        seller_account = Account.objects.create(user=seller, account_type='personal', account_index=0,
                                                bsc_address='0x' + '0b' * 20)
        MarketplaceCategory.objects.update_or_create(key='textiles', defaults={
            'label': 'Textiles', 'group': 'Artesanía', 'is_active': True})
        MarketplaceCity.objects.update_or_create(country_code='BO', city='La Paz', defaults={
            'currency_code': 'BOB', 'is_live': True})
        store = Store.objects.create(owner=seller, owner_account=seller_account, name='Tejidos Rosa',
                                     country_code='BO', city='La Paz', delivery_price_usd=Decimal('5'))
        self.product = Product.objects.create(store=store, title='Chompa de alpaca', category='textiles',
                                              price_usd=Decimal('30.00'), stock=3, status='active')
        DeliveryAddress.objects.create(user=self.user, account=self.account, label='Casa', country_code='BO',
                                       city='La Paz', address='Av. Arce 2345', phone='+59170000000', is_default=True)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        self.route = hands_off.Route('paywall')
        for target, kwargs in (
                ('smart_account.relay_purchases.enabled', {'return_value': True}),
                ('smart_account.relay_purchases.route', {'side_effect': lambda *a, **k: self.route}),
                ('assistant.trades.offered', {'return_value': False}),
                ('assistant.engine.Toolbelt.payments_ready', {'return_value': True}),
                ('assistant.first_use.due', {'return_value': False}),
                ('assistant.service.send_support_staff_push', {'return_value': None})):
            patched = mock.patch(target, **kwargs)
            patched.start()
            self.addCleanup(patched.stop)

    def say(self, body, *responses):
        with mock.patch('assistant.engine._openai_post', side_effect=list(responses)) as model:
            outcome = service.ask(self.user, self.account, None, self.jwt, body, request_meta=META)
        return outcome.reply_message, model

    def asked(self):
        reply, _model = self.say('cómprame la chompa de alpaca',
                                 call_response('propose_comprar_purchase',
                                               json.dumps({'product': 'chompa de alpaca', 'quantity': None})),
                                 text_response('Listo.'))
        return reply

    def test_code_asks_the_total_and_the_place(self):
        reply = self.asked()
        self.assertEqual(reply.body, '¿Compro Chompa de alpaca de Tejidos Rosa por US$35 (envío incluido), para '
                                     'entregar en Casa, La Paz? Escribe sí o no.')

    def test_only_the_exact_yes_goes_on_and_without_the_model(self):
        self.asked()
        reply, model = self.say('cómpralo')
        model.assert_not_called()
        self.assertEqual([a['type'] for a in reply.metadata['actions']], ['purchase_offer'])
        self.asked()
        reply, _model = self.say('no')
        self.assertEqual(reply.metadata.get('actions') or [], [])

    def test_go_makes_the_hands_off_purchase(self):
        from smart_account.models import SmartRelayPurchase
        own = mock.Mock()
        self.route = hands_off.Route('go', own=own)
        self.asked()
        with mock.patch('smart_account.relay_purchases.schedule') as scheduled:
            reply, _model = self.say('sí')
        row = SmartRelayPurchase.objects.get(user=self.user)
        self.assertEqual(reply.metadata['actions'][0]['type'], 'relay_purchase')
        self.assertEqual(row.amount_usd, Decimal('35.00'))
        scheduled.assert_called_once_with(row.pk, countdown=2)
