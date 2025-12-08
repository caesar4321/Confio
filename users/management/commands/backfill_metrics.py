"""
Management command to backfill historical metrics

This command estimates historical DAU/WAU/MAU metrics based on current last_activity_at values.

WARNING: Historical backfill is approximate since last_activity_at is continuously updated.
The backfill uses current last_activity_at values to estimate past metrics, which may not
be 100% accurate for dates before the snapshot system was implemented.

Usage:
    python manage.py backfill_metrics --start-date 2025-11-01 --end-date 2025-12-06
    python manage.py backfill_metrics --days 30
    python manage.py backfill_metrics --days 30 --include-countries
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill historical DAU/WAU/MAU metrics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date for backfill (YYYY-MM-DD format)',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date for backfill (YYYY-MM-DD format). Defaults to yesterday.',
        )
        parser.add_argument(
            '--days',
            type=int,
            help='Number of days to backfill (alternative to start-date/end-date)',
        )
        parser.add_argument(
            '--include-countries',
            action='store_true',
            help='Also backfill country-specific metrics',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite existing snapshots',
        )
    
    def handle(self, *args, **options):
        from users.analytics import snapshot_daily_metrics, snapshot_country_metrics
        from users.models_analytics import DailyMetrics
        
        # Determine date range
        if options['days']:
            end_date = (timezone.now() - timedelta(days=1)).date()
            start_date = end_date - timedelta(days=options['days'])
        elif options['start_date'] and options['end_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f"Invalid date format: {e}"))
                return
        elif options['start_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
                end_date = (timezone.now() - timedelta(days=1)).date()
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f"Invalid date format: {e}"))
                return
        else:
            self.stdout.write(self.style.ERROR(
                "Please specify either --days or --start-date (and optionally --end-date)"
            ))
            return
        
        if start_date > end_date:
            self.stdout.write(self.style.ERROR("Start date must be before end date"))
            return
        
        # Calculate number of days
        num_days = (end_date - start_date).days + 1
        
        self.stdout.write(
            self.style.WARNING(
                f"\n⚠️  BACKFILL WARNING:\n"
                f"Historical backfill is approximate since last_activity_at is continuously updated.\n"
                f"Metrics may not be 100% accurate for dates before snapshot system was implemented.\n"
            )
        )
        
        self.stdout.write(
            f"\nBackfilling metrics from {start_date} to {end_date} ({num_days} days)..."
        )
        
        # Check for existing snapshots
        if not options['force']:
            existing = DailyMetrics.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            ).count()
            
            if existing > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n⚠️  Found {existing} existing snapshots in this range.\n"
                        f"Use --force to overwrite them."
                    )
                )
                return
        
        # Backfill each day
        current_date = start_date
        success_count = 0
        error_count = 0
        
        while current_date <= end_date:
            try:
                # Capture daily metrics
                snapshot = snapshot_daily_metrics(current_date)
                
                self.stdout.write(
                    f"  {current_date}: DAU={snapshot.dau:,}, WAU={snapshot.wau:,}, MAU={snapshot.mau:,}"
                )
                
                # Capture country metrics if requested
                if options['include_countries']:
                    snapshot_country_metrics(current_date)
                
                success_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  {current_date}: Error - {str(e)}")
                )
                error_count += 1
                logger.exception(f"Error backfilling metrics for {current_date}")
            
            current_date += timedelta(days=1)
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Backfill complete:\n"
                f"  Success: {success_count} days\n"
                f"  Errors: {error_count} days"
            )
        )
        
        if options['include_countries']:
            self.stdout.write("  Country metrics: Included")
