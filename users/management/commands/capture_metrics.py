"""
Management command to capture daily metrics snapshot

Usage:
    python manage.py capture_metrics
    python manage.py capture_metrics --date 2025-12-06
    python manage.py capture_metrics --include-countries
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Capture daily DAU/WAU/MAU metrics snapshot'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to capture metrics for (YYYY-MM-DD format). Defaults to yesterday.',
        )
        parser.add_argument(
            '--include-countries',
            action='store_true',
            help='Also capture country-specific metrics',
        )
    
    def handle(self, *args, **options):
        from users.analytics import snapshot_daily_metrics, snapshot_country_metrics
        
        # Parse target date
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(f"Invalid date format: {options['date']}. Use YYYY-MM-DD")
                )
                return
        else:
            # Default to yesterday
            target_date = (timezone.now() - timedelta(days=1)).date()
        
        self.stdout.write(f"Capturing metrics for {target_date}...")
        
        try:
            # Capture daily metrics
            snapshot = snapshot_daily_metrics(target_date)
            
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Successfully captured daily metrics for {target_date}:\n"
                f"  DAU: {snapshot.dau:,}\n"
                f"  WAU: {snapshot.wau:,}\n"
                f"  MAU: {snapshot.mau:,}\n"
                f"  Total Users: {snapshot.total_users:,}\n"
                f"  New Users: {snapshot.new_users_today:,}\n"
                f"  DAU/MAU Ratio: {snapshot.dau_mau_ratio:.2%}"
            ))
            
            # Capture country metrics if requested
            if options['include_countries']:
                self.stdout.write("\nCapturing country-specific metrics...")
                country_snapshots = snapshot_country_metrics(target_date)
                
                self.stdout.write(self.style.SUCCESS(
                    f"\n✓ Successfully captured metrics for {len(country_snapshots)} countries"
                ))
                
                # Show top 5 countries by MAU
                top_countries = sorted(
                    country_snapshots,
                    key=lambda x: x.mau,
                    reverse=True
                )[:5]
                
                self.stdout.write("\nTop 5 countries by MAU:")
                for snapshot in top_countries:
                    self.stdout.write(
                        f"  {snapshot.country_flag} {snapshot.country_code}: "
                        f"DAU={snapshot.dau:,}, MAU={snapshot.mau:,}"
                    )
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Error capturing metrics: {str(e)}"))
            logger.exception("Error in capture_metrics command")
            raise
