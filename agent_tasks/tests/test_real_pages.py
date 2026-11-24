"""Code's own checks against pages recorded from real stores (AgentTask.trace, anonymised).

Every rule here was once written from an imagined page and failed on the real one. A rule that
changes is run against these before a person meets it."""
import json
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from agent_tasks import guard, operate

PAGES = Path(__file__).parent / 'pages'


def recorded(name):
    page = json.loads((PAGES / f'{name}.json').read_text())
    host = page['url'].split('/')[0]
    elements = [{**element,
                 'href': (f"https://{host}{element['href']}" if element.get('href', '').startswith('/') else
                          'javascript:void(0)' if element.get('href') == 'void(0)' else element.get('href', '')),
                 'checked': element.get('checked') == 'True', 'disabled': element.get('disabled') == 'True',
                 'on_screen': element.get('on_screen') != 'False'} for element in page['elements']]
    return SimpleNamespace(url=f"https://{page['url']}", title=page['title'], text=page['text'], elements=elements)


class AmazonMexicoReviewTests(SimpleTestCase):
    """The order review page (/checkout/p/.../spc), with a saved card selected."""

    def setUp(self):
        self.page = recorded('amazon_mx_review')
        self.on_checkout = guard.is_checkout(self.page)

    def floor(self, label):
        element = next(e for e in self.page.elements if e['label'].startswith(label))
        return guard.hard_refusal(element, on_checkout=self.on_checkout, page=self.page)

    def test_it_is_a_checkout_and_its_last_page(self):
        self.assertTrue(self.on_checkout)
        self.assertTrue(guard.final_step(self.page.text, self.page.elements))

    def test_what_the_agent_must_press_is_left_to_the_judge(self):
        # 2026-11-24: "Cambiar el método de pago" was refused for its address (/checkout/.../pay).
        for label in ('Cambiar | Cambiar el método de pago', 'Cambiar | Cambiar dirección de entrega',
                      'jueves 26 de nov | $44.00 Envío estándar', 'Cambiar fecha y hora de entrega',
                      'Carrito | Volver al carrito', 'Recolección cerca disponible'):
            with self.subTest(label=label):
                self.assertEqual(self.floor(label), '')

    def test_what_code_never_lets_through(self):
        for label, kind in (('Realiza tu pedido y paga', 'places_order'), ('Prueba Prime gratis', 'account'),
                            ('Empieza tu prueba gratis', 'account'), ('Pagar con Mastercard', 'card'),
                            ('Agregar tarjeta de regalo', 'account'),
                            ('Revisa tu opción de envío. Marca esta casilla para establecer', 'account'),
                            ('miércoles 25 de nov Envíos rápidos y GRATIS', 'account')):   # delivery with a Prime trial
            with self.subTest(label=label):
                self.assertEqual(self.floor(label), kind)

    def test_the_total_is_amazons_total_with_its_long_bracket(self):
        # "Total (IVA incluido, en caso de ser aplicable) $129.00"
        self.assertTrue(operate.total_on(self.page.text, '$129.00'))
        for other in ('$85.00', '$44.00', '$59.00'):   # the products, the shipping, another delivery
            self.assertFalse(operate.total_on(self.page.text, other), other)

    def test_a_saved_card_is_never_ordered_with(self):
        refusal = operate._method_refusal(SimpleNamespace(country='MX'), self.page)
        self.assertIn('local payment method', refusal)

    def test_the_address_is_the_orders(self):
        self.assertEqual(guard.ship_to(self.page.text),
                         'ana perez calle falsa 123, centro, guadalajara, jalisco, 44100, mexico')


class AmazonMexicoPayTests(SimpleTestCase):
    """Choosing how to pay (/checkout/p/.../pay), with SPEI chosen and a saved card listed."""

    def setUp(self):
        self.page = recorded('amazon_mx_pay')

    def floor(self, label):
        element = next(e for e in self.page.elements if e['label'].startswith(label))
        return guard.hard_refusal(element, on_checkout=True, page=self.page)

    def test_spei_and_the_way_on_are_the_models(self):
        for label in ('Transferencia electrónica (Finaliza tu pago con SPEI', 'Usar este método de pago',
                      'Revisar el pedido'):
            with self.subTest(label=label):
                self.assertEqual(self.floor(label), '')

    def test_amazon_says_it_will_share_a_clabe_after_the_order(self):
        self.assertIn('cuenta CLABE de 18 dígitos', self.page.text)


class AmazonMexicoSpeiReviewTests(SimpleTestCase):
    """The order review page paying with SPEI: the page the founder's 10:36 run stopped on."""

    def setUp(self):
        self.page = recorded('amazon_mx_review_spei')
        self.final = next(e for e in self.page.elements if e['label'] == 'Realiza tu pedido y paga')

    def test_a_checkout_address_is_never_a_products_page(self):
        # /checkout/p/p-000…/spc: that "p" refused the final button as "on a product page".
        self.assertFalse(guard.product_address(self.page.url))
        self.assertTrue(guard.product_address('https://www.amazon.com.mx/De-la-Rosa/dp/B0X'))
        self.assertTrue(guard.product_address('https://tienda.mx/p/123'))

    def test_spei_is_read_as_the_method_after_the_address_s_own_cambiar(self):
        # "… Cambiar  Pagando con SPEI  Agregar tarjeta de regalo …"
        self.assertEqual(operate._method_refusal(SimpleNamespace(country='MX'), self.page), '')

    def test_the_final_button_is_named_never_pressed_and_the_total_is_the_pages(self):
        self.assertTrue(guard.final_looking(self.final))
        self.assertEqual(guard.hard_refusal(self.final, on_checkout=True, page=self.page), 'places_order')
        self.assertTrue(operate.total_on(self.page.text, '$99.48'))
        self.assertFalse(operate.total_on(self.page.text, '$55.48'))
