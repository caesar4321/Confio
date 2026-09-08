"""Frozen lifecycle tables for the pilot billing kernel."""


class InvalidTransition(ValueError):
    pass


OBLIGATION_TRANSITIONS = {
    'draft': frozenset({'open', 'void'}),
    'open': frozenset({'held', 'disputed', 'payment_pending', 'past_due',
                       'void', 'uncollectible'}),
    'held': frozenset({'open', 'void', 'uncollectible'}),
    'disputed': frozenset({'open', 'held', 'void', 'uncollectible'}),
    'payment_pending': frozenset({'paid', 'open'}),
    'past_due': frozenset({'payment_pending', 'held', 'disputed', 'paid',
                           'void', 'uncollectible'}),
    'paid': frozenset(),
    'void': frozenset(),
    'uncollectible': frozenset(),
}

INVOICE_TRANSITIONS = {
    'draft': frozenset({'open', 'void'}),
    'open': frozenset({'payment_pending', 'past_due', 'void', 'uncollectible'}),
    'payment_pending': frozenset({'paid', 'open'}),
    'past_due': frozenset({'payment_pending', 'paid', 'void', 'uncollectible'}),
    'paid': frozenset(),
    'void': frozenset(),
    'uncollectible': frozenset(),
}

PAYMENT_INTENT_TRANSITIONS = {
    'requires_payment_method': frozenset({'requires_confirmation', 'canceled'}),
    'requires_confirmation': frozenset({'processing', 'canceled'}),
    'processing': frozenset({'succeeded', 'failed'}),
    'succeeded': frozenset(),
    'failed': frozenset(),
    'canceled': frozenset(),
}

APPLICATION_TRANSITIONS = {
    'payment_confirmed': frozenset({'application_pending'}),
    'application_pending': frozenset({'acknowledged', 'mismatch', 'rejected'}),
    'mismatch': frozenset({'manual_review'}),
    'rejected': frozenset({'manual_review'}),
    'manual_review': frozenset({'acknowledged'}),
    'acknowledged': frozenset(),
}


def assert_transition(table, current: str, target: str) -> None:
    if target == current:
        return
    if target not in table.get(current, frozenset()):
        raise InvalidTransition(f'invalid transition: {current} -> {target}')
