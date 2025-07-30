"""
Management command to clean up invalid FCM tokens
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from notifications.models import FCMDeviceToken


class Command(BaseCommand):
    help = 'Clean up invalid and stale FCM tokens'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it',
        )
        parser.add_argument(
            '--days-inactive',
            type=int,
            default=90,
            help='Number of days of inactivity before considering a token stale (default: 90)',
        )
        parser.add_argument(
            '--max-failures',
            type=int,
            default=5,
            help='Maximum failure count before deactivating a token (default: 5)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days_inactive = options['days_inactive']
        max_failures = options['max_failures']
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        # Find tokens with too many failures
        failed_tokens = FCMDeviceToken.objects.filter(
            is_active=True,
            failure_count__gte=max_failures
        )
        
        failed_count = failed_tokens.count()
        if failed_count > 0:
            self.stdout.write(
                f"Found {failed_count} token(s) with {max_failures}+ failures"
            )
            if not dry_run:
                failed_tokens.update(
                    is_active=False,
                    last_failure_reason='Too many failures'
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Deactivated {failed_count} failed token(s)")
                )
        
        # Find stale tokens (not used in X days)
        cutoff_date = timezone.now() - timedelta(days=days_inactive)
        stale_tokens = FCMDeviceToken.objects.filter(
            is_active=True,
            last_used__lt=cutoff_date
        )
        
        stale_count = stale_tokens.count()
        if stale_count > 0:
            self.stdout.write(
                f"Found {stale_count} token(s) not used since {cutoff_date.date()}"
            )
            if not dry_run:
                stale_tokens.update(
                    is_active=False,
                    last_failure_reason=f'Inactive for {days_inactive}+ days'
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Deactivated {stale_count} stale token(s)")
                )
        
        # Find duplicate tokens (same token for different users/devices)
        from django.db.models import Count
        duplicates = FCMDeviceToken.objects.values('token').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        if duplicates:
            self.stdout.write(f"Found {len(duplicates)} duplicate token(s)")
            
            for dup in duplicates:
                token_value = dup['token']
                # Keep the most recent one, deactivate others
                tokens = FCMDeviceToken.objects.filter(
                    token=token_value
                ).order_by('-last_used')
                
                if not dry_run:
                    # Keep first (most recent), deactivate rest
                    tokens_to_deactivate = tokens[1:]
                    for token in tokens_to_deactivate:
                        token.is_active = False
                        token.last_failure_reason = 'Duplicate token'
                        token.save()
                    
                    self.stdout.write(
                        f"Deactivated {len(tokens_to_deactivate)} duplicate(s) of token ending in ...{token_value[-10:]}"
                    )
        
        # Summary
        total_active = FCMDeviceToken.objects.filter(is_active=True).count()
        total_inactive = FCMDeviceToken.objects.filter(is_active=False).count()
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nToken Summary:\n"
                f"Active tokens: {total_active}\n"
                f"Inactive tokens: {total_inactive}\n"
                f"Total tokens: {total_active + total_inactive}"
            )
        )
        
        # Show tokens by device type
        self.stdout.write("\nTokens by device type:")
        for device_type in ['ios', 'android', 'web']:
            count = FCMDeviceToken.objects.filter(
                device_type=device_type,
                is_active=True
            ).count()
            self.stdout.write(f"  {device_type.upper()}: {count}")
        
        # Show recent failures
        recent_failures = FCMDeviceToken.objects.filter(
            last_failure__isnull=False,
            last_failure__gte=timezone.now() - timedelta(days=7)
        ).order_by('-last_failure')[:10]
        
        if recent_failures:
            self.stdout.write("\nRecent failures (last 7 days):")
            for token in recent_failures:
                self.stdout.write(
                    f"  User: {token.user.email}, "
                    f"Device: {token.device_type}, "
                    f"Reason: {token.last_failure_reason}, "
                    f"Time: {token.last_failure}"
                )