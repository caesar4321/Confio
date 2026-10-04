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

# Keys are English and stable (stored); labels are the app's Spanish copy.
# Order = how the app lists them (the first six are the prompt's quick set).
CATEGORY_CHOICES = [
    ('food', 'Comida'),
    ('transport', 'Transporte'),
    ('home', 'Casa'),
    ('bills', 'Servicios'),
    ('family', 'Familia'),
    ('shopping', 'Compras'),
    ('health', 'Salud'),
    ('education', 'Educación'),
    ('leisure', 'Salidas'),
    ('debt', 'Deudas'),
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


class CusdPlusPriceSnapshot(models.Model):
    """One per UTC day: the cUSD+ share price at a pinned BSC block, written
    by cusd_plus.snapshot_savings_daily (docs/designs/tu-mes-insights.md R20,
    R26, R28). Savings earnings for "Tu mes" are computed from consecutive
    snapshots; a day without a row is unknown, never zero."""
    date = models.DateField(unique=True)
    pps_wad = models.DecimalField(max_digits=40, decimal_places=0, help_text='pPlus() at block_number, 1e18 = US$1')
    block_number = models.BigIntegerField()
    complete = models.BooleanField(
        default=False, help_text='True once every holder batch was attempted (R26)')
    failed_account_ids = models.JSONField(
        default=list, blank=True, help_text='Accounts whose balance read failed after retries; their month is unknown (R28)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.date} pps={self.pps_wad} block={self.block_number}'


class CusdPlusHoldingSnapshot(models.Model):
    """An account's cUSD+ shares on a snapshot day (same pinned block). Only
    nonzero balances get a row: on a complete day, no row = 0 shares (R26)."""
    account = models.ForeignKey('users.Account', on_delete=models.CASCADE, related_name='cusd_plus_snapshots')
    date = models.DateField()
    shares_raw = models.DecimalField(max_digits=40, decimal_places=0, help_text='balanceOf, 18 decimals')
    block_number = models.BigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'date'], name='uniq_cusd_plus_holding_day')]
        indexes = [models.Index(fields=['account', 'date'])]

    def __str__(self):
        return f'{self.account_id} {self.date} {self.shares_raw}'
