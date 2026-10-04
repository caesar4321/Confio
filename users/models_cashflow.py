"""Spending categories for the month summary ("Tu mes").

Design: docs/designs/cashflow-home-tu-mes.md (D2 separate models, R3/R4
permissions, R5 counterparty keys, R20 rules apply past + future).

Category is a second, optional, user-supplied dimension on spending
movements; it never changes a movement's rail-derived kind. Resolution at
read time: MovementOverride for that ledger row > CounterpartyRule for its
counterparty > uncategorized. Rules are evaluated when the month is read,
so labeling a counterparty labels its past AND future payments (except rows
with their own override) without rewriting any history row.

All rows are scoped to the account (JWT active account), never the user:
a business and its owner's personal account keep separate labels.
"""
from django.db import models

CATEGORY_CHOICES = [
    ('food', 'Comida'),
    ('transport', 'Transporte'),
    ('home', 'Casa'),
    ('family', 'Familia'),
    ('work', 'Trabajo'),
    ('other', 'Otro'),
]
CATEGORY_KEYS = {key for key, _ in CATEGORY_CHOICES}


class CounterpartyRule(models.Model):
    """'Doña Rosa is food' for one account — applies to all her payments."""
    account = models.ForeignKey('users.Account', on_delete=models.CASCADE, related_name='counterparty_rules')
    counterparty_key = models.CharField(
        max_length=160, help_text='business:<id> | user:<id> | bank:<code>:<acct> | dest:<id> | addr:<address>')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'counterparty_key'], name='uniq_counterparty_rule')]

    def __str__(self):
        return f'{self.account_id} {self.counterparty_key} -> {self.category}'


class MovementOverride(models.Model):
    """'Only this payment' — wins over the counterparty rule for one row."""
    account = models.ForeignKey('users.Account', on_delete=models.CASCADE, related_name='movement_overrides')
    movement = models.ForeignKey(
        'users.UnifiedTransactionTable', on_delete=models.CASCADE, related_name='category_overrides')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'movement'], name='uniq_movement_override')]

    def __str__(self):
        return f'{self.account_id} #{self.movement_id} -> {self.category}'


class CounterpartyPromptState(models.Model):
    """How often the success-screen chips were declined for a counterparty.

    Design D11: "Ahora no" is a skip (stop after 2); leaving without
    answering is a dismiss (stop after 3). Server-side so it survives
    reinstalls and device changes.
    """
    SKIP_LIMIT = 2
    DISMISS_LIMIT = 3

    account = models.ForeignKey('users.Account', on_delete=models.CASCADE, related_name='counterparty_prompt_states')
    counterparty_key = models.CharField(max_length=160)
    skip_count = models.PositiveSmallIntegerField(default=0)
    dismiss_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'counterparty_key'], name='uniq_counterparty_prompt_state')]

    @property
    def exhausted(self) -> bool:
        return self.skip_count >= self.SKIP_LIMIT or self.dismiss_count >= self.DISMISS_LIMIT

    def __str__(self):
        return f'{self.account_id} {self.counterparty_key} skip={self.skip_count} dismiss={self.dismiss_count}'
