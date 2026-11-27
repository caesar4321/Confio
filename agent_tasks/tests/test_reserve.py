"""A reservation (reserve.py): no card ever, the guest's details typed by code after the person approved them
for that site, the booking pressed once after the person approved exactly it."""
from django.test import SimpleTestCase

from agent_tasks import notes, reserve, service, stores
from agent_tasks.tests.base import BASE, element, snap
from agent_tasks.tests.test_runner import StepBase, field

GOAL = 'reserva una habitación privada en Tilcara del 3 al 6 de febrero para 2 personas'


class SearchableTests(SimpleTestCase):
    def test_only_her_words_dates_times_and_counts(self):
        self.assertEqual(reserve.searchable('Tilcara', GOAL), 'Tilcara')
        self.assertEqual(reserve.searchable('03/02/2027', GOAL), '03/02/2027')
        self.assertEqual(reserve.searchable('2027-02-06', GOAL), '2027-02-06')
        self.assertEqual(reserve.searchable('2 adultos', GOAL), '2 adultos')
        self.assertEqual(reserve.searchable('3 de febrero', GOAL), '3 de febrero')
        self.assertEqual(reserve.searchable('21:00', 'mesa para 4 a las 21'), '21:00')
        # Never a word she did not say, a long number, an address or a mail.
        self.assertEqual(reserve.searchable('Purmamarca', GOAL), '')
        self.assertEqual(reserve.searchable('4111111111111111', GOAL), '')
        self.assertEqual(reserve.searchable('12345678', GOAL), '')
        self.assertEqual(reserve.searchable('ana@x.com', 'ana x com'), '')
        self.assertEqual(reserve.searchable('www.tilcara.com', GOAL), '')
        for value in ('4111 1111 1111 1111', '1234-5678', 'A1B2C3D4', '4111-11-1111 1111-11-1111'):
            self.assertEqual(reserve.searchable(value, 'reserva para 2 a1b2c3d4'), '', value)
        self.assertEqual(reserve.searchable('21hs', 'mesa a las 21'), '21hs')

    def test_guest_and_payment_fields_are_never_typed_by_the_model(self):
        for label, over in (('Correo electrónico', {}), ('Nombre', {}), ('Número de tarjeta', {}),
                            ('Documento', {}), ('Teléfono', {}), ('x', {'autocomplete': 'cc-number'}),
                            ('Clave', {'kind': 'password'})):
            self.assertTrue(reserve._fields_refusal(field(label, 0, **over)), label)
        self.assertEqual(reserve._fields_refusal(field('Destino', 0)), '')
        self.assertEqual(reserve._fields_refusal(field('Fecha de entrada', 0, 'date')), '')

    def test_the_consent_card_never_shows_a_whole_document_or_mail(self):
        text = reserve.consent_text(['document', 'email', 'full_name', 'phone'],
                                    {'document': '12345678', 'email': 'julian@example.com', 'full_name': 'Ana Pérez',
                                     'phone': '+59170000009'}, 'hostal.com')
        self.assertIn('Ana Pérez', text)
        self.assertIn('terminado en 678', text)
        self.assertNotIn('12345678', text)
        self.assertNotIn('julian@', text)
        self.assertIn('hostal.com', text)


class StoreNameTests(SimpleTestCase):
    def test_a_site_named_with_spaces_is_the_place_she_named(self):
        self.assertEqual(stores.choose('hostallastunas.com.ar', ['resérvame en Hostal Las Tunas'], joined=True),
                         'hostallastunas.com.ar')
        self.assertIsNone(stores.choose('hostallastunas.com.ar', ['resérvame en Hostal Sol'], joined=True))
        # Ordinary words never make a site, and a purchase never matches a brand split into words.
        self.assertIsNone(stores.choose('unahabitacion.com', ['reserva una habitación en Salta'], joined=True))
        self.assertIsNone(stores.choose('hostallastunas.com.ar', ['resérvame en Hostal Las Tunas']))
        for site, text in (('unahabitacion.com', 'Una habitación en Salta para 2'),
                           ('hotelbarato.com', 'Hotel barato en Mérida'), ('mesaparados.com', 'Mesa para dos a las 21')):
            self.assertIsNone(stores.choose(site, [text], joined=True), site)
        self.assertIsNone(stores.choose('hotelbarato.com', ['Hola\nHotel barato en Mérida'], joined=True))
        self.assertEqual(stores.choose('hostallastunas.com.ar', ['Hostal Las Tunas del 3 al 6'], joined=True),
                         'hostallastunas.com.ar')


class ReserveTests(StepBase):
    FORM = f'{BASE}/reserva/datos'

    def setUp(self):
        super().setUp()
        self.reserve = self.patch('agent_tasks.agent.reserve', return_value=('wait', {}))
        self.user.first_name, self.user.last_name, self.user.email = 'Ana', 'Pérez', 'ana@example.com'
        self.user.save()
        self.reader._run.return_value = ['https://www.youtube.com/embed/x']   # the page's frames: none pays

    def task(self, **over):
        return self.make_task(kind='reserve', goal=GOAL, **over)

    def guest_form(self, extra=()):
        return snap('Tus datos Nombre Correo', self.FORM, elements=[
            field('Nombre completo', 0), field('Correo electrónico', 1, 'email'), *extra,
            element('Confirmar reserva', ref=2)])

    def test_the_guest_details_are_typed_by_code_only_after_she_approved_them_for_this_site(self):
        page = self.guest_form()
        self.reserve.return_value = ('fill_guest', {'fields': [{'ref': 0, 'key': 'full_name'},
                                                               {'ref': 1, 'key': 'email'}]})
        task = self.step(self.task(), page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        self.reader.type.assert_not_called()
        self.assertEqual(task.order['request']['kind'], 'guest')
        self.assertNotIn('ana@example.com', task.order['request']['what'])
        task = service.answer_request(self.account, self.user, task.internal_id, True)
        task = self.step(task, page)
        typed = [call.args[1] for call in self.reader.type.call_args_list]
        self.assertEqual(typed, ['Ana Pérez', 'ana@example.com'])
        self.assertEqual(task.order['guest_approved']['keys'], ['email', 'full_name'])
        # Approved once: the same details are typed again without asking.
        task = self.step(task, page)
        self.assertEqual(task.state, 'working')

    def test_a_detail_never_goes_into_a_field_that_is_not_its_own(self):
        page = snap('Tus datos', self.FORM, elements=[field('Mensaje al anfitrión', 0), field('Nombre', 1)])
        self.reserve.return_value = ('fill_guest', {'fields': [{'ref': 0, 'key': 'email'}]})
        task = self.step(self.task(), page)
        self.assertEqual(task.state, 'working')
        self.assertIn('is not that field', task.history[-1]['result'])
        self.reader.type.assert_not_called()

    def test_after_her_details_are_typed_no_model_sees_them_echoed(self):
        page = self.guest_form()
        self.reserve.return_value = ('fill_guest', {'fields': [{'ref': 1, 'key': 'email'}]})
        task = self.step(self.task(), page)
        task = self.step(service.answer_request(self.account, self.user, task.internal_id, True), page)
        self.assertEqual(task.order['guest_typed'], ['email'])
        self.assertNotIn('ana@example.com', str(task.order))
        self.reserve.return_value = ('wait', {})
        echoed = snap('Revisa: ana@example.com, 2 personas', self.FORM, elements=[element('Siguiente', ref=0)])
        self.step(task, echoed)
        shown = self.reserve.call_args.args[1]
        self.assertNotIn('ana@example.com', shown.text)
        self.assertIn('[dato]', shown.text)
        self.assertIsNone(shown.look)   # no picture of a page with her details

    def test_no_to_the_details_books_nothing(self):
        self.reserve.return_value = ('fill_guest', {'fields': [{'ref': 0, 'key': 'full_name'}]})
        task = self.step(self.task(), self.guest_form())
        task = service.answer_request(self.account, self.user, task.internal_id, False)
        self.assertEqual((task.state, task.reason), ('stopped', 'declined'))
        self.assertIn('no reservé nada', notes.stopped_text(task, 'declined'))
        self.reader.type.assert_not_called()

    def test_the_model_never_types_a_guest_field_itself(self):
        self.reserve.return_value = ('type', {'ref': 1, 'text': 'ana@example.com'})
        task = self.step(self.task(), self.guest_form())
        self.reader.type.assert_not_called()
        self.assertIn('refused', task.history[-1]['result'])

    def test_the_booking_is_approved_then_pressed_once(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        page = snap('Resumen Hostal Las Tunas 3-6 feb 2 personas US$ 120 Pagas en el alojamiento', self.FORM,
                    elements=[element('Confirmar reserva', ref=0)])
        self.reserve.return_value = ('press', {'ref': 0})
        task = self.step(self.task(), page)
        self.reader.click.assert_not_called()
        self.assertIn('ready_to_book', task.history[-1]['result'])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal Las Tunas, 3 al 6 de febrero, 2 '
                                                                         'personas, US$ 120 en el alojamiento'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        self.assertIn('No pide tarjeta', self.post.call_args.args[1])
        from agent_tasks.schema import task_type
        shown = task_type(task)
        self.assertEqual(shown.kind, 'manage')   # drawn by the app as the same approval card
        self.reader.click.assert_not_called()
        task = self.step(service.answer_request(self.account, self.user, task.internal_id, True), page)
        self.reader.click.assert_called_once()
        self.assertEqual(task.order['submitted'], 1)
        task = self.step(task, page)
        self.reader.click.assert_called_once()   # a second press is asked again, never pressed on the first yes
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        task.state, task.reason = 'working', ''
        task.save()
        self.reserve.return_value = ('answer', {'text': 'Reserva confirmada 3 al 6 de febrero.'})
        task = self.step(task, snap('Reserva confirmada 3 al 6 de febrero', self.FORM, elements=[]))
        self.assertEqual((task.state, task.reason), ('stopped', 'answered'))
        self.assertIn('Envié tu reserva', self.post.call_args.args[1])
        self.assertIn('Reserva confirmada', self.post.call_args.args[1])

    def test_an_approval_never_covers_another_price_or_a_changed_form(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        page = snap('Resumen Hostal 3-6 feb US$ 120', self.FORM, elements=[element('Confirmar reserva', ref=0),
                                                                          field('Fecha', 1, 'date')])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal, 3 al 6 de febrero, US$ 500'})
        task = self.step(self.task(), page)
        self.assertIn('500 is not on this page', task.history[-1]['result'])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal, 3 al 6 de febrero, US$ 120'})
        task = self.step(task, page)
        task = service.answer_request(self.account, self.user, task.internal_id, True)
        self.reserve.return_value = ('type', {'ref': 1, 'text': '7 de febrero'})
        task = self.step(task, page)
        self.assertIsNone(task.order.get('request_approved'))   # the form changed: asked again
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal, 3 al 6 de febrero, US$ 120'})
        task = self.step(task, page)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        self.reader.click.assert_not_called()

    def test_a_card_on_the_page_stops_it_with_nothing_booked(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        page = snap('Garantía con tarjeta', self.FORM, elements=[
            field('Número de tarjeta', 0, autocomplete='cc-number'), element('Confirmar reserva', ref=1)])
        self.reserve.return_value = ('ready_to_book', {'ref': 1, 'what': 'la habitación'})
        task = self.step(self.task(), page)
        self.assertEqual((task.state, task.reason), ('stopped', 'needs_card'))
        self.reader.click.assert_not_called()
        self.assertIn('WhatsApp', notes.stopped_text(task, 'needs_card'))

    def test_a_saved_card_or_a_payment_frame_is_a_card(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        for text, frames in (('Garantizamos tu reserva con tu Visa •••• 4242', []),
                             ('Resumen 3-6 feb', ['https://js.stripe.com/v3/elements-inner-card']),
                             ('Resumen 3-6 feb', None)):
            self.reader._run.return_value = frames
            self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'la habitación'})
            task = self.step(self.task(), snap(text, self.FORM, elements=[element('Confirmar reserva', ref=0)]))
            self.assertEqual((task.state, task.reason), ('stopped', 'needs_card'), text)
            task.delete()
        self.reader.click.assert_not_called()

    def test_no_second_booking_once_the_page_shows_one(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        task = self.task()
        task.order = {'submitted': 1, 'booked_button': 'Reservar'}
        task.save()
        done = snap('Reserva confirmada. Número de reserva 4821. Reservar otra habitación', self.FORM,
                    elements=[element('Reservar otra habitación', ref=0)])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'otra habitación'})
        task = self.step(task, done)
        self.assertIn('already sent', task.history[-1]['result'])
        # A real second step says one press was already sent.
        step2 = snap('Confirma tu solicitud 3-6 feb', self.FORM, elements=[element('Solicitar reserva', ref=0)])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal, 3 al 6 de febrero'})
        task = self.step(task, step2)
        self.assertEqual((task.state, task.reason), ('needs_person', 'act'))
        self.assertIn('Ya presioné «Reservar» una vez', self.post.call_args.args[1])
        self.reader.click.assert_not_called()

    def test_a_page_saying_no_card_is_needed_is_not_a_card(self):
        self.reader._run.return_value = []
        self.assertFalse(reserve.card_on_page(snap('Reserva sin tarjeta de crédito para garantizar. Precio final 1250 BOB',
                                                   self.FORM), self.reader))

    def test_sign_in_is_never_a_guest_form(self):
        self.reserve.return_value = ('sign_in', {})
        task = self.step(self.task(), self.guest_form())
        self.assertIn('no password', task.history[-1]['result'])
        self.reader.type.assert_not_called()
        self.reader.click.assert_not_called()

    def test_an_approved_booking_is_pressed_even_when_reworded(self):
        self.judge.side_effect = None
        self.judge.return_value = ('places_order', 'it books')
        page = snap('Resumen Hostal 3-6 feb US$ 120', self.FORM, elements=[element('Confirmar reserva', ref=0)])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal, 3 al 6 de febrero, US$ 120'})
        task = self.step(self.task(), page)
        task = service.answer_request(self.account, self.user, task.internal_id, True)
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'Hostal del 3 al 6 feb por US$ 120'})
        task = self.step(task, page)
        self.reader.click.assert_called_once()
        self.assertEqual(task.order['submitted'], 1)

    def test_a_card_verdict_on_the_button_never_books(self):
        self.judge.side_effect = None
        self.judge.return_value = ('card', 'adds a card')
        page = snap('Resumen', self.FORM, elements=[element('Agregar tarjeta y reservar', ref=0)])
        self.reserve.return_value = ('ready_to_book', {'ref': 0, 'what': 'la habitación'})
        task = self.step(self.task(), page)
        self.assertEqual((task.state, task.reason), ('stopped', 'needs_card'))
        self.reader.click.assert_not_called()

    def test_ended_after_sending_never_says_nothing_was_booked(self):
        task = self.task()
        self.assertIn('no reservé nada', notes.stopped_text(task, 'too_long'))
        task.order = {'submitted': 1}
        self.assertIn('no alcancé a ver su confirmación', notes.stopped_text(task, 'too_long'))
