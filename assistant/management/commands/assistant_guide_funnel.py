"""First-steps guide funnel: each step's events, then what those people really
did afterwards, read from the same records the guide itself trusts.

    manage.py assistant_guide_funnel --days 30 [--country BO]
"""
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Min
from django.utils import timezone

from assistant import conf
from assistant.guide import PAID_ORDER_STATUSES, PERP_OPENED_STATES
from assistant.models import AssistantGuideEvent

EVENT_ORDER = ('shown', 'replied', 'dismissed', 'accepted', 'opened', 'pointer_shown', 'pointer_missing',
               'pointer_tapped', 'pointer_closed')


def outcomes(first_shown):
    """How many of {user_id: first shown at} did each thing afterwards."""
    from blockchain.models import PerpPosition, SponsoredBatch
    from marketplace.models import Order
    from ramps.models import RampTransaction
    from security.models import IdentityVerification
    from users.models_unified import UnifiedTransactionTable

    def after(rows):
        return len({uid for uid, when in rows if when >= first_shown[uid]})

    ids = list(first_shown)
    unified = UnifiedTransactionTable.objects.filter(status='CONFIRMED', deleted_at__isnull=True)
    orders = RampTransaction.objects.filter(actor_user_id__in=ids, direction='on_ramp')
    batches = SponsoredBatch.objects.filter(user_id__in=ids, status='confirmed')
    return {
        'verified': after(IdentityVerification.all_documents.filter(user_id__in=ids, status='verified',
                                                                    verified_at__isnull=False)
                          .values_list('user_id', 'verified_at')),
        'order created': after(orders.values_list('actor_user_id', 'created_at')),
        'order paid': after(orders.filter(status='COMPLETED', completed_at__isnull=False)
                            .values_list('actor_user_id', 'completed_at')),
        'funded': after(unified.filter(counterparty_user_id__in=ids).exclude(is_invitation=True, invitation_claimed=False)
                        .values_list('counterparty_user_id', 'created_at')),
        'sent or paid': after(unified.filter(sender_user_id__in=ids, sender_business__isnull=True,
                                              transaction_type__in=('send', 'payment'))
                              .values_list('sender_user_id', 'created_at')),
        'bought stocks': after(batches.filter(kind='stock_buy').values_list('user_id', 'created_at')),
        'bought gold or bitcoin': after(batches.filter(kind='crypto_buy').values_list('user_id', 'created_at')),
        'opened a future': after(PerpPosition.objects.filter(user_id__in=ids, state__in=PERP_OPENED_STATES)
                                 .values_list('user_id', 'created_at')),
        'bought in Comprar': after(Order.objects.filter(buyer_id__in=ids, status__in=PAID_ORDER_STATUSES)
                                   .values_list('buyer_id', 'created_at')),
    }


class Command(BaseCommand):
    help = 'Funnel of the assistant first-steps guide'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--country', default='')

    def handle(self, *args, days, country, **options):
        events = AssistantGuideEvent.objects.filter(created_at__gte=timezone.now() - timedelta(days=days)).exclude(
            user_id__in=conf.get('ASSISTANT_GUIDE_PREVIEW_USER_IDS'))
        if country:
            events = events.filter(country=country.upper())
        people = defaultdict(lambda: defaultdict(set))
        details = defaultdict(lambda: defaultdict(set))
        for step, event, detail, user_id in events.values_list('step', 'event', 'detail', 'user_id'):
            people[step][event].add(user_id)
            if detail:
                details[step][f'{event} {detail}'].add(user_id)
        for step in sorted(people, key=lambda s: -len(people[s]['shown'])):
            line = ' · '.join(f'{e} {len(people[step][e])}' for e in EVENT_ORDER if people[step][e])
            self.stdout.write(f'{step}: {line}')
            for key in sorted(details[step]):
                self.stdout.write(f'  {key}: {len(details[step][key])}')
        first_shown = dict(events.filter(event='shown').values_list('user_id').annotate(at=Min('created_at')))
        self.stdout.write(f'\nPeople shown any step: {len(first_shown)}')
        if first_shown:
            for label, count in outcomes(first_shown).items():
                self.stdout.write(f'  {label}: {count}')
