"""The picture the second readers see: the page as it is on screen, the control inside a red box."""
import base64
import io
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

from agent_tasks import agent, page as pages
from agent_tasks.cdp import CdpError


def screenshot(width=2560, height=1440):
    out = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(out, format='JPEG')
    return base64.b64encode(out.getvalue()).decode()


class PictureTests(SimpleTestCase):
    def reader(self, box):
        browser = mock.Mock()
        browser.call.return_value = {'data': screenshot()}
        reader = pages.Reader(browser)
        reader._run = mock.Mock(return_value=box)
        return reader, browser

    def test_the_control_is_boxed_in_red_at_its_place_on_a_dense_screen(self):
        # A 1280-wide viewport drawn at twice the density, sent 1280 wide.
        reader, browser = self.reader({'x': 100, 'y': 200, 'w': 300, 'h': 50, 'vw': 1280, 'vh': 720})
        image = Image.open(io.BytesIO(reader.picture({'ref': 3, 'label': 'No gracias'})))
        self.assertEqual(image.size, (1280, 720))
        red, green, blue = image.getpixel((98, 225))        # its left edge
        self.assertTrue(red > 180 and green < 110 and blue < 110, (red, green, blue))
        self.assertEqual(image.getpixel((250, 225)), (255, 255, 255))   # inside it: the page, untouched
        self.assertEqual(browser.call.call_args.args[0], 'Page.captureScreenshot')

    def test_a_page_that_moved_while_it_was_taken_gives_no_picture(self):
        reader, _ = self.reader(None)
        first = {'x': 100, 'y': 200, 'w': 300, 'h': 50, 'vw': 1280, 'vh': 720}
        for after in ({**first, 'y': 260}, 'secret', 'changed', 'gone'):
            reader._run = mock.Mock(side_effect=[first, after])
            self.assertIsNone(reader.picture({'ref': 3}))

    def test_no_picture_is_never_a_failure(self):
        for box in ('gone', 'changed', 'secret', 'zoomed', 'too_much', None, {'x': 0, 'y': 0, 'w': 0, 'h': 0, 'vw': 1280}):
            reader, browser = self.reader(box)
            self.assertIsNone(reader.picture({'ref': 0}))
            browser.call.assert_not_called()
        reader, browser = self.reader({'x': 1, 'y': 1, 'w': 9, 'h': 9, 'vw': 1280, 'vh': 720})
        browser.call.side_effect = CdpError('gone')
        self.assertIsNone(reader.picture({'ref': 0}))


class ReadersSeeTests(SimpleTestCase):
    TASK = SimpleNamespace(site='loja.com.br', country='BR', goal='chocolate', user_id=None)

    def page(self, **over):
        return SimpleNamespace(**{'url': 'https://loja.com.br/checkout', 'title': 'Checkout', 'text': 'Total R$ 9,00',
                                  'elements': [], 'look': lambda element: b'jpeg-bytes', **over})

    def test_the_judge_gets_the_picture_beside_the_text(self):
        with mock.patch('agent_tasks.agent._call', return_value=('verdict', {'verdict': 'safe', 'why': ''})) as call:
            agent.judge(self.TASK, self.page(), {'tag': 'button', 'label': 'Continuar'}, agent.Meter())
        self.assertEqual(call.call_args.kwargs['picture'], b'jpeg-bytes')
        self.assertIn('red box', call.call_args.kwargs['system'])

    def test_never_a_picture_of_a_page_with_a_password_field_nor_a_broken_one(self):
        def broken(element):
            raise CdpError('no screen')
        for page in (self.page(secret=True), self.page(look=broken), self.page(look=lambda element: mock.Mock())):
            with mock.patch('agent_tasks.agent._call', return_value=('verdict', {'verdict': 'safe', 'why': ''})) as call:
                agent.judge(self.TASK, page, {'tag': 'button', 'label': 'Continuar'}, agent.Meter())
            self.assertIsNone(call.call_args.kwargs.get('picture'))
            self.assertNotIn('red box', call.call_args.kwargs['system'])

    def test_an_outage_is_never_asked_twice(self):
        for why in ('model answered 500', 'model answered 429', 'model request failed: ReadTimeout'):
            with mock.patch('agent_tasks.agent._call', side_effect=agent.AgentUnavailable(why)) as call:
                with self.assertRaises(agent.AgentUnavailable):
                    agent.judge(self.TASK, self.page(), {'tag': 'button', 'label': 'Pagar'}, agent.Meter())
            self.assertEqual(call.call_count, 1)

    def test_if_the_model_refuses_the_picture_the_text_alone_is_read(self):
        answers = [agent.AgentUnavailable('model answered 400'), ('verdict', {'verdict': 'card', 'why': 'x'})]
        with mock.patch('agent_tasks.agent._call', side_effect=answers) as call:
            verdict, _ = agent.judge(self.TASK, self.page(), {'tag': 'button', 'label': 'Pagar'}, agent.Meter())
        self.assertEqual((verdict, call.call_count), ('card', 2))
        self.assertIsNone(call.call_args.kwargs.get('picture'))
