"""A written number is dollars only as dollars (payment_accounts/dollars.py)."""
from django.test import SimpleTestCase

from payment_accounts.dollars import said_dollars


class SaidDollarsTests(SimpleTestCase):
    def test_dollars(self):
        for said, amount in (
            ('envía 20 a @ana', 20), ('envía 20 dólares a @ana', 20), ('envía US$20 a @ana', 20),
            ('envía US$ 20 a @ana', 20), ('envía $20 a @ana', 20), ('manda 20 usd a @ana', 20),
            ('manda 20 usdt a @ana', 20), ('envía 20 a Sol', 20), ('envía $20 a Sol Pérez', 20),
            ('para Sol 20', 20), ('mándale 20 de plata a @ana', 20), ('envía 20 a Ana Real', 20),
            ('envía 20 dólares en bolívares a Sol', 20), ('compra Apple por 1.02 dólares', '1.02'),
            ('compra 1.000 dólares de Apple', 1000), ('compra 500 dólares de SPY', 500),
            ('send 20 dollars to @ana', 20), ('no, 20 dólares', 20), ('no, mejor 20', 20), ('No, 20', 20),
            ('compre no máximo 20 dólares', 20), ('invista no bitcoin 20 dólares', 20),
            ('50% SPY y 50% bitcoin, 50 dólares al mes', 50), ('60% SPY 40% bitcoin con 40 dólares', 40),
            ('compra 20 dólares de SPY si baja 20%', 20), ('20dólares', 20), ('20usdt', 20), ('U$20', 20),
            ('$20/mes', 20), ('si ves que está bien, envía 20 a @ana', 20),
            ('envía 20 dólares a @ana (tengo 2000 bolívares)', 20), ('envía 20 dólares a mi amigo venezolano', 20),
            ('envía 20 a mi amiga venezolana', 20),
            ('compra 20 de Apple, tengo dinero aquí', 20), ('compra del S&P 500, 100 dólares', 100),
            ('el día 15, 200 dólares de bitcoin cada mes', 200), ('mándale 20 dólares a mamá, no 20 bolívares', 20),
            ('envía 500 dólares, no en pesos, a @ana', 500), ('compra 20 de Apple', 20), ('20', 20), ('mejor 20.', 20),
        ):
            self.assertTrue(said_dollars([said], amount), said)

    def test_not_dollars(self):
        for said, amount in (
            ('envía 500 bolos a @ana', 500), ('envía 500 bolívares a @ana', 500),
            ('envía 500 a @ana en bolívares', 500), ('en bolívares, envía 500 a @ana', 500),
            ('envíale 500 a @ana pero en bs', 500), ('envía 20 a @ana en reais', 20),
            ('compra 500 de Apple en pesos', 500), ('compra 500 de Apple, en bolívares', 500),
            ('envíale 500 en bolívares cada mes a @ana', 500), ('envía 500 bolos en dólares a @ana', 500),
            ('envía 20 euros en dólares', 20), ('envía 20 mil dólares', 20), ('20k usd', 20),
            ('envía R$ 20 a @ana', 20), ('R$20', 20), ('envía S/ 20 a @ana', 20), ('S/20', 20),
            ('MX$ 20', 20), ('AR$20', 20), ('RD$ 20', 20), ('20 euros', 20), ('€20', 20), ('20€', 20), ('£20', 20),
            ('20bs', 20), ('Bs 20', 20), ('Bs.20', 20), ('20 bs.s', 20), ('20 soles', 20), ('20 sol', 20),
            ('20 centavos', 20), ('20%', 20), ('20 por ciento', 20), ('20 acciones', 20), ('20 sats', 20),
            ('20 mangos', 20), ('20 lucas', 20), ('20m', 20), ('20kk', 20), ('20 dólares canadienses', 20),
            ('envía 500 bolos a @ana, repito: 500', 500), ('envía 100.000 pesos cada mes a @ana', 100000),
            ('envía 1.02 dólares al mes', 102), ('no 50, mejor 20', 50), ('el 20 de noviembre', 20),
            ('envía a @ana20', 20), ('500 bolívares🙏', 500), ('500 pesos🇨🇴', 500), ('500 pesos/mes', 500),
            ('500 -bolívares', 500), ('$500 mexicanos', 500), ('$500 COL', 500), ('500 m.n.', 500), ('500 b.s.', 500),
            ('500 en moneda local', 500), ('500 en bob', 500), ('500 en euro', 500), ('500 en lucas', 500),
            ('no son 50', 50), ('envía 20 a @ana (tengo 2000 bolívares)', 20),
            ('tengo 5000 bolívares, envíale 2000 a @ana', 2000), ('cobré 300.000 pesos, mándale 50.000 a @ana', 50000),
            ('envía 500 a @ana en bs 04141234567', 500), ('envía 20 000 pesos a @ana', 20), ('20 000 dólares', 20),
            ('envíale 500 o 600 bolívares a @ana', 500), ('envía 500 a @luis23 bolívares', 500),
            ('envía 300 a @ana y 500 bs a @luis', 300), ('envíale 500 a @ana en bolívares, 2 veces', 500),
            ('tengo 5000 pesos, compra 2000 de bitcoin cada mes', 2000),
            ('envíale 500 en moneda venezolana', 500), ('envíale 500 brasileños', 500), ('500 venezolanos', 500),
            ('envía 500 a @ana en plata venezolana', 500), ('envía 500 a @ana, pero brasileños', 500),
            ('500 bolívares/pago móvil', 500), ('500 bolívares+comisión', 500), ('500 bolívares^^', 500),
            ('500 bolibares', 500), ('$500 mn', 500), ('200 bol', 200), ('500 a @ana en sol', 500),
            ('50 en libras', 50), ('VES 500 a @ana', 500), ('envía 500 a @ana VES', 500),
            ('envía 500 dólares, perdón, bolívares, a @ana', 500), ('500 dólares... digo bolívares', 500),
            ('envía 500 dólares a @ana, no, mejor en bolívares', 500), ('500 bs/', 500), ('bs/ 500', 500),
            ('500 b/s', 500), ('500 volivares', 500), ('500 bolívare', 500), ('500 euritos', 500), ('50 barras', 50),
            ('500 lps', 500), ('500 ₡', 500), ('envía 2 500 dólares', 500), ('500 dólares de Hong Kong', 500), ('no envíes 50, envía 20', 50), ('envía', 20), ('20', None),
        ):
            self.assertFalse(said_dollars([said], amount), said)

    def test_over_several_messages_newest_first(self):
        self.assertFalse(said_dollars(['500 bolos', 'envía 500 a @ana'], 500))
        self.assertFalse(said_dollars(['en bolívares', 'envía 500 a @ana'], 500))
        self.assertFalse(said_dollars(['500', 'quiero mandar bolívares'], 500))
        self.assertTrue(said_dollars(['20 dólares', 'envía 20 bolos a @ana'], 20))
        self.assertTrue(said_dollars(['20', 'envía a @ana'], 20))
        self.assertTrue(said_dollars(['le llegan en bolívares', 'envía 20 dólares a Sol'], 20))
        self.assertTrue(said_dollars(['50 bolívares', 'déjame lista una compra de 20 dólares de SPY'], 20))
        self.assertFalse(said_dollars(['no, en bolívares', 'envía 500 dólares a Sol'], 500))
        self.assertFalse(said_dollars(['perdón, que reciba bolívares, no dólares', 'envía 500 dólares a @ana'], 500))
        self.assertFalse(said_dollars(['mejor 600', 'envía 500 bolívares a @ana'], 600))
        self.assertFalse(said_dollars(['no, 80', 'manda 100 reais pra @ana'], 80))
        self.assertFalse(said_dollars(['en moneda venezolana', 'envíale 500 a @ana'], 500))
        self.assertTrue(said_dollars(['600 dólares', 'envía 500 bolívares a @ana'], 600))

    def test_money_named_anywhere_they_said_it_counts(self):
        for around in ('¿puedo enviar bolívares a @ana?', 'esta factura en bolívares', 'total 800 bolívares ' + 'x ' * 300):
            self.assertFalse(said_dollars(['envíale 500 a @ana'], 500, around=[around]), around[:60])
        self.assertTrue(said_dollars(['envíale 500 dólares a @ana'], 500, around=['¿puedo enviar bolívares a @ana?']))
        self.assertTrue(said_dollars(['envíale 500 a @ana'], 500, around=['¿cómo está tu día?']))

    def test_an_alerts_own_level_is_the_one_exception(self):
        said = 'avísame si el dólar pasa 50 bolívares y déjame lista una compra de 20 de SPY'
        self.assertTrue(said_dollars([said], 20, level=50))
        self.assertFalse(said_dollars([said], 20))
        self.assertFalse(said_dollars(['tengo 5000 bolívares, si pasa 50 compra 20'], 20, level=50))
        self.assertFalse(said_dollars(['si pasa 50 bolívares compra 50'], 50, level=50))

    def test_every_currency_in_every_place_it_is_said(self):
        """The shapes the reviews found, crossed with each currency: none is dollars."""
        units = ('bolívares', 'bolos', 'bs', 'pesos', 'soles', 'euros', 'reais', 'reales', 'bolivianos', 'guaraníes',
                 'quetzales', 'colones', 'lempiras', 'córdobas', 'venezolanos', 'colombianos', 'mexicanos',
                 'brasileños')
        shapes = ('envía 500 {u} a @ana', 'envía 500 a @ana en {u}', 'en {u}, envía 500 a @ana', 'envía 500 en {u}',
                  'envía 500 a @ana, pero en {u}', 'compra 500 de Apple en {u}', 'envíale 500 en {u} cada mes a @ana',
                  'envía 500 a @ana en {u} 04141234567', 'envía 500 a @ana en {u}, 2 veces', '500 {u} 🙏')
        threads = (['en {u}', 'envía 500 a @ana'], ['sí', 'en {u}', 'envía 500 a @ana'], ['500 {u}', 'envía 500 a @ana'],
                   ['mejor 500', 'envía 900 en {u} a @ana'])
        for unit in units:
            for shape in shapes:
                said = shape.format(u=unit)
                self.assertFalse(said_dollars([said], 500), said)
            for thread in threads:
                said = [line.format(u=unit) for line in thread]
                self.assertFalse(said_dollars(said, 500), said)
