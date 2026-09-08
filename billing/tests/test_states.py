from django.test import SimpleTestCase

from billing.states import (
    APPLICATION_TRANSITIONS,
    OBLIGATION_TRANSITIONS,
    PAYMENT_INTENT_TRANSITIONS,
    InvalidTransition,
    assert_transition,
)


class StateMachineTests(SimpleTestCase):
    def test_outcome_unknown_can_resolve_or_reopen(self):
        assert_transition(OBLIGATION_TRANSITIONS, 'payment_pending', 'paid')
        assert_transition(OBLIGATION_TRANSITIONS, 'payment_pending', 'open')

    def test_payment_success_is_terminal(self):
        with self.assertRaises(InvalidTransition):
            assert_transition(PAYMENT_INTENT_TRANSITIONS, 'succeeded', 'processing')

    def test_cip_failure_never_reopens_payment(self):
        assert_transition(APPLICATION_TRANSITIONS, 'application_pending', 'rejected')
        with self.assertRaises(InvalidTransition):
            assert_transition(APPLICATION_TRANSITIONS, 'rejected', 'payment_confirmed')
