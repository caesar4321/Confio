"""The general card (cards.py): composed by the server, answered only for the very card that was seen."""
from agent_tasks import cards, schema, service
from agent_tasks.models import AgentTask
from agent_tasks.tests.test_service import ServiceBase

ORDER = {'total': '$129.00', 'button': 'Finalizar compra', 'page': 'loja.com.br/checkout', 'item': 'Garrafa térmica',
         'image': 'https://img.invalid/g.jpg', 'address': 'Rua A 1, São Paulo',
         'breakdown': [{'kind': 'products', 'amount': '$85.00'}, {'kind': 'shipping', 'amount': '$44.00'}]}


class CardTests(ServiceBase):
    def setUp(self):
        super().setUp()
        self.subscribed = self.patch('agent_tasks.service.subscribed', return_value=True)

    def answer(self, task, action, binding=None):
        shown = cards.card(task)
        return cards.answer(self.account, self.user, task.internal_id, action,
                            shown['binding'] if binding is None else binding)

    def test_the_order_card_shows_what_the_older_card_showed(self):
        task = self.waiting(reason='approve', order=dict(ORDER))
        card = cards.card(task)
        self.assertEqual((card['version'], card['icon'], card['title'], card['subtitle'], card['image']),
                         (1, 'bag', 'Garrafa térmica', task.site, 'https://img.invalid/g.jpg'))
        self.assertEqual(card['lines'], [{'label': 'Productos', 'value': '$85.00'},
                                         {'label': 'Envío', 'value': '$44.00'},
                                         {'label': 'Envío a', 'value': 'Rua A 1, São Paulo'}])
        self.assertEqual(card['total'], {'label': 'Total', 'value': '$129.00', 'note': ''})
        self.assertEqual([one['id'] for one in card['actions']], ['approve', 'change_address'])

    def test_a_tap_approves_the_card_that_was_seen_and_nothing_else(self):
        task = self.waiting(reason='approve', order=dict(ORDER))
        seen = cards.card(task)['binding']
        # The total changed after the card was drawn: the old card's tap approves nothing.
        AgentTask.objects.filter(pk=task.pk).update(order={**ORDER, 'total': '$199.00'})
        task.refresh_from_db()
        self.refused('not_open', cards.answer, self.account, self.user, task.internal_id, 'approve', seen)
        self.assertNotIn('approved', task.order)
        self.refused('not_open', cards.answer, self.account, self.user, task.internal_id, 'approve', 'forged')
        self.refused('not_open', self.answer, task, 'request_yes')   # an action this card does not offer
        done = self.answer(task, 'approve')
        self.assertEqual((done.order['approved']['total'], done.order['approved']['address']),
                         ('$199.00', 'Rua A 1, São Paulo'))

    def test_an_expired_card_is_never_answered_and_the_task_ends(self):
        from datetime import timedelta
        from django.utils import timezone
        task = self.waiting(reason='approve', order=dict(ORDER))
        seen = cards.card(task)['binding']
        AgentTask.objects.filter(pk=task.pk).update(wait_until=timezone.now() - timedelta(seconds=1))
        self.refused('not_open', cards.answer, self.account, self.user, task.internal_id, 'approve', seen)
        self.assertEqual(AgentTask.objects.get(pk=task.pk).reason, 'person_timeout')

    def test_an_odd_quantity_never_breaks_the_card(self):
        task = self.waiting(reason='approve', order={**ORDER, 'items': [{'title': 'A', 'quantity': '2 kg'},
                                                                        {'title': 'B', 'quantity': 3}]})
        self.assertEqual(cards.card(task)['title'], '4 productos')

    def test_another_persons_card_is_never_answered(self):
        task = self.waiting(reason='approve', order=dict(ORDER))
        stranger, account = self.person()
        self.refused('not_found', cards.answer, account, stranger, task.internal_id, 'approve',
                     cards.card(task)['binding'])

    def test_subscribe_opens_the_offer_in_the_app_and_seguir_resumes(self):
        task = self.waiting(reason='subscribe', order=dict(ORDER))
        card = cards.card(task)
        self.assertEqual([(one['id'], one['screen']) for one in card['actions']],
                         [('open_smart_account', 'SmartAccountOffer'), ('approve', None)])
        self.refused('not_open', self.answer, task, 'open_smart_account')   # the app opens it, never the server
        self.answer(task, 'approve')
        self.assertNotEqual(AgentTask.objects.get(pk=task.pk).state, 'needs_person')

    def test_a_booking_is_said_as_one(self):
        task = self.waiting(reason='approve', kind='reserve', goal='reserva un hostal en Salta 2 noches',
                            order={**ORDER, 'address': ''})
        card = cards.card(task)
        self.assertEqual((card['icon'], [one['label'] for one in card['actions']]), ('bed', ['Confirmar reserva']))
        for goal, icon in (('pasaje de bus a Lima', 'bus'), ('un vuelo a Cusco', 'plane'),
                           ('mesa para 4 en un restaurante', 'table'), ('un turno con la tatuadora', 'calendar')):
            AgentTask.objects.filter(pk=task.pk).update(goal=goal)
            task.refresh_from_db()
            self.assertEqual(cards.card(task)['icon'], icon, goal)

    def test_requests_steps_and_notify(self):
        request = {'label': 'book', 'kind': 'book', 'what': 'Habitación doble, 3 al 6 feb, US$ 120',
                   'button': 'Reservar'}
        task = self.waiting(reason='act', kind='reserve', goal='reserva un hotel', order={'request': request})
        card = cards.card(task)
        self.assertEqual((card['title'], card['lines'][0]['value'], card['actions'][0]['label']),
                         (request['what'], '«Reservar»', 'Confirmar reserva'))
        done = self.answer(task, 'request_yes')
        self.assertEqual(done.order['request_approved']['what'], request['what'])
        AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

        step = self.waiting(reason='step', order={'ask_step': {'label': 'Aceptar cookies'}}, site='otra.com.br')
        self.assertEqual(cards.card(step)['title'], '«Aceptar cookies»')
        self.answer(step, 'step_no')
        AgentTask.objects.filter(pk=step.pk).update(state='cancelled')

        stopped = self.make_task(state='stopped', reason='no_rail', site='tienda.com.pe', country='PE')
        self.assertEqual([one['id'] for one in cards.card(stopped)['actions']], ['notify_yes', 'notify_no'])
        self.answer(stopped, 'notify_yes')
        stopped.refresh_from_db()
        self.assertEqual(cards.card(stopped)['actions'], [])
        AgentTask.objects.filter(pk=stopped.pk).update(order={'notify': 'no'})
        stopped.refresh_from_db()
        self.assertIsNone(cards.card(stopped))

    def test_native_states_have_no_general_card(self):
        for reason in ('choose', 'login', 'otp', 'address', 'account_wait'):
            task = self.waiting(reason=reason, order=dict(ORDER))
            self.assertIsNone(cards.card(task), reason)
            AgentTask.objects.filter(pk=task.pk).update(state='cancelled')

    def test_the_graphql_type(self):
        task = self.waiting(reason='approve', order=dict(ORDER))
        shown = schema._card_type(task)
        self.assertEqual((shown.title, shown.total.value, shown.actions[0].style, len(shown.binding)),
                         ('Garrafa térmica', '$129.00', 'primary', 40))
        self.assertIsNone(schema._card_type(None))
        self.assertIn('answer_agent_card', schema.Mutation._meta.fields)
        self.assertIn('agent_task_card', schema.Query._meta.fields)
        self.assertIsInstance(service.TaskRefused('not_open'), Exception)
