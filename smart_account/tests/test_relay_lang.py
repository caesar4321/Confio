"""Hands-off results are told in the person's language (es / pt / en), amounts as the chat writes them."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from assistant.trades import money
from inbox.models import SupportConversation, SupportMessage
from smart_account import relay_purchases, relay_trades
from smart_account.models import SmartRelayTrade
from smart_account.tests.base import SmartAccountTestCase

TX = '0x' + 'cd' * 32


class RelayLanguageTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('ana')
        self.own = self.make_account(self.user)
        patcher = mock.patch('assistant.service.post_system_note')
        self.note = patcher.start()
        self.addCleanup(patcher.stop)

    def row(self, lang='', conversation_id=None, **extra):
        meta = {'lang': lang} if lang else {}
        values = dict(user=self.user, smart_account=self.own, nonce=f'n{SmartRelayTrade.objects.count()}',
                      side='buy', asset_kind='stock', ticker='AAPLon', amount_usd=Decimal('1.01'), meta=meta,
                      status='sent', tx_hash=TX, conversation_id=conversation_id)
        values.update(extra)
        return SmartRelayTrade.objects.create(**values)

    def said(self):
        return self.note.call_args[0][1]

    def test_the_lang_is_kept_with_the_gates_headers(self):
        self.assertEqual(relay_trades.kept_meta({'HTTP_CF_IPCOUNTRY': 'BO', 'HTTP_X_EVIL': 'x'}, 'en'),
                         {'HTTP_CF_IPCOUNTRY': 'BO', 'lang': 'en'})
        self.assertEqual(relay_trades.kept_meta({}, 'klingon'), {})

    def test_a_buy_done_is_told_in_each_language_with_its_money(self):
        for lang, expected in (('en', 'Done: I bought AAPL for US$1.01 from your Cuenta inteligente.'),
                               ('pt', 'Pronto: comprei AAPL por US$1,01 pela sua Cuenta inteligente.'),
                               ('es', 'Listo: compré AAPL por US$1,01 desde tu Cuenta inteligente.')):
            row = self.row(lang)
            relay_trades._end(row, 'done', '', note='done_buy', what='AAPL', spent=money(Decimal('1.01'), lang))
            self.assertTrue(self.said().startswith(expected), (lang, self.said()))

    def test_finish_formats_the_amount_per_language(self):
        row = self.row('en')
        relay_tx = SimpleNamespace(status='confirmed', signed_tx_hash=TX)
        with mock.patch('smart_account.models.SmartAccountRelayTx.objects') as relays, \
                mock.patch('smart_account.relay_trades.chain.receipt', return_value={'logs': []}):
            relays.filter.return_value.first.return_value = relay_tx
            relay_trades.finish(row.pk)
        self.assertEqual(self.said(), 'Done: I bought AAPL for US$1.01 from your Cuenta inteligente. It is there now.')

    def test_without_a_stored_lang_the_chat_messages_decide(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.user.accounts.first())
        SupportMessage.objects.create(conversation=conversation, sender_type='USER',
                                      body='please buy one dollar of apple stock for me')
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', body='yes do it')
        row = self.row(conversation_id=conversation.id)
        self.assertEqual(relay_trades.lang_of(row), 'en')
        relay_trades._end(row, 'failed', 'x')
        self.assertIn("I couldn't do it now", self.said())

    def test_spanish_when_nothing_says_otherwise(self):
        row = self.row()
        self.assertEqual(relay_trades.lang_of(row), 'es')
        relay_trades._end(row, 'failed', 'x', note='market_closed')
        self.assertIn('el mercado de acciones está cerrado', self.said())

    def test_every_result_has_three_languages(self):
        for table in (relay_trades.MESSAGES, relay_purchases.MESSAGES):
            for key, texts in table.items():
                self.assertEqual(set(texts), {'es', 'pt', 'en'}, key)

    def test_a_purchase_done_in_english(self):
        row = SimpleNamespace(pk=0, internal_id='p1', status='done', user=self.user, meta={'lang': 'en'},
                              conversation_id=None, created_at=None, order_id=None)
        with mock.patch('smart_account.relay_purchases.card', return_value={}):
            relay_purchases._post(row, 'done', what='Café', spent='US$12.50')
        self.assertTrue(self.said().startswith('Done: I bought Café for US$12.50 from your Cuenta inteligente.'))
