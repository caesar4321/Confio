"""Pages recorded from real stores (AgentTask.trace, anonymised).

What a page means is read by models (agent.judge, agent.review): their real judgment on these pages is
run against the live models by scripts/ops/eval_agent_readers.py, never here. Here: the facts code checks
on those same pages, and that the tests' stand-in readers (tests/readers.py) read them as a person would."""
import json
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from agent_tasks import operate
from agent_tasks.tests import readers

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
        self.final = next(e for e in self.page.elements if e['label'] == 'Realiza tu pedido y paga')

    def test_the_figures_code_checks_are_on_the_page(self):
        # "Total (IVA incluido, en caso de ser aplicable) $129.00"
        self.assertTrue(operate.figure_on(self.page.text, operate.amount_of('$129.00')))
        self.assertFalse(operate.figure_on(self.page.text, operate.amount_of('$130.00')))

    def test_an_address_counts_only_as_the_page_writes_it(self):
        self.assertTrue(operate.written_on(self.page.text, 'Calle Falsa 123, CENTRO, GUADALAJARA, JALISCO, 44100, México'))
        self.assertTrue(operate.written_on(self.page.text, 'calle falsa 123,  centro'))   # case and spacing aside
        self.assertFalse(operate.written_on(self.page.text, 'Calle Verdadera 9, Monterrey'))
        self.assertFalse(operate.written_on(self.page.text, ''))

    def test_a_saved_card_is_never_what_a_reader_calls_the_asked_way(self):
        read = readers.review_by_words(SimpleNamespace(country='MX'), self.page, self.final, 'Chocolate', None)
        self.assertEqual((read['places_order'], read['total']), (True, '129.00'))
        self.assertNotEqual(read['pays_with'], 'asked')


class AmazonMexicoPayTests(SimpleTestCase):
    """Choosing how to pay (/checkout/p/.../pay), with SPEI chosen and a saved card listed."""

    def setUp(self):
        self.page = recorded('amazon_mx_pay')

    def test_amazon_says_it_will_share_a_clabe_after_the_order(self):
        self.assertIn('cuenta CLABE de 18 dígitos', self.page.text)


class AmazonMexicoSpeiReviewTests(SimpleTestCase):
    """The order review page paying with SPEI: the page the founder's 10:36 run stopped on."""

    def setUp(self):
        self.page = recorded('amazon_mx_review_spei')
        self.final = next(e for e in self.page.elements if e['label'] == 'Realiza tu pedido y paga')

    def test_the_total_the_person_approves_is_written_on_it(self):
        self.assertTrue(operate.figure_on(self.page.text, operate.amount_of('$99.48')))

    def test_a_reader_calls_it_the_order_paid_by_spei(self):
        read = readers.review_by_words(SimpleNamespace(country='MX'), self.page, self.final, 'Chocolate', None)
        self.assertEqual((read['places_order'], read['pays_with'], read['total']), (True, 'asked', '99.48'))
        self.assertTrue(operate.written_on(self.page.text, read['ship_to']))
