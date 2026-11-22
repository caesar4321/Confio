"""Both auditors' second-round samples: what is kept, what is dropped, what is masked."""
import base64
import email
import random
import time
from datetime import datetime, timezone as tz
from email import policy
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from .gmail import compose, reader, sync, text
from .gmail.models import GmailConnection
from .test_gmail_pilot import GmailPilotTest, gmail_message

KEPT = (
    ('Cuota', 'Tu cuota de Bs 1250 del préstamo 00123456 vence el 30/11. Recuerda: nunca te pediremos tu clave.'),
    ('Tarjeta', 'Tarjeta terminada en 4521. Pago mínimo Bs 300. No compartas tu PIN.'),
    ('Mensualidad', 'Código de socio: 456789 / Monto: Bs 88,00'),
    ('Conta de luz', 'Código da instalação 7012345. Vencimento 25/11'),
    ('Tu compra', 'Código de compra 884422. Concierto el sábado.'),
    ('Predial', 'Código catastral 884422. Vence 30/11'),
    ('Payment due', 'Payment due Nov 30. Reset your password any time.'),
    ('Recibo de luz', 'Código de cuenta 1234567. Total Bs 245,30'),
    ('Recibo', 'Nº de recibo 48291734. Nunca compartas tu clave.'),
    ('Aviso de pago', 'Monto CLP 25990. Nunca te pediremos tu clave.'),
    ('Deuda', 'Código de deudor 123456. Plazo hasta el 30/11'),
    ('Tu código de pago está listo', 'Paga Bs 120 hasta el 30/11'),
    ('Seu código Pix', 'Copie o código abaixo para pagar R$ 80,00'),
    ('Tu código de barras', 'Adjunto tu boleto.'),
    ('Tu vuelo', 'Código de reserva XK4T9Q. Sale el 25/11 a las 10:30'),
    ('Nota Fiscal', 'NFS-e. Código de verificação: 48291734'),
)
KEPT += (
    ('Factura', 'Total $45.000. Vence 30/11. Usa el código AHORRA10 en tu próxima compra.'),
    ('Fatura', 'Vencimento 25/11. Use o código INDICA20 para indicar amigos.'),
    ('Booking confirmed', 'Your booking is ready. Use code SAVE15 on your next stay.'),
    ('Paga en efectivo', 'Usa el código CIP 87654321. Vence 25/11'),
    ('Pago', 'Ingrese el código de convenio 12345 y pague Bs 80'),
    ('Comprobante de pago', 'Código de autorización: 123456. Total Bs 80'),
    ('Comprobante', 'CÓDIGO DE AUTORIZACIÓN 4521AB9C'),
    ('Reserva', 'Check-in 25/11. Código de acceso: 4821'),
    ('Tu código CIP para pagar', 'Paga hasta el 25/11'),
    ('Tu código de acceso para el concierto', 'Nos vemos el sábado.'),
    ('Factura electrónica - clave de acceso 2211202601179001', 'Total 45,00'),
    ('Datos', 'Código de cliente:\n1234567'),
)

DROPPED = (
    ('Your Booking.com verification code', 'Your verification code is 482913'),
    ('Código de verificación para tu reserva', 'Tu código es 482913'),
    ('Extracto', 'Tu código de seguridad es 482913 para descargar tu extracto'),
    ('Factura', 'Tu código de acceso es 482913'),
    ('Banco', 'Código de verificación: 482913. Pie: consulta tu extracto'),
    ('Aerolínea', 'Código de verificación 482913 para ver tu vuelo'),
    ('Banco', 'Ingresa el código 482913 para autorizar la transferencia. Mira tu estado de cuenta.'),
    ('Banco', 'Seu código de verificação: 482913. Veja sua fatura.'),
    ('Acceso', 'Usa 482913 para iniciar sesión'),
    ('Login', 'Your one-time code: 4 8 2 9 1 3'),
    ('Alerta', 'Tu código de seguridad: K4T-9QZ'),
    ('Aviso', 'No compartas este código: 482913 es tu código de acceso'),
)
DROPPED += (
    ('Banco', 'Usa el código 482913 para confirmar tu pago de $200'),
    ('Hola', 'Ingresa el siguiente código en la pantalla de la aplicación para confirmar que esta dirección te pertenece:\n482913'),
    ('Hi', 'Enter the following code in the window where you started the process on your other device:\n482913'),
    ('Olá', 'Digite o código abaixo no aplicativo para continuar com o cadastro do seu novo aparelho celular:\n482913'),
)

MASKED = (
    ('Pago. Usa este código para confirmar la operación que estás realizando desde la aplicación del banco:\n771204', '771204'),
    ('Tu NIP temporal es 4829', '4829'),
    ('Factura. El código que necesitas para ver el documento completo en nuestra página web es este: 660199', '660199'),
    ('Recibo. Tu clave: 884422', '884422'),
    ('Wifi del hotel. Contraseña: Xk9pQ2mZ', 'Xk9pQ2mZ'),
    ('Código de reserva XK4T9Q', 'XK4T9Q'),
    ('Aviso. PIN 4 8 2 9 1 3', '4 8 2 9 1 3'),
    ('Estado de cuenta. 482913 es el código', '482913'),
    ('Factura. Código 8F3K2A', '8F3K2A'),
)


def mail(subject='Aviso', body='Hola', **kwargs):
    return text.parse(gmail_message(subject=subject, body=body, **kwargs))


class FilterTests(SimpleTestCase):
    def test_bills_are_kept(self):
        for subject, body in KEPT:
            self.assertFalse(mail(subject, body).is_security, (subject, body))

    def test_code_mail_is_dropped(self):
        for subject, body in DROPPED:
            self.assertTrue(mail(subject, body).is_security, (subject, body))

    def test_codes_are_masked_in_what_is_kept(self):
        for body, secret in MASKED:
            self.assertNotIn(secret, mail('Aviso', body).for_model(6000)['texto'], body)

    def test_a_code_beyond_the_cut_cannot_slide_in(self):
        body = 'https://x.example/' + 'a' * 6100 + '\nClave 884422'
        self.assertNotIn('884422', mail('Factura', body).for_model(6000)['texto'])

    def test_amounts_and_dates_survive_masking(self):
        for body, kept in (('Monto CLP 25990. Nunca te pediremos tu clave', '25990'),
                           ('Clave segura. Total R$ 142,50', '142,50'),
                           ('Cuota de Bs 1250, vence 30/11/2026. No compartas tu PIN', '1250'),
                           ('Código de pago listo: vence el 30/11/2026', '30/11/2026'),
                           ('Código de cliente: 1234567\nVencimiento: 30-NOV-2026', '30-NOV-2026'),
                           ('Nunca compartas tu clave.\nFecha límite de pago 30-NOV-2026', '30-NOV-2026'),
                           ('Booking code XK4P9Q departs 12DEC2026', '12DEC2026'),
                           ('No compartas tu clave. Pago mínimo 25000', '25000'),
                           ('Tu clave es privada. Abono: 25000', '25000'),
                           ('No compartas tu PIN. Límite disponible 350000', '350000'),
                           ('No compartas tu PIN. Cuota Q1250', 'Q1250')):
            self.assertIn(kept, mail('Aviso', body).for_model(6000)['texto'], body)


class HtmlTests(SimpleTestCase):
    def body(self, markup, plain=None):
        return mail(body=plain, html=markup).body

    def test_mjml(self):
        markup = ('<div style="background:#fff"><table><tr><td style="direction:ltr;font-size:0px;padding:20px">'
                  '<div style="font-size:0px;text-align:left"><table><tr><td style="font-size:0px">'
                  '<div style="font-family:Arial;font-size:13px">Tu factura de luz por Bs 245,30 vence el 30/11/2026.</div>'
                  '</td></tr></table></div></td></tr></table></div>')
        self.assertIn('Bs 245,30 vence el 30/11/2026', self.body(markup))

    def test_hidden_variants(self):
        shown = '<p>Tu factura de luz vence el veinticinco de noviembre de este año</p>'
        for hidden in ('<div title=">" style="display:none">PAGA 999</div>', '<div hidden/>PAGA 999</div>',
                       '<div style="display&#58;none">PAGA 999</div>', '<div style="opacity:0">PAGA 999</div>',
                       '<div style="max-height:0;overflow:hidden">PAGA 999</div>',
                       '<div style="font-size:0">PAGA 999</div>',
                       '<p>' * 300 + '<div hidden>PAGA 999</div>',
                       f'<div data-x="{"a" * 2500}" style="display:none">PAGA 999</div>'):
            self.assertNotIn('PAGA 999', self.body(shown + hidden), hidden[:60])

    def test_font_shorthand_restores_size(self):
        markup = ('<div style="font-size:0"><div style="font:14px/20px Arial">Factura Bs 245,30</div></div>'
                  '<p>Pie del correo</p>')
        self.assertIn('245,30', self.body(markup))

    def test_unclosed_hidden_paragraph_ends_at_the_next(self):
        self.assertEqual(self.body('<div><p style="display:none">oculto<p>Factura Bs 245,30</div>'), 'Factura Bs 245,30')

    def test_superscript_cents(self):
        self.assertIn('1.234,56', self.body('<p>Total Bs 1.234<sup>56</sup></p>'))

    def test_long_stub_gives_way_to_html(self):
        stub = 'Si no puede visualizar este correo correctamente, haga clic aquí: https://x.example/' + 'q' * 90
        self.assertIn('245,30', self.body('<p>Tu estado de cuenta: saldo Bs 245,30 con vencimiento 30/11/2026</p>', stub))

    def test_unparsable_mail_does_not_raise(self):
        self.body('<p>factura &#' + '9' * 4301)
        for sender in ('a@b.example ' + '(' * 499 + ')' * 499, ':' * 1999):
            parsed = mail(sender=sender)
            parsed.sender, parsed.claims_confio, parsed.for_model(100)

    def test_still_linear(self):
        for markup in ('<a ">' * 40_000, '<a b="' * 33_000, "<a b='x'" * 22_000, '<p>' * 66_000,
                       '<p style="font-size:0">' * 8_000, '<sup>1' * 33_000):
            started = time.monotonic()
            mail(body=None, html=markup)
            self.assertLess(time.monotonic() - started, 1.5, markup[:20])
        for body in ('clave 1234 ' * 1800, '1234 ' * 4000, 'A-' * 10_000, 'password: ' * 2000, 'no share ' * 2200,
                     'iniciar sesión 1234 ' * 1000, 'x.y' * 6600):
            started = time.monotonic()
            parsed = mail(body=body)
            parsed.is_security, parsed.for_model(6000)
            self.assertLess(time.monotonic() - started, 1.5, body[:20])


class DisplayTests(SimpleTestCase):
    def test_evening_mail_keeps_its_day(self):
        parsed = mail()
        parsed.sent_at = datetime(2026, 11, 26, 1, 30, tzinfo=tz.utc)
        self.assertEqual(parsed.for_model(100)['fecha'], '2026-11-25')

    def test_night_mail_in_brazil_is_that_day(self):
        parsed = mail()
        parsed.sent_at = datetime(2026, 11, 25, 3, 30, tzinfo=tz.utc)
        parsed.utc_offset = -3
        self.assertEqual(parsed.for_model(100)['fecha'], '2026-11-25')

    def test_brand_names(self):
        self.assertEqual(mail(sender='Booking.com <no-reply@mail.booking.com>').sender,
                         'Booking.com <no-reply@mail.booking.com>')
        self.assertEqual(mail(sender='Booking.com <x@evil.example>').sender, 'x@evil.example')
        imitation = 'Banco avisos' + chr(0xFF20) + 'bnb' + chr(0x2024) + 'com <x@evil.example>'
        self.assertEqual(mail(sender=imitation).sender, 'x@evil.example')

    def test_confio_lookalike(self):
        self.assertTrue(mail(sender='C' + chr(0x043E) + 'nfío <x@evil.example>').claims_confio)

    def test_planted_sites_in_answers(self):
        for planted in ('.confio-verifica.com', 'confio-verifica.com_', 'evil-pay.com-', 'evil.xn--p1ai',
                        chr(0x431) + chr(0x430) + '.' + chr(0x440) + chr(0x444), 'evil' + chr(0x3002) + 'com',
                        'a.b.c.d.e.f.g.h.i.j.evil.com'):
            self.assertEqual(text.redact_for_answer(f'Paga en {planted} hoy'), 'Paga en [enlace] hoy', planted)
        self.assertEqual(text.redact_for_answer('Viaje a EE.UU por 142.50'), 'Viaje a EE.UU por 142.50')


class SubjectEncodingTests(SimpleTestCase):
    def test_accented_subjects_are_valid_and_unchanged(self):
        letters = 'aáéñç zãõ,.:-()?=_ ' + chr(0x1F382)
        rng = random.Random(7)
        for _ in range(3000):
            subject = ' '.join(''.join(rng.choice(letters) for _ in range(rng.randint(1, 200))).split()).replace('=?', '= ?')
            if not subject:
                continue
            fields = {'sender': 'a@x.example', 'to': 'b@x.example', 'subject': subject, 'body': 'Hola'}
            raw = base64.urlsafe_b64decode(compose.raw_message(fields))
            head = raw.split(b'\r\n\r\n')[0]
            for word in head.split():
                if word.startswith(b'=?utf-8?'):
                    self.assertLessEqual(len(word), 75, subject)
            self.assertEqual(str(email.message_from_bytes(raw, policy=policy.default)['subject']), subject)


class SyncRoundTwoTests(GmailPilotTest):
    def test_lone_bad_mail_is_dropped_after_hours(self):
        row = self.connect(failures=sync.LONE_FAILURES)
        self.box.search.return_value = ['bad']
        self.box.message.return_value = gmail_message()
        with self.with_box(), patch.object(reader, 'detect', side_effect=RuntimeError('x')) as detect:
            sync.sync(row.pk)
            GmailConnection.objects.filter(pk=row.pk).update(next_sync_at=timezone.now())
            sync.sync(row.pk)
        self.assertEqual(detect.call_count, 1)

    def test_disconnect_and_reconnect_finds_the_needs_again(self):
        self.box.search.return_value = ['bill']
        self.box.message.return_value = gmail_message()
        need = {'kind': 'payment', 'due_date': None, 'amount': None, 'currency': None}
        with self.with_box(), patch.object(reader, 'detect', return_value=need):
            first = self.connect()
            sync.sync(first.pk)
            GmailConnection.objects.filter(pk=first.pk).delete()
            second = self.connect()
            sync.sync(second.pk)
        self.assertEqual(second.needs.count(), 1)

    def test_outage_does_not_blame_mail_next_to_a_skipped_one(self):
        row = self.connect()
        self.box.search.return_value = ['code', 'bill']
        self.box.message.side_effect = lambda message_id: gmail_message(
            message_id=message_id, subject='Your verification code' if message_id == 'code' else 'Factura')
        with self.with_box(), patch.object(reader, 'detect', side_effect=RuntimeError('down')) as detect:
            for _ in range(4):
                GmailConnection.objects.filter(pk=row.pk).update(next_sync_at=timezone.now())
                sync.sync(row.pk)
        self.assertEqual(detect.call_count, 4)
