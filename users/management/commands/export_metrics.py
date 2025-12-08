"""
Management command to export metrics to CSV or JSON

Usage:
    python manage.py export_metrics --format csv --output metrics.csv
    python manage.py export_metrics --format json --output metrics.json
    python manage.py export_metrics --format csv --start-date 2025-11-01 --end-date 2025-12-06
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import csv
import json
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Export DAU/WAU/MAU metrics to CSV or JSON'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            choices=['csv', 'json'],
            default='csv',
            help='Export format (csv or json)',
        )
        parser.add_argument(
            '--output',
            type=str,
            required=True,
            help='Output file path',
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date for export (YYYY-MM-DD format)',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End-date for export (YYYY-MM-DD format). Defaults to yesterday.',
        )
        parser.add_argument(
            '--include-countries',
            action='store_true',
            help='Include country-specific metrics',
        )
    
    def handle(self, *args, **options):
        from users.models_analytics import DailyMetrics, CountryMetrics
        
        # Parse date range
        if options['start_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid start date: {options['start_date']}"))
                return
        else:
            start_date = None
        
        if options['end_date']:
            try:
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid end date: {options['end_date']}"))
                return
        else:
            end_date = (timezone.now() - timedelta(days=1)).date()
        
        # Build query
        queryset = DailyMetrics.objects.all()
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        queryset = queryset.order_by('date')
        
        # Export based on format
        if options['format'] == 'csv':
            self._export_csv(queryset, options['output'], options['include_countries'])
        else:
            self._export_json(queryset, options['output'], options['include_countries'])
    
    def _export_csv(self, queryset, output_path, include_countries):
        """Export to CSV format"""
        from users.models_analytics import CountryMetrics
        
        try:
            with open(output_path, 'w', newline='') as csvfile:
                # Daily metrics
                fieldnames = ['date', 'dau', 'wau', 'mau', 'total_users', 'new_users_today', 'dau_mau_ratio']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for snapshot in queryset:
                    writer.writerow({
                        'date': snapshot.date,
                        'dau': snapshot.dau,
                        'wau': snapshot.wau,
                        'mau': snapshot.mau,
                        'total_users': snapshot.total_users,
                        'new_users_today': snapshot.new_users_today,
                        'dau_mau_ratio': float(snapshot.dau_mau_ratio),
                    })
                
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Exported {queryset.count()} daily metrics to {output_path}"
                ))
                
                # Country metrics if requested
                if include_countries:
                    country_output = output_path.replace('.csv', '_countries.csv')
                    with open(country_output, 'w', newline='') as country_csvfile:
                        country_fieldnames = ['date', 'country_code', 'dau', 'wau', 'mau', 'total_users', 'new_users_today']
                        country_writer = csv.DictWriter(country_csvfile, fieldnames=country_fieldnames)
                        country_writer.writeheader()
                        
                        dates = queryset.values_list('date', flat=True)
                        country_metrics = CountryMetrics.objects.filter(date__in=dates).order_by('date', 'country_code')
                        
                        for snapshot in country_metrics:
                            country_writer.writerow({
                                'date': snapshot.date,
                                'country_code': snapshot.country_code,
                                'dau': snapshot.dau,
                                'wau': snapshot.wau,
                                'mau': snapshot.mau,
                                'total_users': snapshot.total_users,
                                'new_users_today': snapshot.new_users_today,
                            })
                        
                        self.stdout.write(self.style.SUCCESS(
                            f"✓ Exported {country_metrics.count()} country metrics to {country_output}"
                        ))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Error exporting CSV: {str(e)}"))
            logger.exception("Error in export_metrics CSV export")
            raise
    
    def _export_json(self, queryset, output_path, include_countries):
        """Export to JSON format"""
        from users.models_analytics import CountryMetrics
        
        try:
            data = {
                'daily_metrics': [],
                'export_date': timezone.now().isoformat(),
                'total_records': queryset.count(),
            }
            
            for snapshot in queryset:
                data['daily_metrics'].append({
                    'date': str(snapshot.date),
                    'dau': snapshot.dau,
                    'wau': snapshot.wau,
                    'mau': snapshot.mau,
                    'total_users': snapshot.total_users,
                    'new_users_today': snapshot.new_users_today,
                    'dau_mau_ratio': float(snapshot.dau_mau_ratio),
                })
            
            # Country metrics if requested
            if include_countries:
                data['country_metrics'] = []
                dates = queryset.values_list('date', flat=True)
                country_metrics = CountryMetrics.objects.filter(date__in=dates).order_by('date', 'country_code')
                
                for snapshot in country_metrics:
                    data['country_metrics'].append({
                        'date': str(snapshot.date),
                        'country_code': snapshot.country_code,
                        'dau': snapshot.dau,
                        'wau': snapshot.wau,
                        'mau': snapshot.mau,
                        'total_users': snapshot.total_users,
                        'new_users_today': snapshot.new_users_today,
                    })
            
            with open(output_path, 'w') as jsonfile:
                json.dump(data, jsonfile, indent=2)
            
            self.stdout.write(self.style.SUCCESS(
                f"✓ Exported {queryset.count()} daily metrics to {output_path}"
            ))
            
            if include_countries:
                self.stdout.write(self.style.SUCCESS(
                    f"  Included {len(data.get('country_metrics', []))} country metrics"
                ))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Error exporting JSON: {str(e)}"))
            logger.exception("Error in export_metrics JSON export")
            raise
