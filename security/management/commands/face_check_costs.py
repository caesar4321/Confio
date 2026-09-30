"""What Confío Face actually costs, month by month and by purpose.

Every Rekognition call leaves a FaceCheck row: one liveness session per row,
plus one CompareFaces when the check got as far as the face match (similarity
recorded). Counting those rows gives the real volume; the unit prices are
settings so they can follow the AWS bill (list prices by default, USD).

    myvenv/bin/python manage.py face_check_costs            # last 3 months
    myvenv/bin/python manage.py face_check_costs --months 12
    FACE_LIVENESS_UNIT_USD=0.01 myvenv/bin/python manage.py face_check_costs

Liveness is the dominant term; per-user and per-purpose rows show which
moments drive it (e.g. 'app_unlock' from older builds).
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from security.face_step_up import _setting
from security.models import FaceCheck

DEFAULT_LIVENESS_UNIT_USD = '0.015'   # Rekognition Face Liveness, per session
DEFAULT_COMPARE_UNIT_USD = '0.001'    # Rekognition CompareFaces, per call


class Command(BaseCommand):
    help = 'Monthly Confío Face volume and estimated Rekognition cost, by purpose.'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=3)

    def handle(self, *args, months=3, **options):
        liveness_unit = Decimal(str(_setting('FACE_LIVENESS_UNIT_USD', DEFAULT_LIVENESS_UNIT_USD)))
        compare_unit = Decimal(str(_setting('FACE_COMPARE_UNIT_USD', DEFAULT_COMPARE_UNIT_USD)))
        # Calendar months, current one included, so totals line up with the AWS bill.
        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for _ in range(max(months, 1) - 1):
            start = (start - timedelta(days=1)).replace(day=1)
        since = start
        rows = (FaceCheck.objects.filter(created_at__gte=since)
                .annotate(month=TruncMonth('created_at'))
                .values('month', 'purpose')
                .annotate(sessions=Count('id'),
                          compares=Count('id', filter=Q(similarity__isnull=False)),
                          passed=Count('id', filter=Q(status='passed')),
                          users=Count('user', distinct=True))
                .order_by('month', 'purpose'))

        self.stdout.write(f'Unit prices (USD): liveness {liveness_unit}, compare {compare_unit}')
        header = f"{'month':<8} {'purpose':<15} {'checks':>8} {'passed':>8} {'users':>7} {'per user':>9} {'USD':>10}"
        self.stdout.write(header)
        self.stdout.write('-' * len(header))
        month_totals = {}
        for row in rows:
            cost = row['sessions'] * liveness_unit + row['compares'] * compare_unit
            month = row['month'].strftime('%Y-%m')
            per_user = row['sessions'] / row['users'] if row['users'] else 0
            month_totals.setdefault(month, [0, Decimal('0')])
            month_totals[month][0] += row['sessions']
            month_totals[month][1] += cost
            self.stdout.write(
                f"{month:<8} {row['purpose']:<15} {row['sessions']:>8} {row['passed']:>8} {row['users']:>7} "
                f"{per_user:>9.1f} {cost:>10.2f}")
        self.stdout.write('-' * len(header))
        for month, (checks, cost) in month_totals.items():
            self.stdout.write(f"{month:<8} {'TOTAL':<15} {checks:>8} {'':>8} {'':>7} {'':>9} {cost:>10.2f}")
        if not month_totals:
            self.stdout.write('No face checks in this period.')
