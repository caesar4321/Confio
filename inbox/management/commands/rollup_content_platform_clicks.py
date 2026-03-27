from datetime import date

from django.core.management.base import BaseCommand

from inbox.click_tracking import (
    aggregate_content_platform_clicks_for_date,
    aggregate_pending_content_platform_clicks,
    purge_old_content_platform_clicks,
    rollup_and_cleanup_content_platform_clicks,
)


class Command(BaseCommand):
    help = 'Aggregate raw content platform clicks into daily stats and optionally purge old raw rows.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=date.fromisoformat,
            help='Aggregate a specific date only (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--through-date',
            type=date.fromisoformat,
            help='Aggregate all raw click dates up to and including this date.',
        )
        parser.add_argument(
            '--retention-days',
            type=int,
            default=90,
            help='Retention window for raw click events before purge (default: 90).',
        )
        parser.add_argument(
            '--purge-only',
            action='store_true',
            help='Skip aggregation and only purge raw rows older than the retention window.',
        )

    def handle(self, *args, **options):
        retention_days = options['retention_days']

        if options['purge_only']:
            purge_result = purge_old_content_platform_clicks(retention_days=retention_days)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Purged {purge_result['deleted_rows']} raw click rows older than {retention_days} days."
                )
            )
            return

        if options['date']:
            result = aggregate_content_platform_clicks_for_date(options['date'])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Aggregated {result['groups']} group(s) for {result['date']}."
                )
            )
            return

        if options['through_date']:
            result = aggregate_pending_content_platform_clicks(through_date=options['through_date'])
        else:
            result = rollup_and_cleanup_content_platform_clicks(retention_days=retention_days)
            purge = result['purge']
            self.stdout.write(
                self.style.SUCCESS(
                    f"Purged {purge['deleted_rows']} raw click rows older than {retention_days} days."
                )
            )
            result = result['aggregation']

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {result['dates_processed']} date(s) through {result['through_date']}."
            )
        )
