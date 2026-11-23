"""Where a task may start and where it may go: the boundary that contains a hostile page."""
from django.test import SimpleTestCase

from agent_tasks import sites, stores

ML, MP = 'mercadolivre.com.br', 'https://www.mercadopago.com.br'


class SiteTests(SimpleTestCase):
    def test_a_store(self):
        self.assertEqual(sites.store('https://www.mercadolivre.com.br/x'), ML)
        self.assertEqual(sites.store('loja.myshopify.com'), 'loja.myshopify.com')
        self.assertEqual(sites.store('loja.emp.br'), 'loja.emp.br')

    def test_never_stores(self):
        for value in ('itau.com.br', 'nubank.com.br', 'www.bb.com.br', 'receita.fazenda.gov.br', 'gmail.com',
                      'mail.google.com', 'google.com', 'confio.lat', 'mercadopago.com.br', '127.0.0.1', 'localhost',
                      'com.br', 'emp.br', 'mercadoshops.com.br', 'workers.dev', 'myvtex.com', 'wordpress.com',
                      'bancointer.com.br', 'c6bank.com.br', 'sicredi.com.br', 'safra.com.br', 'stone.com.br',
                      'pagseguro.uol.com.br', 'revolut.com', 'proton.me', 'metadata.google.internal',
                      '10.0.0.5.nip.io', 'xn--mercadlivre-3ij.com', 'açaídaana.com.br', 'caixa.com.br', 'stone.com', 'yampi.io', 'http://loja.com.br',
                      'https://user:pw@loja.com.br', 'https://loja.com.br:8443', 'loja com br'):
            with self.subTest(value=value):
                self.assertIsNone(sites.store(value))

    def test_the_boundary(self):
        self.assertTrue(sites.within('https://produto.mercadolivre.com.br/p', ML))
        for url in ('https://mercadolivre.com.br.evil.com/', 'https://evil.com/mercadolivre.com.br',
                    'https://mercadolivre.com.br@evil.com/', 'http://mercadolivre.com.br/', 'javascript:alert(1)',
                    'data:text/html,x', '', f'https://www.{ML}/money-out;x'):
            with self.subTest(url=url):
                self.assertFalse(sites.within(url, ML))
        self.assertFalse(sites.within('https://atacante.emp.br/', 'loja.emp.br'))
        self.assertFalse(sites.within('https://b.workers.dev/', 'a.workers.dev'))
        self.assertFalse(sites.within('https://outra.myshopify.com/', 'loja.myshopify.com'))

    def test_the_payment_house_is_only_ever_the_persons(self):
        for path in ('checkout/v1/redirect', 'payments/123/ticket'):
            with self.subTest(path=path):
                self.assertFalse(sites.within(f'{MP}/{path}', ML))
                self.assertTrue(sites.within(f'{MP}/{path}', ML, house=True))
                self.assertFalse(sites.within(f'{MP}/{path}', 'amazon.com.br', house=True))
        for path in ('home', 'pix/transferir', 'banking/pix', 'cards', '%6Doney-out', 'checkout/../home',
                     'checkout/%2e%2e/home', 'checkout/%252e%252e/home', 'checkout/..%5Chome', 'checkout/..\\home'):
            with self.subTest(path=path):
                self.assertFalse(sites.within(f'{MP}/{path}', ML, house=True))


class ChooseTests(SimpleTestCase):
    def test_the_store_the_person_named_wins(self):
        texts = ['compra um cabo no mercado livre']
        self.assertEqual(stores.choose('amazon.com.br', texts), ML)
        self.assertEqual(stores.choose(None, texts), ML)

    def test_the_models_own_address_never_counts(self):
        self.assertIsNone(stores.choose('mercadolivre-ofertas.com', ['compra um cabo']))
        self.assertIsNone(stores.choose('lojadajoana.com.br', ['compra um cabo']))
        self.assertIsNone(stores.choose(None, ['compra um cabo']))
        self.assertEqual(stores.choose('kabum.com.br', ['compra um cabo']), 'kabum.com.br')

    def test_an_address_the_person_wrote(self):
        self.assertEqual(stores.choose(None, ['compra na lojadajoana.com.br']), 'lojadajoana.com.br')
        self.assertIsNone(stores.choose(None, ['garrafa azul.grande']))
        self.assertEqual(stores.written(['compra em açaídaana.com.br']), set())
        self.assertEqual(stores.written(['compra em rnercadolivre.com']), set())

    def test_look_alikes(self):
        for site in ('mercadolivre-ofertas.com', 'rnercadolivre.com', 'mercado1ivre.com.br', 'shoppee.com.br',
                     'kabum-ofertas.com.br', 'amazon-promo.shop', 'meli-ofertas.com.br', 'mercado.livre-ofertas.com',
                     'amazonofertas.com.br', 'magaluofertas.com.br', 'kabumofertas.com.br', 'shopeebrasil.com.br',
                     'ofertasshopee.com.br', 'lojaamazonbr.com.br', 'promokabum.com.br', 'ofertaifood.com.br'):
            with self.subTest(site=site):
                self.assertTrue(stores.imitates(site))
        for site in (ML, 'lojadajoana.com.br', 'garrafasnorte.com.br', 'pet-food.com.br', 'healthy-food.com.br',
                     'newshoes.com.br', 'user-store.com', 'amazonia.org.br', 'cafedaamazonia.com.br',
                     'brennerferragens.com.br', 'abuser.com.br'):
            with self.subTest(site=site):
                self.assertFalse(stores.imitates(site))


class OrdinaryWordTests(SimpleTestCase):
    def test_shops_with_ordinary_words(self):
        for value in ('caixa-de-som.com.br', 'neon-led.com.br', 'pedra-stone.com.br', 'xp-games.com.br'):
            with self.subTest(value=value):
                self.assertEqual(sites.store(value), value)
