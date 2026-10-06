"""What people asked Confío for: counts by category x country x funded, and
the top unmet needs with redacted paraphrases. Run any time:

    manage.py assistant_needs_report --days 30 [--tag-now]
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Report of tagged user needs (assistant/needs.py).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--tag-now', action='store_true', help='Tag untagged messages from the window first')

    def handle(self, *args, **opts):
        from assistant.models import AssistantNeed, ProbeAnswer
        from assistant.needs import tag_recent

        days = opts['days']
        if opts['tag_now']:
            self.stdout.write(f'tagged {tag_recent(hours=days * 24)} new messages')
        since = timezone.now() - timedelta(days=days)
        needs = AssistantNeed.objects.filter(message_at__gte=since)
        total = needs.count()
        self.stdout.write(f'\nNeeds in the last {days} days: {total} messages, '
                          f'{needs.values("user").distinct().count()} people\n')
        by_cat = Counter(needs.values_list('category', flat=True))
        for category, n in by_cat.most_common():
            people = needs.filter(category=category).values('user').distinct().count()
            unfunded = needs.filter(category=category, funded=False).values('user').distinct().count()
            countries = Counter(needs.filter(category=category).values_list('phone_country', flat=True))
            top = ', '.join(f'{c or "?"} {k}' for c, k in countries.most_common(4))
            self.stdout.write(f'  {category:<20} {n:>4} msgs  {people:>4} people  ({unfunded} never funded)  {top}')
        unmet = needs.filter(met_by_confio=False)
        if unmet.exists():
            self.stdout.write('\nUnmet needs (examples):')
            for row in unmet.order_by('-message_at')[:10]:
                self.stdout.write(f'  [{row.category}/{row.phone_country or "?"}] {row.paraphrase}')
        answers = ProbeAnswer.objects.filter(created_at__gte=since)
        if answers.exists():
            self.stdout.write('\nProbe "¿Para qué te gustaría usar Confío?":')
            for answer, n in Counter(answers.values_list('answer', flat=True)).most_common():
                self.stdout.write(f'  {answer:<14} {n}')
