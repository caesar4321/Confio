"""
Django management command to populate ConfioGrowthMetric with Venezuela-focused growth data.
Usage: myvenv/bin/python manage.py populate_growth_metrics
"""

from django.core.management.base import BaseCommand
from achievements.models import ConfioGrowthMetric


class Command(BaseCommand):
    help = 'Populate ConfioGrowthMetric with Venezuela-focused growth data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset existing metrics before adding new ones',
        )

    def handle(self, *args, **options):
        self.stdout.write('Creating Venezuela-focused CONFIO growth metrics...')

        # Venezuela-focused growth metrics (weekly growth during beta stage)
        metrics_data = [
            {
                'metric_type': 'active_users',
                'display_name': 'Usuarios Activos mensual',
                'current_value': '8K+',
                'growth_percentage': '+12% semanal',
                'display_order': 1,
                'is_active': True,
            },
            {
                'metric_type': 'protected_savings',
                'display_name': 'Ahorros Protegidos',
                'current_value': '$1.2M cUSD',
                'growth_percentage': '+25% semanal',
                'display_order': 2,
                'is_active': True,
            },
            {
                'metric_type': 'daily_transactions',
                'display_name': 'Transacciones Diarias',
                'current_value': '2.5K+',
                'growth_percentage': '+18% semanal',
                'display_order': 3,
                'is_active': True,
            },
        ]

        if options['reset']:
            self.stdout.write('Resetting existing metrics...')
            ConfioGrowthMetric.objects.all().delete()

        created_count = 0
        updated_count = 0

        for metric_data in metrics_data:
            metric, created = ConfioGrowthMetric.objects.get_or_create(
                metric_type=metric_data['metric_type'],
                defaults=metric_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Created: {metric.display_name} - {metric.current_value} ({metric.growth_percentage})'
                    )
                )
            else:
                # Update existing metric with new values
                updated = False
                for field, value in metric_data.items():
                    if field != 'metric_type':  # Don't update the key field
                        old_value = getattr(metric, field)
                        if old_value != value:
                            setattr(metric, field, value)
                            updated = True
                
                if updated:
                    metric.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'🔄 Updated: {metric.display_name} - {metric.current_value} ({metric.growth_percentage})'
                        )
                    )
                else:
                    self.stdout.write(
                        f'ℹ️  Unchanged: {metric.display_name} - {metric.current_value} ({metric.growth_percentage})'
                    )

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'🎉 Venezuela-focused growth metrics setup complete! '
                f'Created: {created_count}, Updated: {updated_count}'
            )
        )
        self.stdout.write(
            'These metrics will show Venezuela\'s progress in the CONFIO Token Info screen.'
        )