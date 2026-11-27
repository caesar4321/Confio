"""Review of 2026-11-27: a form promised and not shown (Pedro, Chile, twice)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class FormPromiseTests(SimpleTestCase):
    def run_guard(self, reply, offered=('topup', 'investor_bio'), actions=(), home=True, waiting=False, **fields):
        from .engine import TurnResult, _keep_form_promise
        result = TurnResult(reply=reply)
        result.actions = [dict(a) for a in actions]
        for name, value in fields.items():
            setattr(result, name, value)
        belt = SimpleNamespace(viewer=SimpleNamespace(), force_tool='', waiting_for_team=waiting)
        with mock.patch('assistant.here.specs', return_value=[{'name': 'x'}] if home else []), \
                mock.patch('assistant.here.forms_for', return_value=list(offered)):
            _keep_form_promise(belt, result)
        return result

    def test_the_form_a_top_up_promised_is_made(self):
        said = ('En Chile puedes recargar con transferencia bancaria o con Khipu desde una cuenta a tu nombre.\n\n'
                'Puedes crear tu recarga aquí mismo en este formulario:')
        result = self.run_guard(said, offered=('topup', 'investor_bio', 'profile_name'))
        self.assertEqual(result.actions, [{'type': 'form', 'target': 'topup', 'label': 'Recargar'}])
        self.assertEqual(result.reply, said)
        self.assertEqual(result.tools[-1]['name'], 'ask_details:auto')

    def test_a_reply_ending_on_aqui_mismo(self):
        said = ('En Chile puedes poner tus primeros dólares de tres formas:\n\n1. Recargando en pesos.\n'
                '2. Recibiendo dólares.\n\nSi quieres recargar ahora desde tu banco, puedes hacerlo aquí mismo:')
        result = self.run_guard(said)
        self.assertEqual(result.actions[0]['target'], 'topup')

    def test_promise_taken_out_when_no_form_fits(self):
        said = 'Primero verifica tu identidad.\n\nPuedes recargar aquí mismo en este formulario:'
        for kw in ({'offered': ()}, {'home': False}, {'waiting': True}):
            result = self.run_guard(said, **kw)
            self.assertEqual(result.actions, [], kw)
            self.assertEqual(result.reply, 'Primero verifica tu identidad.', kw)

    def test_two_forms_fit_code_does_not_pick(self):
        said = 'Para recargar o escribir tu descripción, usa el formulario de abajo.'
        result = self.run_guard(said, offered=('topup', 'investor_bio'))
        self.assertEqual(result.actions, [])

    def test_left_alone(self):
        form = {'type': 'form', 'target': 'topup', 'label': 'Recargar'}
        card = {'type': 'card', 'destination': 'top_up'}
        self.assertEqual(self.run_guard('Escribe el monto en el formulario de abajo.', actions=[form]).actions,
                         [form])
        # A card under it keeps "aquí mismo:".
        kept = self.run_guard('Puedes ver tus opciones aquí mismo:', actions=[card])
        self.assertEqual((kept.actions, kept.reply), ([card], 'Puedes ver tus opciones aquí mismo:'))
        for plain in ('Llena el formulario de verificación en la app.', 'Tienes tres formas:\n\n1. Recargar.',
                      'Recarga con transferencia desde una cuenta a tu nombre.',
                      'El formulario de Didit te pide tu documento.'):
            result = self.run_guard(plain)
            self.assertEqual((result.actions, result.reply), ([], plain), plain)

    def test_a_named_form_beside_a_card_is_not_left_as_a_promise(self):
        card = {'type': 'card', 'destination': 'receive'}
        result = self.run_guard('Abre Recibir. Te dejo el formulario para recargar.', actions=[card])
        self.assertEqual((result.actions, result.reply), ([card], 'Abre Recibir.'))

    def test_audit_findings(self):
        # A card promise ending on "aquí:" is the card check's, never removed here.
        said = 'Para recibir dinero comparte tu código. Te dejo la tarjeta de Recibir aquí:'
        self.assertEqual((self.run_guard(said).actions, self.run_guard(said).reply), ([], said))
        # A WhatsApp card under it keeps "aquí:".
        said = 'Te preparé este mensaje para Juan. Revísalo y envíalo aquí:'
        self.assertEqual(self.run_guard(said, whatsapp_card=True).reply, said)
        # Portuguese "aqui:" is not a form.
        said = 'Você pode ver seu saldo. Confira aqui:'
        self.assertEqual(self.run_guard(said).reply, said)
        # An earlier form asked about, a bank's form, a Didit form: left alone.
        for plain in ('¿Ya llenaste el formulario de recarga que te dejé? Si tienes dudas, dime.',
                      'En este formulario del banco, pon el monto que quieres recargar.',
                      'Mira la captura. Revisa los datos en este formulario antes de enviarlo.'):
            result = self.run_guard(plain)
            self.assertEqual((result.actions, result.reply), ([], plain), plain)
        # Only the promise's words pick the form.
        said = 'Tu recarga de ayer llegó. Para tu próxima operación, entra aquí:'
        result = self.run_guard(said)
        self.assertEqual((result.actions, result.reply), ([], 'Tu recarga de ayer llegó.'))
        # No bare "2." left behind.
        said = 'Los pasos son:\n1. Abre la app.\n2. Completa los datos aquí:'
        self.assertEqual(self.run_guard(said, offered=()).reply, 'Los pasos son:\n1. Abre la app.')
        # With the form attached, a card it also promised goes from the text.
        said = 'Te dejo el formulario de recarga abajo. Toca también la tarjeta de Recibir de abajo.'
        result = self.run_guard(said)
        self.assertEqual(result.actions[0]['target'], 'topup')
        self.assertEqual(result.reply, 'Te dejo el formulario de recarga abajo.')

    def test_second_audit(self):
        said = 'Didit te mostrará un formulario. Revisa los datos en este formulario.'
        self.assertEqual(self.run_guard(said).reply, said)
        said = '¿Quieres recargar desde tu banco? Puedes hacerlo aquí mismo:'
        self.assertEqual(self.run_guard(said).actions[0]['target'], 'topup')
