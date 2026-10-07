"""Which paid-offer chip (Confío IA+ / Cuenta inteligente) a reply carries.

The server decides, never the model alone (design: docs/designs/
cuenta-inteligente-fake-door.md):

- `asked`: the person names the offer → its chip, even inside the cap.
- `pain_point` (Cuenta inteligente) / `model` (Confío IA+): the model opened
  an offer itself (a need it solves, e.g. paying bills by hand every month) →
  kept unless that offer's chip was shown in the last 7 days (navigate()
  refuses it then, so the reply doesn't pitch it either).
- `investing`: the turn used get_portfolio or get_stock_quote → Confío IA+,
  same 7-day cap.

At most one paid chip per reply; never after an escalation (the reply then
belongs to the team), never to employees or old builds (allowed_destinations).
Every chip shown is logged once as a `door_shown` funnel event, which is also
what the cap counts.
"""
import re
from datetime import timedelta

from django.utils import timezone

from .destinations import PAID_OFFERS

LABELS = {'ia_plus': 'Conoce Confío IA+', 'cuenta_inteligente': 'Conoce Cuenta inteligente'}
ASKED = {
    # Not "Assistant+": that is the existing (unsold) plan, not this offer.
    'ia_plus': re.compile(r'(\bia\s*\+|\bia\s+plus\b)', re.I),
    'cuenta_inteligente': re.compile(r'\bcuenta\s+inteligente\b', re.I),
}
INVESTING_TOOLS = {'get_portfolio', 'get_stock_quote'}
CAP = timedelta(days=7)


def capped(user, key):
    from users.models import FunnelEvent
    from users.paid_offers import EVENT

    return FunnelEvent.objects.filter(
        event_name=EVENT, user=user, source_type=PAID_OFFERS[key],
        properties__stage='door_shown', properties__door='chip',
        created_at__gte=timezone.now() - CAP,
    ).exists()


def _action(key, trigger):
    return {'type': 'navigate', 'destination': 'home', 'target': key, 'label': LABELS[key],
            'source': f'chip:{trigger}'}


def choose(viewer, user_text, result, allowed):
    """Rewrite result.actions so it carries at most one allowed paid chip.
    Returns (key, trigger) of the chip kept, or None."""
    text = user_text or ''
    paid = [a for a in result.actions if a.get('target') in PAID_OFFERS]
    result.actions = [a for a in result.actions if a.get('target') not in PAID_OFFERS]
    if result.handoff_reason or viewer.user is None:
        return None
    chosen = None
    for key in PAID_OFFERS:
        if key in allowed and ASKED[key].search(text):
            chosen = (key, 'asked')
            break
    if chosen is None:
        for action in paid:
            key = action['target']
            if key in allowed and not capped(viewer.user, key):
                # Confío IA+ has no pain point of its own: the model opened it
                # for a reason the regex didn't name.
                chosen = (key, 'pain_point' if key == 'cuenta_inteligente' else 'model')
                break
    if chosen is None:
        used = {str(t.get('name', '')) for t in result.tools if isinstance(t, dict) and t.get('ok')}
        if used & INVESTING_TOOLS and 'ia_plus' in allowed and not capped(viewer.user, 'ia_plus'):
            chosen = ('ia_plus', 'investing')
    if chosen is None:
        return None
    result.actions.append(_action(*chosen))
    return chosen


def log_shown(viewer, chosen):
    from users.funding import has_funded
    from users.funnel import emit_event
    from users.paid_offers import EVENT

    from users.paid_offers import previewing

    key, trigger = chosen
    if previewing(getattr(viewer.user, 'pk', None)):
        # A preview tester's chips are neither counted nor capped.
        return
    emit_event(EVENT, user=viewer.user, country=(getattr(viewer.user, 'phone_country', '') or '')[:2],
               source_type=PAID_OFFERS[key],
               properties={'stage': 'door_shown', 'offer': PAID_OFFERS[key], 'door': 'chip',
                           'trigger': trigger, 'account_type': viewer.account_type,
                           'funded': has_funded(viewer.user)})
