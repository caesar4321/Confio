"""The real decoder on real pictures: what is read, and what never is."""
import io

from django.test import SimpleTestCase

from agent_tasks import countries, qr
from agent_tasks.cdp import Picture
from agent_tasks.tests.base import CODE


def screen(*codes, boxes=(), scale=1.0, invert=False):
    import qrcode
    from PIL import Image, ImageOps
    image = Image.new('RGB', (int(412 * scale), int(915 * scale)), (255, 255, 255))
    for text, left, top, side in codes:
        made = qrcode.make(text).get_image().convert('RGB').resize((int(side * scale), int(side * scale)))
        image.paste(made, (int(left * scale), int(top * scale)))
    if invert:
        image = ImageOps.invert(image)
    out = io.BytesIO()
    image.save(out, format='PNG')
    return Picture(url='', png=out.getvalue(), boxes=tuple(boxes), scale=scale)


class DecoderTests(SimpleTestCase):
    def test_a_whole_pix_code_at_phone_sizes(self):
        for side in (160, 200, 260, 320):
            with self.subTest(side=side):
                self.assertEqual(qr.texts(screen((CODE, 40, 100, side))), {CODE})

    def test_high_density_and_dark_mode(self):
        self.assertEqual(qr.texts(screen((CODE, 40, 100, 200), scale=2.0)), {CODE})
        self.assertEqual(qr.texts(screen((CODE, 40, 100, 200), invert=True)), {CODE})

    def test_what_is_embedded_is_never_read(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                seen = screen((CODE, 10, 20, 190), ('embedded', 215, 20, 190), boxes=((215, 20, 405, 210),), scale=scale)
                self.assertEqual(qr.texts(seen), {CODE})
                self.assertEqual(qr.texts(screen((CODE, 10, 20, 190), boxes=((10, 20, 200, 210),), scale=scale)), set())

    def test_every_qr_on_screen_is_seen(self):
        both = qr.texts(screen((CODE, 10, 20, 190), ('https://loja.com.br/app', 215, 20, 190)))
        self.assertEqual(both, {CODE, 'https://loja.com.br/app'})
        self.assertEqual(countries.RAILS['BR'].codes(both), {CODE})

    def test_half_a_qr_is_no_qr(self):
        self.assertEqual(qr.texts(screen((CODE, 300, 100, 220))), set())
        self.assertEqual(qr.texts(screen()), set())

    def test_its_size_on_the_page_is_known(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                (text, side), = qr.read(screen((CODE, 40, 100, 200), scale=scale))
                self.assertEqual(text, CODE)
                self.assertTrue(150 < side < 200, side)

    def test_the_decoder_is_there(self):
        self.assertTrue(qr.available())
