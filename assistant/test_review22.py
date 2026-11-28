"""Review of 2026-11-28: a WhatsApp invite button promised and not shown (Pedro, twice)."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

INVITE = {'type': 'do', 'target': 'invite_whatsapp', 'label': 'Invitar por WhatsApp'}


class ButtonPromiseTests(SimpleTestCase):
    def run_guard(self, reply, offered=('act_here',), actions=(), waiting=False, **fields):
        from .engine import TurnResult, _keep_button_promise
        result = TurnResult(reply=reply)
        result.actions = [dict(a) for a in actions]
        for name, value in fields.items():
            setattr(result, name, value)
        belt = SimpleNamespace(viewer=SimpleNamespace(), waiting_for_team=waiting)
        with mock.patch('assistant.here.specs', return_value=[{'name': name} for name in offered]):
            _keep_button_promise(belt, result)
        return result

    def test_the_invite_button_promised_is_made(self):
        for said in ('No necesito sus números: al tocar el botón de abajo se abre tu WhatsApp con tu enlace y código '
                     'de invitación, y tú eliges a qué contactos enviárselo.',
                     'Toca el botón de abajo para abrir WhatsApp y elegir a quién enviarle tu invitación. ¡Éxito!'):
            result = self.run_guard(said)
            self.assertEqual(result.actions, [INVITE], said)
            self.assertEqual(result.reply, said)
            self.assertEqual(result.tools[-1]['name'], 'act_here:auto')

    def test_share_username(self):
        result = self.run_guard('Toca el botón de abajo para compartir tu usuario con quien te va a enviar.')
        self.assertEqual(result.actions[0]['target'], 'share_username')

    def test_left_alone(self):
        said = 'Toca el botón de abajo para abrir WhatsApp y enviar tu invitación.'
        for kw in ({'offered': ()}, {'waiting': True}, {'actions': [INVITE]}, {'pending_action': {'x': 1}}):
            result = self.run_guard(said, **kw)
            self.assertEqual(result.actions, kw.get('actions', []), kw)
            self.assertEqual(result.reply, said, kw)
        # An offer, an app screen's button, a button with nothing to share: no button from here.
        for plain in ('Si quieres, dime y te dejo aquí el botón para enviarles la invitación por WhatsApp.',
                      'En Recibir, toca el botón Invitar por WhatsApp y elige a tu amiga.',
                      'Toca el botón de abajo para abrir Recibir.',
                      'Toca el botón de abajo para invitar y compartir tu usuario por WhatsApp.'):
            result = self.run_guard(plain)
            self.assertEqual(result.actions, [], plain)

    def test_audit_findings(self):
        from .engine import TurnResult, _keep_card_promise
        # Past, negated, someone else's screen, a screen card promised: no button.
        for plain in ('Ya no hace falta el botón de abajo: tu invitación por WhatsApp se envió.',
                      'No toques el botón de abajo si no quieres invitar por WhatsApp.',
                      'Si tu amigo recibe la invitación por WhatsApp, que toque el botón de abajo de su pantalla.',
                      'Toca la tarjeta de Recibir de abajo; ahí está tu invitación para WhatsApp y el botón de abajo.',
                      'Te dejo la tarjeta de Recibir. Toca el botón de abajo para invitar por WhatsApp.',
                      'En WhatsApp, toca el botón de abajo a la derecha y pega tu código de invitación.',
                      'Cuando tu amigo abra la invitación de WhatsApp, verá el botón de abajo para registrarse.'):
            self.assertEqual(self.run_guard(plain).actions, [], plain)
        # "El botón de abajo" of a bank app or a form is never a card promise: never deleted.
        for said in ('En tu app del banco, entra a Pago Móvil y toca el botón de abajo que dice Continuar.',
                     'Escribe el monto en el formulario de abajo y toca el botón de abajo para crear tu recarga.'):
            result = TurnResult(reply=said)
            belt = SimpleNamespace(card_spec=None)
            _keep_card_promise(belt, result)
            self.assertEqual(result.reply, said)
            from .engine import _CARD_PROMISE
            self.assertFalse(_CARD_PROMISE.search(said), said)
