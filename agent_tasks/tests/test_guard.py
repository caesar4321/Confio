"""The agent's three verbs, and that there is no fourth. Each case from the 2026-11-22 audits is here."""
import time

from django.test import SimpleTestCase

from agent_tasks import agent, guard
from agent_tasks.tests.base import BASE, SITE, cart_button, element, link, search_box, snap


def press(label='Adicionar ao carrinho', page=None, **over):
    return guard.press_refusal(cart_button(label, **over), page or snap(), SITE)


class PressTests(SimpleTestCase):
    def test_add_to_cart_is_pressed(self):
        for label in ('Adicionar ao carrinho', 'ADICIONAR AO CARRINHO', 'Adicionar à sacola', 'Adicione ao carrinho',
                      'Agregar al carrito', 'Añadir a la cesta', 'Add to cart', 'Colocar no carrinho'):
            with self.subTest(label=label):
                self.assertEqual(press(label), '')

    def test_boxes_are_the_persons(self):
        for label in ('Fechar', 'Agora não', 'Recusar cookies', 'No thanks'):
            with self.subTest(label=label):
                self.assertEqual(press(label), 'not_allowed')

    def test_nothing_else_is_pressed(self):
        for label in (
                'Comprar agora', 'Comprar', 'Comprar já', 'Quero comprar', 'Buy now', 'Confirmar compra', 'Confirmar',
                'Confirmar & pagar', 'Confirmar →', 'Finalizar compra', 'Fazer meu pedido', 'Pagar', 'Pague via Pix',
                'Pague no Pix', 'Continuar com Pix', 'QR Code Pix', 'Gerar código Pix', 'Continuar', 'Prosseguir',
                'Efetivar', 'Contratar plano', 'Experimente o Prime', 'Começar teste grátis', 'Ativar Meli+',
                'Alugar HD R$ 14,90', 'Enviar Pix', 'Pay with card', 'Usar este endereço e gerar cobrança', 'OK',
                'Sim', 'Aceitar cookies', 'Aceitar', 'Criar conta', 'Entrar com Google', 'Con​firmar compra',
                'Ｃomprar agora', 'Adicionar ao carrinho e finalizar', 'Adicionar cartão', 'Adicionar garantia',
                'Adicionar ao carrinho | Comprar agora', 'Comprar com 1 clique', 'Fechar pedido', 'Fechar compra',
                'Cancelar pedido', ''):
            with self.subTest(label=label):
                self.assertNotEqual(press(label), '')

    def test_only_a_button_that_is_its_own(self):
        self.assertEqual(press(tag='label'), 'not_a_button')
        self.assertEqual(press(tag='input', type='checkbox'), 'not_a_button')
        self.assertEqual(press(tag='input', type='image'), 'not_a_button')
        self.assertEqual(press(nested=True), 'inside_another_control')
        self.assertEqual(press(tag='span', role='button'), '')
        self.assertEqual(press(cut=True), 'unreadable')
        self.assertEqual(press(disabled=True), 'disabled')

    def test_what_it_submits_to_counts_whatever_it_says(self):
        for action in (f'{BASE}/place-order', f'{BASE}/checkout/buy', f'{BASE}/x?step=confirm',
                       f'{BASE}/%2570ay', 'https://evil.com/cart', 'javascript:void(0)', 'invalid:'):
            with self.subTest(action=action):
                self.assertNotEqual(press(action=action), '')
        for name in ('submit.buy-now', 'placeYourOrder1', 'buyNow', 'confirm-order'):
            with self.subTest(name=name):
                self.assertEqual(press(name=name), 'acts')
        self.assertEqual(press(action=f'{BASE}/gp/product/handle-buy-box/ref-1', name='submit.add-to-cart'), '')

    def test_nothing_is_pressed_in_a_checkout(self):
        for label in ('Adicionar ao carrinho', 'Fechar'):
            with self.subTest(label=label):
                self.assertEqual(press(label, snap(url=f'{BASE}/checkout/review')), 'checkout')


class LinkTests(SimpleTestCase):
    def test_products_and_categories_are_opened(self):
        for item in (link('Garrafa térmica Norte 750 ml R$ 79,90'),
                     link('Fone Bluetooth com cancelamento de ruído', '/fone-com-cancelamento-de-ruido/p/1'),
                     link('Finalizador de cabelo', '/finalizador-cachos/p/2'),
                     link('Aceite de oliva 500 ml', '/aceite-de-oliva/p/3'),
                     link('Camisa, frete grátis na primeira compra'),
                     link('Tênis | pague no Pix com 5% off', '/tenis/p/4?variation=2')):
            with self.subTest(label=item['label']):
                self.assertEqual(guard.link_refusal(item, SITE), '')

    def test_an_address_that_acts_is_not_opened(self):
        for path in ('/checkout', '/gz/checkout/buy?item=1', '/place-order', '/x?step=confirm', '/%70lace-order',
                     '/%2570ay', '/assinatura', '/buy-now/1', '/x#/pagamento', '/cart/delete?id=1', '/logout'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Ver', path), SITE), 'acts')

    def test_words_that_act_are_not_opened(self):
        for label in ('Comprar agora', 'Comprar com Google Pay', 'Confirmar & pagar', 'Aceitar termos',
                      'Finalizar compra', 'Cancelar compra', 'Criar conta', 'Assine o Prime', 'Entrar com Google',
                      'Comprar com 1 clique'):
            with self.subTest(label=label):
                self.assertEqual(guard.link_refusal(link(label), SITE), 'acts')

    def test_outside_the_store_is_not_opened(self):
        for href in ('https://evil.com/x', 'http://www.mercadolivre.com.br/', 'javascript:buy()',
                     'https://www.mercadopago.com.br/checkout/v1/redirect', 'https://www.mercadopago.com.br/home'):
            with self.subTest(href=href):
                self.assertEqual(guard.link_refusal(element('Ver', tag='a', href=href), SITE), 'outside_store')

    def test_only_a_link_is_opened(self):
        self.assertEqual(guard.link_refusal(element('Ver', href=f'{BASE}/p/1'), SITE), 'not_a_link')


class SearchTests(SimpleTestCase):
    GOAL = 'compra um cabo usb c, modelo 123456'

    def search(self, text='cabo usb-c 2m', page=None, **over):
        return guard.search_refusal(search_box(**over), text, page or snap(), SITE, self.GOAL)

    def test_a_search(self):
        self.assertEqual(self.search(), '')
        self.assertEqual(self.search('cabo 123456'), '')
        self.assertEqual(self.search(action='', method=''), '')

    def test_only_a_search_box_that_only_searches(self):
        for over in ({'search': False}, {'method': 'post'}, {'secret_form': True}, {'type': 'password'},
                     {'type': 'email'}, {'autocomplete': 'billing cc-number'}, {'tag': 'textarea'}):
            with self.subTest(over=over):
                self.assertEqual(self.search(**over), 'not_a_search')
        self.assertEqual(self.search(action='https://evil.com/s'), 'outside_store')
        self.assertEqual(self.search(action=f'{BASE}/checkout/coupon'), 'acts')
        self.assertEqual(self.search(page=snap(url=f'{BASE}/checkout')), 'checkout')

    def test_a_search_carries_nothing_out(self):
        for text in ('fulano@mail.com', 'https://evil.com/x', '12345678900', '987 654 321'):
            with self.subTest(text=text):
                self.assertEqual(self.search(text), 'not_said')
        for text in ('', 'a\nb', 'x' * 200):
            with self.subTest(text=text):
                self.assertEqual(self.search(text), 'bad_text')


class PageTests(SimpleTestCase):
    def test_where_the_agent_stops(self):
        for page in (snap(url=f'{BASE}/checkout/review'), snap(url=f'{BASE}/gz/checkout/buy'),
                     snap(url=f'{BASE}/app#/pagamento'), snap(url=f'{BASE}/checkouts/cn/1'), snap(url=f'{BASE}/fechamento'),
                     snap(url=f'{BASE}/buyingflow/review'), snap(url=f'{BASE}/checkoutOnePage'),
                     snap(url='https://checkout.loja.com.br/x'),
                     snap(url=f'{BASE}/revisao', elements=[element('Confirmar pedido')]),
                     snap(url=f'{BASE}/review', elements=[element('Place your order')])):
            with self.subTest(url=page.url, text=page.text):
                self.assertTrue(guard.is_checkout(page))
        for page in (snap('Ofertas do dia\nEscolha como pagar'), snap('Camisa Copa final 2026'),
                     snap('Telefone •••• 4321'), snap(url=f'{BASE}/fone-com-cancelamento/p/1'),
                     snap('Vendedor: revise seu pedido. Confirme sua compra.'),
                     snap(url=f'{BASE}/maquina-de-pagamento/p/3'), snap(url=f'{BASE}/best-buy-tv/p/4'),
                     snap(url=f'{BASE}/livro-como-pagar-dividas/p/5')):
            with self.subTest(url=page.url, text=page.text):
                self.assertFalse(guard.is_checkout(page))

    def test_the_persons_turn_and_a_block(self):
        self.assertEqual(guard.person_needed(snap(secret=True)), 'login')
        self.assertEqual(guard.person_needed(snap(captcha=True)), 'captcha')
        self.assertEqual(guard.person_needed(snap(url=f'{BASE}/gz/account-verification')), 'login')
        self.assertEqual(guard.person_needed(snap()), '')
        self.assertTrue(guard.blocked(snap('Access Denied. Reference #18')))

    def test_hostile_text_is_linear(self):
        started = time.monotonic()
        for text in ('x' * 60000, 'a' * 60000, 'comprar ' * 7000, '/buy' * 15000):
            guard.is_checkout(snap(text))
            agent.redact(text)
            guard.link_refusal(element(text[:300], tag='a', href=f'{BASE}/{text[:2000]}'), SITE)
        self.assertLess(time.monotonic() - started, 8)


class RoundThreeTests(SimpleTestCase):
    def test_products_named_like_acts_are_opened(self):
        for path in ('/fone-jbl-noise-cancel/p/1', '/s?keywords=fone+noise+cancel', '/s?k=samsung+pay',
                     '/livro-como-pagar-dividas/p/2', '/maquina-de-pagamento/p/3', '/balcao-checkout-caixa/p/4',
                     '/caneta-assinatura/p/5', '/cafeteira-one-click/p/6', '/best-buy-tv/p/7'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Produto', path), SITE), '')
        self.assertEqual(guard.link_refusal(link('Produto com um texto longo', cut=True), SITE), '')

    def test_acts_in_any_spelling(self):
        for path in ('/oneClickBuy', '/expressBuy', '/processPayment', '/placeOrderNow', '/api/payNow',
                     '/confirmPurchase', '/cancelOrder', '/createOrder', '/x?action=cancelled', '/terms/accept',
                     '/customer/account/create', '/gp/prime/pipeline/membersignup', '/log-out', '/sign-out', '/sair',
                     '/comprar', '/cancelar', '/assinaturas/nova', '/pagamentos/confirma', '/cart/remove'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Ver', path), SITE), 'acts')

    def test_every_hop_is_checked(self):
        self.assertTrue(guard.hop_allowed(f'{BASE}/p/1', 'GET', SITE))
        self.assertTrue(guard.hop_allowed(f'{BASE}/cart/add', 'POST', SITE))
        self.assertFalse(guard.hop_allowed(f'{BASE}/cart/add', 'POST', SITE, only_get=True))
        for url in ('https://evil.com/', f'{BASE}/gz/checkout/buy?item=999', f'{BASE}/placeOrderNow'):
            with self.subTest(url=url):
                self.assertFalse(guard.hop_allowed(url, 'GET', SITE))

    def test_an_ordinary_search_with_numbers(self):
        for words in ('iphone 15 128gb', 'galaxy s24 256 gb', 'rtx 4090 16gb', 'tenis nike 42 2024', 'air max 270 42'):
            with self.subTest(words=words):
                self.assertEqual(guard.search_refusal(search_box(), words, snap(), SITE, f'compra {words}'), '')
        for words in ('987 654 321', '123 456 789 00'):
            with self.subTest(words=words):
                self.assertEqual(guard.search_refusal(search_box(), words, snap(), SITE, 'compra um cabo'), 'not_said')

    def test_a_script_button_dressed_as_a_link(self):
        self.assertEqual(guard.link_refusal(element('Adicionar', tag='a', href=f'{BASE}/#'), SITE, snap()), 'same_page')


class RoundFourTests(SimpleTestCase):
    def test_platform_gets_that_act(self):
        for path in ('/index.php?route=extension/payment/cod/confirm', '/index.php?route=checkout/checkout',
                     '/my-account/?subscription_id=7&change_subscription_to=cancelled&_wpnonce=ab',
                     '/my-account/set-default-payment-method/7/?_wpnonce=ab',
                     '/my-account/delete-payment-method/7/', '/cart/?cancel_order=true&order_id=3',
                     '/orders/7?action=cancelled', '/checkout-v2/payment-step', '/checkoutSteps', '/cancelOrderNow',
                     '/place-order.json', '/fastOrder', '/pago', '/carrito/pago', '/realizar-pedido'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Ver medidas', path), SITE), 'acts')
                self.assertFalse(guard.hop_allowed(f'{BASE}{path}', 'GET', SITE))

    def test_the_way_back_of_a_sign_in_is_not_an_act(self):
        back = f'{BASE}/gz/account-verification?go=https%3A%2F%2Fwww.{SITE}%2Fp%2F1'
        self.assertTrue(guard.hop_allowed(back, 'GET', SITE))

    def test_a_closed_drawer_or_a_home_page_is_not_a_checkout(self):
        button = element('Confirmar pedido')
        self.assertFalse(guard.is_checkout(snap(url=f'{BASE}/', elements=[button])))
        self.assertFalse(guard.is_checkout(snap(url=f'{BASE}/p/1', elements=[{**button, 'on_screen': False}])))
        self.assertFalse(guard.is_checkout(snap(url=f'{BASE}/p/1', elements=[element('Finalizar compra')])))
        self.assertTrue(guard.is_checkout(snap(url=f'{BASE}/p/1', elements=[button])))

    def test_a_sellers_form_is_not_a_cart(self):
        product = snap(url=f'{BASE}/p/1')
        self.assertEqual(press(page=product, action=f'{BASE}/account/address/update', method='post'), 'not_a_cart')
        self.assertEqual(press(page=product, new_window=True), 'new_window')
        for action in (f'{BASE}/cart/add', f'{BASE}/carrinho/adicionar', f'{BASE}/gz/cart/v2'):
            with self.subTest(action=action):
                self.assertEqual(press(page=product, action=action, method='post'), '')


class RoundFiveTests(SimpleTestCase):
    def test_every_value_is_looked_at_whatever_its_name_or_length(self):
        padded = 'extension/payment/cod/confirm' + '.' * 200
        for path in ('/x?s=/order/confirm', '/x?page=checkout/confirm', '/x?p=logout', f'/index.php?route={padded}',
                     f'/go?url=https%3A%2F%2Fwww.{SITE}%2Forders%2F7%2Fcancellation', '/orders/7/cancellation',
                     '/cart/clear', '/pedido/7/repetir', '/account/address/7/default', '/aceitar-termos',
                     '/finalizar-compra-expressa'):
            with self.subTest(path=path[:60]):
                self.assertEqual(guard.link_refusal(link('Ver', path), SITE), 'acts')

    def test_ordinary_addresses_open_whole(self):
        for path in ('/index.php?route=product/product&product_id=4', '/mclics/clicks/external/MLB/count?a=xYz%2B9',
                     '/sspa/click?url=%2Fdp%2FB0ABC%2Fref%3Dsspa', '/s?rh=n%3A16209062011&node=16209062011',
                     '/busca?page_number=3', '/p/1?smid=A1XYZ&seller_id=99', '/reactivate-creme-facial/p/2'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Produto', path), SITE), '')

    def test_a_press_is_a_plain_submit_to_a_cart(self):
        self.assertEqual(press(), '')
        self.assertEqual(press(action=''), 'not_a_cart')
        self.assertEqual(press(scripted=True), 'scripted')
        for action in (f'{BASE}/minha-conta/cartao/principal', f'{BASE}/p/1', f'{BASE}/index.php?route=x/cart'):
            with self.subTest(action=action):
                self.assertNotEqual(press(action=action, page=snap(url=f'{BASE}/p/1')), '')

    def test_a_search_stays_in_this_window(self):
        self.assertEqual(guard.search_refusal(search_box(new_window=True), 'cabo', snap(), SITE, 'cabo'), 'new_window')

    def test_homes_and_routes(self):
        button = element('Confirmar pedido')
        self.assertFalse(guard.is_checkout(snap(url=f'{BASE}/br/', elements=[button])))
        self.assertTrue(guard.is_checkout(snap(url=f'{BASE}/index.php?route=checkout/checkout')))


class RoundSixTests(SimpleTestCase):
    def test_a_route_is_read_as_its_router_reads_it(self):
        for route in ('extension/paym%26ent/cod/conf%26irm', 'extension/payment/cod/conf%3Dirm',
                      'extension/payment/cod/con%3Bfirm', '.' * 5000 + 'extension/payment/cod/confirm'):
            with self.subTest(route=route[:50]):
                self.assertTrue(guard.acts(f'{BASE}/index.php?route={route}'))

    def test_ordinary_words_open(self):
        for path in ('/s?sort=default', '/default/garrafa/p/1', '/busca?q=comprar', '/p/1?layout=default',
                     '/p/1?cor=clear', '/default.aspx', '/s/Sites-loja-Site/default/Search-Show?q=garrafa'):
            with self.subTest(path=path):
                self.assertEqual(guard.link_refusal(link('Produto', path), SITE), '')

    def test_words_beside_what_they_act_on(self):
        for path in ('/conta/cartao/7/principal', '/eliminar/7', '/ativar', '/cart/clear', '/customer/account/create',
                     '/carrinho/identificacao', '/pedido/criar'):
            with self.subTest(path=path):
                self.assertTrue(guard.acts(f'{BASE}{path}'))

    def test_what_cannot_be_read_acts(self):
        self.assertTrue(guard.acts(f'{BASE}/x?u=http://[::1'))

    def test_a_way_back_is_not_a_checkout(self):
        self.assertFalse(guard.is_checkout(snap(url=f'{BASE}/entrar?redirect=/checkout')))

    def test_only_a_carts_own_endpoint(self):
        for action in (f'{BASE}/api/orders#cart', f'{BASE}/account/address.php/cart', f'{BASE}/cart/7/address',
                       f'{BASE}/cart/add?x=1'):
            with self.subTest(action=action):
                self.assertFalse(guard.cart_address(action))

    def test_while_an_act_is_sent_only_it_is_sent(self):
        action = f'{BASE}/cart/add'
        self.assertTrue(guard.sent_to('POST', action, action))
        self.assertTrue(guard.sent_to('GET', f'{BASE}/api/price'))
        self.assertFalse(guard.sent_to('POST', f'{BASE}/checkout/place-order', action))
        self.assertFalse(guard.sent_to('POST', f'{BASE}/busca'))


class RoundSevenTests(SimpleTestCase):
    def test_letters_a_router_deletes_do_not_hide_a_route(self):
        for route in ('extension/pay%C4%B0ment/cod/con%C4%B0firm', 'extension/pay%E2%84%AAment/cod/con%E2%84%AAfirm',
                      'extension/payment/cod/conf%25irm', 'account/log%C4%B0out'):
            with self.subTest(route=route):
                self.assertTrue(guard.acts(f'{BASE}/index.php?route={route}'))

    def test_suffixes_and_context(self):
        for path in ('/logout.json', '/orders/7/cancel.json', '/oferta/aceitar', '/termos-de-uso/aceitar',
                     '/account/cards/7/primary', '/enderecos/7/padrao'):
            with self.subTest(path=path):
                self.assertTrue(guard.acts(f'{BASE}{path}'))
        self.assertFalse(guard.cart_address(f'{BASE}/cart/refund'))
        self.assertTrue(guard.cart_address(f'{BASE}/gp/product/handle-buy-box/ref=dp_start-bbf_1_glance'))

    def test_a_scripts_get_can_act_too(self):
        self.assertFalse(guard.sent_to('GET', f'{BASE}/index.php?route=extension/payment/cod/confirm'))
        self.assertEqual(guard.search_refusal(search_box(action='', scripted=True), 'cabo', snap(), SITE, 'cabo'),
                         'scripted')


class RoundTenPageTests(SimpleTestCase):
    def test_woocommerce_and_hashbang_pages_differ(self):
        from agent_tasks import runner
        same = runner.same_page
        self.assertNotEqual(same(f'{BASE}/?product=garrafa'), same(f'{BASE}/?order-pay=99'))
        self.assertNotEqual(same(f'{BASE}/#!/produto/1'), same(f'{BASE}/#!/pedido/9'))
