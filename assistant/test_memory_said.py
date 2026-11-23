"""What said_by_code says, for each verdict (assistant/memory.py)."""
from django.test import SimpleTestCase

from assistant import engine, memory, service


class SaidByCodeTests(SimpleTestCase):
    def test_each_line_in_each_language(self):
        expected = {
            # The items are named in Spanish: in another language the line does not name them.
            'saved': ('Guardé en tu memoria: Respuestas cortas.', 'Salvei na sua memória: “Respuestas cortas”.',
                      'I saved to your memory: “Respuestas cortas”.'),
            'forgot': ('Listo, ya no voy a tener', 'Pronto, não vou mais', "Done, I won't"),
            'maybe_not_saved': ('Si querías que lo guarde', 'Se você queria que eu salvasse', 'If you wanted me to save'),
            'maybe_not_forgot': ('Si querías que olvide algo: no borré', 'Se você queria que eu esquecesse algo: não apaguei',
                                 'If you wanted me to forget something: I didn'),
            'not_forgot_yet': ('Si querías que olvide algo: no pude', 'Se você queria que eu esquecesse algo: não consegui',
                               'If you wanted me to forget something: I couldn'),
        }
        self.assertEqual(set(expected), set(memory._LINES))
        for line, starts in expected.items():
            turn = memory.MemoryTurn(usage=None, line=line, saved=['Respuestas cortas'])
            for lang, start in zip(('es', 'pt', 'en'), starts):
                self.assertTrue(memory.said_by_code(turn, lang).startswith(start), (line, lang))

    def test_nothing_to_say(self):
        self.assertEqual(memory.said_by_code(None), '')
        self.assertEqual(memory.said_by_code(memory.MemoryTurn(usage=None, reply='Listo', line='forgot')), '')
        self.assertEqual(memory.said_by_code(memory.MemoryTurn(usage=None, note=memory.NOTE_NOT_FORGOT)), '')

    def test_the_replies_code_writes(self):
        for body in (engine.PAYMENT_PREPARED_REPLY, engine.DONE_REPLY, engine.SAVED_CHANGES_REPLY,
                     engine.CUT_EMPTY):
            self.assertTrue(service._written_by_code(engine.TurnResult(reply=body)), body)
        refused = engine.TurnResult(reply='No pude.', payment_refusal='No pude.')
        self.assertTrue(service._written_by_code(refused))
        self.assertFalse(service._written_by_code(engine.TurnResult(reply='Claro, te explico.')))
