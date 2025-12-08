"""
Management command to view and validate user activity metrics (DAU/MAU/WAU)

Usage:
    python manage.py activity_metrics                    # Show current metrics
    python manage.py activity_metrics --detailed         # Show detailed breakdown
    python manage.py activity_metrics --compare-methods  # Compare old vs new calculation
    python manage.py activity_metrics --validate         # Validate tracking completeness
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
from users.models import User, Account
from users.activity_tracking import get_activity_metrics, get_active_users
from p2p_exchange.models import P2PTrade, P2PMessage
from send.models import SendTransaction
from payments.models import PaymentTransaction
from conversion.models import Conversion
from achievements.models import UserAchievement


class Command(BaseCommand):
    help = 'Display and validate user activity metrics (DAU/MAU/WAU)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed breakdown of metrics',
        )
        parser.add_argument(
            '--compare-methods',
            action='store_true',
            help='Compare new unified method vs old multi-table union method',
        )
        parser.add_argument(
            '--validate',
            action='store_true',
            help='Validate that activity tracking is working correctly',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to analyze (default: 30)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== User Activity Metrics ===\n'))

        if options['compare_methods']:
            self.compare_calculation_methods()
        elif options['validate']:
            self.validate_tracking(options['days'])
        elif options['detailed']:
            self.show_detailed_metrics(options['days'])
        else:
            self.show_standard_metrics()

    def show_standard_metrics(self):
        """Show standard DAU/WAU/MAU metrics"""
        metrics = get_activity_metrics()

        self.stdout.write(self.style.HTTP_INFO('Current Activity Metrics:'))
        self.stdout.write(f"  Total Users:     {metrics['total_users']:,}")
        self.stdout.write(f"  DAU (24h):       {metrics['dau']:,} ({metrics['dau_percentage']:.1f}%)")
        self.stdout.write(f"  WAU (7 days):    {metrics['wau']:,} ({metrics['wau_percentage']:.1f}%)")
        self.stdout.write(f"  MAU (30 days):   {metrics['mau']:,} ({metrics['mau_percentage']:.1f}%)")
        self.stdout.write('')

        # Activity retention
        if metrics['mau'] > 0:
            dau_mau_ratio = (metrics['dau'] / metrics['mau']) * 100
            wau_mau_ratio = (metrics['wau'] / metrics['mau']) * 100
            self.stdout.write(self.style.HTTP_INFO('Engagement Ratios:'))
            self.stdout.write(f"  DAU/MAU:         {dau_mau_ratio:.1f}%")
            self.stdout.write(f"  WAU/MAU:         {wau_mau_ratio:.1f}%")

    def show_detailed_metrics(self, days):
        """Show detailed breakdown by time periods"""
        self.stdout.write(self.style.HTTP_INFO('Detailed Activity Breakdown:\n'))

        periods = [
            ('Last 24 hours', 1),
            ('Last 3 days', 3),
            ('Last 7 days', 7),
            ('Last 14 days', 14),
            ('Last 30 days', 30),
            ('Last 60 days', 60),
            ('Last 90 days', 90),
        ]

        total_users = User.objects.count()

        for label, days_count in periods:
            count = get_active_users(days=days_count).count()
            percentage = (count / total_users * 100) if total_users > 0 else 0
            self.stdout.write(f"  {label:20} {count:6,} users ({percentage:5.1f}%)")

    def compare_calculation_methods(self):
        """Compare new unified method with old multi-table union method"""
        self.stdout.write(self.style.WARNING('Comparing Calculation Methods:\n'))

        now = timezone.now()
        last_24h = now - timedelta(hours=24)

        # NEW METHOD: Single field
        new_dau = User.objects.filter(last_activity_at__gte=last_24h).count()

        # OLD METHOD: Union of all tables (legacy)
        active_user_ids = set()

        # Account logins
        active_user_ids.update(
            Account.objects
            .filter(last_login_at__gte=last_24h)
            .values_list('user_id', flat=True)
        )

        # Auth logins
        active_user_ids.update(
            User.objects
            .filter(last_login__gte=last_24h)
            .values_list('id', flat=True)
        )

        # P2P trades
        q_trades = P2PTrade.objects.filter(created_at__gte=last_24h)
        active_user_ids.update(q_trades.filter(buyer_user__isnull=False).values_list('buyer_user_id', flat=True))
        active_user_ids.update(q_trades.filter(seller_user__isnull=False).values_list('seller_user_id', flat=True))

        # P2P messages
        active_user_ids.update(
            P2PMessage.objects
            .filter(created_at__gte=last_24h, sender_user__isnull=False)
            .values_list('sender_user_id', flat=True)
        )

        # Sends
        q_sends = SendTransaction.objects.filter(created_at__gte=last_24h)
        active_user_ids.update(q_sends.filter(sender_user__isnull=False).values_list('sender_user_id', flat=True))
        active_user_ids.update(q_sends.filter(recipient_user__isnull=False).values_list('recipient_user_id', flat=True))

        # Payments
        q_payments = PaymentTransaction.objects.filter(created_at__gte=last_24h)
        active_user_ids.update(q_payments.values_list('payer_user_id', flat=True))

        # Conversions
        active_user_ids.update(
            Conversion.objects
            .filter(created_at__gte=last_24h, actor_user__isnull=False)
            .values_list('actor_user_id', flat=True)
        )

        # Achievements
        active_user_ids.update(
            UserAchievement.objects
            .filter(earned_at__gte=last_24h)
            .values_list('user_id', flat=True)
        )

        old_dau = len({uid for uid in active_user_ids if uid})

        self.stdout.write(f"  NEW METHOD (last_activity_at):  {new_dau:,} users")
        self.stdout.write(f"  OLD METHOD (union queries):     {old_dau:,} users")
        self.stdout.write(f"  Difference:                     {abs(new_dau - old_dau):,} users")
        self.stdout.write('')

        if new_dau < old_dau:
            diff_pct = ((old_dau - new_dau) / old_dau * 100) if old_dau > 0 else 0
            self.stdout.write(self.style.WARNING(
                f"⚠️  New method shows {diff_pct:.1f}% fewer users.\n"
                f"   This suggests some activity points may not be calling touch_last_activity().\n"
                f"   Run with --validate to identify missing tracking points."
            ))
        elif new_dau > old_dau:
            self.stdout.write(self.style.SUCCESS(
                "✓ New method captures more activity (likely includes additional tracking points)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "✓ Methods are in sync!"
            ))

    def validate_tracking(self, days):
        """Validate that activity tracking is complete"""
        self.stdout.write(self.style.HTTP_INFO('Validating Activity Tracking:\n'))

        now = timezone.now()
        cutoff = now - timedelta(days=days)

        # Check users with recent activity but no last_activity_at
        issues = []

        # Users with recent logins but no activity timestamp
        recent_logins_no_activity = User.objects.filter(
            last_login__gte=cutoff,
            last_activity_at__isnull=True
        ).count()
        if recent_logins_no_activity > 0:
            issues.append(f"  ⚠️  {recent_logins_no_activity} users logged in recently but have no last_activity_at")

        # Users with recent transactions but stale activity
        users_with_recent_sends = set(
            SendTransaction.objects
            .filter(created_at__gte=cutoff)
            .values_list('sender_user_id', flat=True)
        )
        for user_id in list(users_with_recent_sends)[:100]:  # Sample
            user = User.objects.filter(id=user_id).first()
            if user and (not user.last_activity_at or user.last_activity_at < cutoff):
                issues.append(f"  ⚠️  User {user_id} has recent send transaction but stale activity timestamp")
                break

        # Summary
        if issues:
            self.stdout.write(self.style.WARNING('Issues Found:'))
            for issue in issues:
                self.stdout.write(issue)
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Recommendation: Run the backfill_last_activity command to sync historical data.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Activity tracking appears to be working correctly!'))

        # Show coverage stats
        total_users = User.objects.count()
        users_with_activity = User.objects.filter(last_activity_at__isnull=False).count()
        coverage = (users_with_activity / total_users * 100) if total_users > 0 else 0

        self.stdout.write('')
        self.stdout.write(f"Activity Tracking Coverage: {users_with_activity:,}/{total_users:,} ({coverage:.1f}%)")
