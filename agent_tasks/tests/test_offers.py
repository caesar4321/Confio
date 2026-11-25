"""A search across stores (offers.py): which store each offer is at, how it is paid, the cost guard, the
tool call and "Comprar aquí". Serper is never reached: its answers are recorded shapes (2026-11-25)."""
import logging
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from agent_tasks import assistant_tool, offers, service
from agent_tasks.models import AgentTask
from agent_tasks.tests.base import RowsBase

BUILD = {'HTTP_X_CONFIO_VERSION': '5.4.0', 'HTTP_X_CONFIO_BROWSER_TASKS': '1'}
KEY = 'serper-test-key-never-logged'
OSHOP = 'https://www.google.com/search?ibp=oshop&q=x&prds=catalogid:{n},gpcid:1'


def item(title, source, price, n=1, link=None, **over):
    found = {'title': title, 'source': source, 'price': price, 'imageUrl': f'https://encrypted-tbn1.gstatic.com/s?{n}',
             'productId': str(n), 'position': n}
    if link is not False:
        found['link'] = link or OSHOP.format(n=n)
    return {**found, **over}


MX = [
    item('Audífonos Sony 1000X', 'Mercado Libre', '$6,835.97 ahora', 1, rating=4.6, ratingCount=708),
    item('Audífonos Billboard Soul Track', 'FullOffice.com', '$386.85', 2, rating=4.9, ratingCount=8),
    item('Audífonos Sony WH-CH520', 'eBay - item_title_google_cloud_translation_test_for_us_es', '$900.00', 3),
    item('Audífonos Xbox inalámbricos', 'Walmart México', '$2,499.00 ahora', 4),
    item('Audífonos JBL Tune 520', 'Coppel', '$1,199.00', 5, link=False),
    item('Audífonos JBL Tune 510', 'Mercado Libre', '$499.00', 6),
    item('Audífonos Sony WH-1000XM5', 'Liverpool', '$7,999.00', 7,
         link='https://www.google.com/url?url=https://www.liverpool.com.mx/tienda/pdp/sony/1144&sa=U'),
    item('Audífonos genéricos', 'Encuentro Todo', '$199.00', 8),
    item('Audífonos Amazon Basics', 'Amazon MX', '$350.00', 9),
]
BR = [
    item('Headphone QCY H3 Lite', 'Pichau', 'R$ 229,99', 1),
    item('Ouvido QCY H3 ANC', 'QCY.com.br', 'R$ 259,90 agora', 2),
    item('Fone Bluetooth Intra', 'Amazon.com.br - Seller', 'R$ 22,90', 3, link=False),
    item('Fone JBL Tune', 'Magalu', 'R$ 199,00', 4),
]


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


@override_settings(SERPER_API_KEY=KEY, AGENT_OFFERS_PER_HOUR=4)
class OffersBase(RowsBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.serper = self.patch('agent_tasks.offers.requests.post',
                                 side_effect=lambda url, **kw: FakeResponse(self.answer(url, kw['json'])))
        self.answers = {'shopping': {'shopping': MX}, 'search': {'organic': []}}

    def answer(self, url, body):
        return self.answers['shopping' if url == offers.SHOPPING_URL else 'search']


class WhichStoreTests(OffersBase):
    def test_google_links_are_never_the_store(self):
        found = offers.rank(MX, 'MX', limit=10)
        sites = [offer['site'] for offer in found]
        self.assertTrue(all('google' not in offer['site'] and 'google' not in offer['href'] for offer in found))
        # Each offer's store is the store Google names, in the search's country; one offer per store.
        self.assertEqual(sites, ['mercadolibre.com.mx', 'fulloffice.com', 'walmart.com.mx', 'coppel.com',
                                 'liverpool.com.mx', 'amazon.com.mx'])

    def test_an_unknown_seller_or_a_marketplace_seller_is_refused(self):
        found = {offer['store'] for offer in offers.rank(MX, 'MX', limit=10)}
        self.assertNotIn('Encuentro Todo', found)
        self.assertFalse(any(store.startswith('eBay') for store in found))

    def test_a_store_link_inside_a_google_redirect_is_the_product_page(self):
        offer = next(o for o in offers.rank(MX, 'MX', limit=10) if o['site'] == 'liverpool.com.mx')
        self.assertEqual(offer['href'], 'https://www.liverpool.com.mx/tienda/pdp/sony/1144')

    def test_an_opaque_google_link_leaves_no_product_page(self):
        offer = offers.rank(MX, 'MX', limit=10)[0]
        self.assertEqual((offer['site'], offer['href']), ('mercadolibre.com.mx', ''))

    def test_a_look_alike_link_with_an_unknown_name_is_refused(self):
        fake = item('Audífonos', 'Ofertas Amazon', '$10.00', 1, link='https://amazon-ofertas.com.mx/p/1')
        found = offers.rank([fake], 'MX')
        self.assertEqual([o['site'] for o in found], ['amazon.com.mx'])   # the real store, never the look-alike
        self.assertEqual(found[0]['href'], '')
        self.assertEqual(offers.rank([item('A', 'Tienda X', '$1.00', 1, link='https://amaz0n.com.mx/p/1')], 'MX'), [])

    def test_a_link_that_acts_is_not_opened(self):
        found = offers.rank([item('A', 'Liverpool', '$1.00', 1,
                                  link='https://www.liverpool.com.mx/cart/add?sku=1')], 'MX')
        self.assertEqual((found[0]['site'], found[0]['href']), ('liverpool.com.mx', ''))

    def test_brazil(self):
        found = offers.rank(BR, 'BR')
        self.assertEqual([o['site'] for o in found],
                         ['pichau.com.br', 'qcy.com.br', 'amazon.com.br', 'magazineluiza.com.br'])
        self.assertEqual(found[2]['image'], 'https://encrypted-tbn1.gstatic.com/s?3')

    def test_cheapest_first_when_asked(self):
        found = offers.rank(MX, 'MX', cheapest=True)
        # Mercado Libre's cheaper offer stands for that store.
        self.assertEqual([o['price'] for o in found], ['$350.00', '$386.85', '$499.00', '$1,199.00', '$2,499.00'])
        self.assertTrue(offers.cheap('busca audífonos Sony baratos'))
        self.assertTrue(offers.cheap('¿dónde está más barato?'))
        self.assertFalse(offers.cheap('audífonos sony'))

    def test_at_most_five(self):
        self.assertEqual(len(offers.rank(MX, 'MX')), 5)

    def test_stars_and_reviews_when_given(self):
        first = offers.rank(MX, 'MX')[0]
        self.assertEqual((first['rating'], first['reviews'], first['store']), ('4.6', '708', 'Mercado Libre'))


class PayLabelTests(OffersBase):
    def test_each_country(self):
        self.assertEqual(offers.pay_label('walmart.com.mx')[0], 'confio')
        self.assertEqual(offers.pay_label('magazineluiza.com.br')[0], 'confio')
        self.assertEqual(offers.pay_label('farmatodo.com.ve')[0], 'reference')
        self.assertEqual(offers.pay_label('mercadolibre.com.ar'), ('none', 'Confío aún no paga esta tienda'))
        self.assertEqual(offers.pay_label('coppel.com')[0], 'none')   # the address does not say its country

    def test_bolivia_by_its_switch(self):
        with mock.patch('agent_tasks.countries.BoliviaQrRail.manual', return_value=True):
            self.assertEqual(offers.pay_label('tienda.com.bo'), ('manual', 'La pagas tú con el QR de la tienda'))
        with mock.patch('agent_tasks.countries.BoliviaQrRail.manual', return_value=False):
            self.assertEqual(offers.pay_label('tienda.com.bo')[0], 'confio')

    def test_ranked_offers_carry_it(self):
        found = {o['site']: o['pay_text'] for o in offers.rank(MX, 'MX', limit=10)}
        self.assertEqual(found['walmart.com.mx'], 'Confío la paga')
        self.assertEqual(found['fulloffice.com'], 'Confío aún no paga esta tienda')
        # A listed ".com" store of the search's country counts as that country; an unknown one does not.
        self.assertEqual(found['coppel.com'], 'Confío la paga')
        self.assertEqual(offers.pay_label('coppel.com', searched='BR')[0], 'none')
        self.assertEqual(offers.country_of('fulloffice.com', 'MX'), '')


class CostGuardTests(OffersBase):
    def test_one_call_with_the_key_in_the_country(self):
        offers.search(self.user, 'audífonos bluetooth', 'MX')
        url, kwargs = self.serper.call_args[0][0], self.serper.call_args[1]
        self.assertEqual(url, 'https://google.serper.dev/shopping')
        self.assertEqual(kwargs['headers']['X-API-KEY'], KEY)
        self.assertEqual(kwargs['json'], {'q': 'audífonos bluetooth', 'gl': 'mx', 'hl': 'es', 'num': 20})
        offers.search(self.user, 'fone bluetooth', 'BR')
        self.assertEqual(self.serper.call_args[1]['json']['hl'], 'pt-br')

    def test_the_same_search_is_cached(self):
        first = offers.search(self.user, 'audífonos bluetooth', 'MX')
        other, _ = self.person()
        again = offers.search(other, 'Audífonos  Bluetooth', 'MX')
        self.assertEqual(self.serper.call_count, 1)
        self.assertEqual(first, again)

    @override_settings(AGENT_OFFERS_PER_HOUR=2)
    def test_a_few_per_hour(self):
        offers.search(self.user, 'uno', 'MX')
        offers.search(self.user, 'dos', 'MX')
        with self.assertRaises(offers.OffersRefused) as caught:
            offers.search(self.user, 'tres', 'MX')
        self.assertEqual(caught.exception.code, 'limit')
        offers.search(self.user, 'uno', 'MX')   # cached: free
        self.assertEqual(self.serper.call_count, 2)

    def test_no_key_no_search(self):
        with override_settings(SERPER_API_KEY=''):
            self.assertFalse(offers.available())
            with self.assertRaises(offers.OffersRefused):
                offers.search(self.user, 'uno', 'MX')
        self.serper.assert_not_called()

    def test_private_words_never_leave(self):
        with self.assertRaises(offers.OffersRefused):
            offers.search(self.user, 'audífonos para ana@correo.com', 'MX')
        self.serper.assert_not_called()

    def test_the_key_is_never_logged(self):
        self.answers['shopping'] = None
        with self.assertLogs('agent_tasks.offers', level=logging.INFO) as logs:
            offers.search(self.user, 'uno', 'MX')
            self.serper.side_effect = lambda url, **kw: FakeResponse({}, status=403)
            with self.assertRaises(offers.OffersRefused):
                offers.search(self.user, 'dos', 'MX')
        self.assertTrue(any('call' in line for line in logs.output))
        self.assertFalse(any(KEY in line for line in logs.output))


class ToolTests(OffersBase):
    def setUp(self):
        super().setUp()
        self.payable = self.patch('agent_tasks.service.require_payable')
        self.patch('agent_tasks.assistant_tool._country', return_value='MX')

    def call(self, texts, **over):
        viewer = type('Viewer', (), {'account': self.account, 'user': self.user, 'request_meta': BUILD})()
        args = {'saw_web': False, 'store': None, 'what': None, 'kind': 'compare', **over}
        return assistant_tool.call(viewer, texts, **args)

    def note(self):
        from inbox.models import SupportMessage
        return SupportMessage.objects.filter(conversation__user=self.user,
                                             metadata__notice__startswith='agent_offers:').get()

    def test_a_search_across_stores_is_a_card(self):
        result, task = self.call(['busca audífonos Sony baratos en México'], what='audífonos Sony baratos')
        self.assertIsNone(task)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['ofertas'], 5)
        # The model never reads the web's words: no title and no price in what it gets.
        self.assertNotIn('Sony 1000X', str(result))
        self.assertNotIn('$', str(result))
        self.assertEqual(self.serper.call_args[1]['json']['q'], 'audífonos Sony baratos')
        note = self.note()
        action = note.metadata['actions'][0]
        self.assertEqual(action['type'], 'offers')
        self.assertEqual(note.metadata['notice'], f"agent_offers:{action['target']}")
        self.assertEqual(len(note.metadata['agent_offers']['offers']), 5)
        self.assertIn('Comprar aquí', note.body)       # an app without the card still reads them
        self.assertEqual(AgentTask.objects.count(), 0)  # nothing started

    def test_a_store_named_in_the_newest_message_is_a_purchase_there(self):
        result, task = self.call(['búscalo en walmart'], what='audífonos')
        self.assertTrue(result['ok'], result)
        self.assertEqual((task.site, task.kind), ('walmart.com.mx', 'buy'))
        self.serper.assert_not_called()

    def test_an_older_store_does_not_decide(self):
        result, task = self.call(['¿dónde está más barato?'], recent=['compra audífonos en walmart',
                                                                       '¿dónde está más barato?'])
        self.assertIsNone(task)
        self.assertEqual(result.get('estado'), 'ofertas', result)

    def test_a_purchase_with_no_store_searches_across_stores(self):
        result, task = self.call(['compra audífonos bluetooth'], kind='buy', what='audífonos bluetooth')
        self.assertIsNone(task)
        self.assertEqual(result.get('estado'), 'ofertas', result)

    def test_nothing_found_is_said(self):
        self.answers['shopping'] = {'shopping': [MX[2], MX[7]]}
        result, _ = self.call(['busca audífonos'])
        self.assertFalse(result['ok'])

    def test_not_after_reading_the_web(self):
        result, _ = self.call(['busca audífonos'], saw_web=True)
        self.assertFalse(result['ok'])
        self.serper.assert_not_called()

    def test_the_description_says_when(self):
        spec = assistant_tool.spec()
        self.assertIn('compare', spec['parameters']['properties']['kind']['enum'])
        self.assertIn('"compare"', spec['description'])


class BuyTests(OffersBase):
    def setUp(self):
        super().setUp()
        self.payable = self.patch('agent_tasks.service.require_payable')
        self.found = offers.search(self.user, 'audífonos bluetooth', 'MX')
        self.id = offers.post(self.user, 'audífonos bluetooth', 'MX', self.found)

    def index(self, site):
        return next(i for i, offer in enumerate(self.found) if offer['site'] == site)

    def test_the_purchase_starts_at_that_store_on_its_product_page(self):
        self.answers['search'] = {'organic': [
            {'link': 'https://www.google.com/goto?url=CAESuQ', 'title': 'Audífonos Xbox inalámbricos'},
            {'link': 'https://www.walmart.com.mx/ip/otra-cosa/1', 'title': 'Cafetera de goteo'},
            {'link': 'https://www.walmart.com.mx/ip/audifonos-xbox/0008', 'title': 'Audífonos Xbox inalámbricos'}]}
        task = offers.buy(self.account, self.user, self.id, self.index('walmart.com.mx'), meta=BUILD)
        self.assertEqual((task.site, task.country, task.kind), ('walmart.com.mx', 'MX', 'buy'))
        self.assertEqual(task.pending_url, 'https://www.walmart.com.mx/ip/audifonos-xbox/0008')
        self.assertEqual(task.goal, 'Audífonos Xbox inalámbricos')
        self.assertEqual(self.serper.call_args[1]['json']['q'], 'site:walmart.com.mx Audífonos Xbox inalámbricos')
        self.assertEqual(offers.load(self.user, self.id)['picked'], self.index('walmart.com.mx'))

    def test_no_product_page_found_starts_at_the_store(self):
        task = offers.buy(self.account, self.user, self.id, self.index('mercadolibre.com.mx'), meta=BUILD)
        self.assertEqual((task.site, task.pending_url, task.history), ('mercadolibre.com.mx', '', []))
        # Looked up once only.
        calls = self.serper.call_count
        offers.buy(self.account, self.user, self.id, self.index('mercadolibre.com.mx'), meta=BUILD)
        self.assertEqual(self.serper.call_count, calls)

    def test_a_known_product_page_needs_no_search(self):
        found = [item('Audífonos Sony WH-1000XM5', 'Liverpool', '$7,999.00', 1,
                      link='https://www.google.com/url?url=https://www.liverpool.com.mx/tienda/pdp/sony/1144')]
        offers_id = offers.post(self.user, 'sony', 'MX', offers.rank(found, 'MX'))
        calls = self.serper.call_count
        task = offers.buy(self.account, self.user, offers_id, 0, meta=BUILD)
        self.assertEqual(task.pending_url, 'https://www.liverpool.com.mx/tienda/pdp/sony/1144')
        self.assertEqual(self.serper.call_count, calls)

    def test_a_listed_com_store_is_bought_as_its_country(self):
        task = offers.buy(self.account, self.user, self.id, self.index('coppel.com'), meta=BUILD)
        self.assertEqual((task.site, task.country), ('coppel.com', 'MX'))

    def test_a_country_never_overrides_the_stores_own(self):
        task = service.start(self.account, self.user, goal='audífonos', site='walmart.com.mx', meta=BUILD,
                             country='BR')
        self.assertEqual(task.country, 'MX')

    def test_a_page_outside_the_store_is_dropped_at_the_start(self):
        task = service.start(self.account, self.user, goal='audífonos', site='walmart.com.mx', meta=BUILD,
                             first_page='https://www.google.com/search?q=x', chosen='audífonos')
        self.assertEqual(task.pending_url, '')

    def test_only_the_persons_own_card(self):
        other, other_account = self.person()
        with self.assertRaises(service.TaskRefused):
            offers.buy(other_account, other, self.id, 0, meta=BUILD)
        self.assertIsNone(offers.load(other, self.id))
        for bad in (-1, 99, 'x'):
            with self.assertRaises(service.TaskRefused):
                offers.buy(self.account, self.user, self.id, bad, meta=BUILD)


class SchemaTests(OffersBase):
    def test_its_own_query_and_mutation(self):
        from agent_tasks.schema import _offers_type
        from config.schema import schema
        printed = str(schema)
        self.assertIn('agentOffers(id: UUID!): AgentOffersType', printed)
        self.assertIn('buyAgentOffer(id: UUID!, index: Int!): BuyAgentOffer', printed)
        found = offers.search(self.user, 'audífonos', 'MX')
        shown = _offers_type(offers.load(self.user, offers.post(self.user, 'audífonos', 'MX', found)))
        self.assertEqual((shown.query, shown.picked, shown.offers[0].site, shown.offers[0].pay_text),
                         ('audífonos', None, 'mercadolibre.com.mx', 'Confío la paga'))
        # The product's page stays on the server: the app sends back only which offer.
        self.assertFalse(hasattr(shown.offers[0], 'href'))
