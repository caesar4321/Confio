"""The waitlist behind every "Próximamente" local rail row.

Before this table the only record of a "Sí, avísame" was a FunnelEvent, and
the nightly funnel rollup deletes raw events after 90 days — so the count
would shrink on its own and the people to notify when a corridor opens would
be gone. A waitlist is a promise ("te avisamos apenas esté listo"), so it
lives here, one row per person per rail, for as long as the rail is a probe.

Two kinds of wait share the table, because both end in the same promise:

- `coming_soon`: a "Próximamente" row. `rail_id` is the client catalog id
  from apps/src/config/localRails.ts (`send_ve_pagomovil`, `receive_ec_bank`).
- `nationality_blocked`: a live rail the provider refuses for this person's
  nationality ("Registramos tu interés…"). `rail_id` is the server method id
  from payment_accounts.local_money.METHODS (`co_breb_receive`, `mx_clabe`).

Both id sets are never renamed — funnel history hangs off them — and they
cannot collide (method ids carry no `send_`/`receive_` prefix), so one
unique (user, rail_id) holds across kinds.
"""
import re

from django.conf import settings
from django.db import models

# `<direction>_<iso2>_<rail>` — e.g. send_co_breb, receive_us_bank.
RAIL_ID_RE = re.compile(r'^(send|receive)_([a-z]{2})_([a-z0-9]{2,24})$')

# The probe rails the app lists. Only these can be joined: a well-formed id is
# not enough, or a script could mint unlimited rows and inflate the demand we
# show providers. Adding a rail to localRails.ts means adding it here first —
# apps/src/config/__tests__/localRails.test.ts fails until both agree.
KNOWN_RAIL_IDS = frozenset({
    'send_co_breb', 'send_mx_clabe', 'send_ar_alias', 'send_ve_pagomovil',
    'send_pe_qr', 'send_bo_qr', 'send_ec_bank', 'send_br_pix', 'send_cl_bank',
    'send_py_bank', 'send_uy_bank', 'send_us_bank', 'send_eu_sepa', 'send_gb_fps',
    'receive_co_breb', 'receive_mx_clabe', 'receive_ar_cvu', 'receive_ve_pagomovil',
    'receive_pe_qr', 'receive_bo_qr', 'receive_ec_bank', 'receive_br_pix',
    'receive_cl_bank', 'receive_py_bank', 'receive_uy_bank', 'receive_us_bank',
    'receive_eu_sepa', 'receive_gb_fps',
})


KIND_COMING_SOON = 'coming_soon'
KIND_NATIONALITY_BLOCKED = 'nationality_blocked'
KIND_CHOICES = [
    (KIND_COMING_SOON, 'Coming soon (probe rail)'),
    (KIND_NATIONALITY_BLOCKED, 'Blocked for nationality'),
]


def parse_rail_id(rail_id):
    """Return (direction, ISO-2 country) for a known probe rail id, else None."""
    rail_id = str(rail_id or '').strip()
    match = RAIL_ID_RE.match(rail_id)
    if not match or rail_id not in KNOWN_RAIL_IDS:
        return None
    return match.group(1), match.group(2).upper()


def resolve_waitlist_rail(rail_id, kind):
    """(direction, ISO-2 country) for a rail this kind of wait can name, else None.

    A blocked rail must be a real server method — the same catalog
    `localMoneyMethods` serves — so a client cannot mint ids here either.
    """
    if kind == KIND_COMING_SOON:
        return parse_rail_id(rail_id)
    if kind == KIND_NATIONALITY_BLOCKED:
        from payment_accounts.local_money import METHODS
        method = METHODS.get(str(rail_id or '').strip())
        return (method.direction, method.iso2) if method else None
    return None


class LocalRailWaitlistEntry(models.Model):
    """One person waiting for one local rail. Unique per (user, rail)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='local_rail_waitlist_entries',
    )
    rail_id = models.CharField(max_length=40, db_index=True)
    direction = models.CharField(max_length=8)
    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default=KIND_COMING_SOON)
    # The rail's country (from the id), not the person's — `EU` for SEPA.
    country = models.CharField(max_length=2, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'rail_id'], name='uniq_local_rail_waitlist_user_rail'),
        ]
        ordering = ['-created_at']
        verbose_name = 'Local rail waitlist entry'
        verbose_name_plural = 'Local rail waitlist entries'

    def __str__(self):
        return f'{self.rail_id} · user {self.user_id}'
