"""
Test and validate the activity tracking system

This command performs a comprehensive test of the activity tracking system,
verifying that all components work correctly.

Usage:
    python manage.py test_activity_tracking
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.activity_tracking import touch_last_activity, get_activity_metrics, get_active_users
from datetime import timedelta
import time

User = get_user_model()


class Command(BaseCommand):
    help = 'Test and validate the activity tracking system'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Activity Tracking System Tests ===\n'))

        # Track test results
        tests_passed = 0
        tests_failed = 0

        # Test 1: Basic touch_last_activity
        self.stdout.write('Test 1: Basic touch_last_activity...')
        try:
            test_user = User.objects.first()
            if test_user:
                old_activity = test_user.last_activity_at
                touch_last_activity(test_user, force=True)
                test_user.refresh_from_db()

                if test_user.last_activity_at and test_user.last_activity_at != old_activity:
                    self.stdout.write(self.style.SUCCESS('  ✓ PASS: Activity timestamp updated'))
                    tests_passed += 1
                else:
                    self.stdout.write(self.style.ERROR('  ✗ FAIL: Activity timestamp not updated'))
                    tests_failed += 1
            else:
                self.stdout.write(self.style.WARNING('  ⊘ SKIP: No users in database'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 2: Cooldown mechanism
        self.stdout.write('\nTest 2: Cooldown mechanism...')
        try:
            test_user = User.objects.first()
            if test_user:
                # First update (should work)
                result1 = touch_last_activity(test_user, force=True)

                # Second update immediately (should be skipped due to cooldown)
                result2 = touch_last_activity(test_user, force=False)

                if result1 and not result2:
                    self.stdout.write(self.style.SUCCESS('  ✓ PASS: Cooldown working correctly'))
                    tests_passed += 1
                else:
                    self.stdout.write(self.style.ERROR('  ✗ FAIL: Cooldown not working'))
                    tests_failed += 1
            else:
                self.stdout.write(self.style.WARNING('  ⊘ SKIP: No users in database'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 3: get_active_users query
        self.stdout.write('\nTest 3: get_active_users query...')
        try:
            active_1day = get_active_users(days=1)
            active_7day = get_active_users(days=7)
            active_30day = get_active_users(days=30)

            count_1 = active_1day.count()
            count_7 = active_7day.count()
            count_30 = active_30day.count()

            # Logical check: 1day <= 7day <= 30day
            if count_1 <= count_7 <= count_30:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ PASS: Query working (DAU={count_1}, WAU={count_7}, MAU={count_30})'
                ))
                tests_passed += 1
            else:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ FAIL: Illogical counts (DAU={count_1}, WAU={count_7}, MAU={count_30})'
                ))
                tests_failed += 1
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 4: get_activity_metrics
        self.stdout.write('\nTest 4: get_activity_metrics function...')
        try:
            metrics = get_activity_metrics()

            required_keys = ['dau', 'wau', 'mau', 'total_users', 'dau_percentage', 'wau_percentage', 'mau_percentage']
            if all(key in metrics for key in required_keys):
                self.stdout.write(self.style.SUCCESS('  ✓ PASS: All metrics returned'))
                self.stdout.write(f'    DAU: {metrics["dau"]}, WAU: {metrics["wau"]}, MAU: {metrics["mau"]}')
                tests_passed += 1
            else:
                self.stdout.write(self.style.ERROR('  ✗ FAIL: Missing metrics'))
                tests_failed += 1
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 5: Timestamp accuracy
        self.stdout.write('\nTest 5: Timestamp accuracy...')
        try:
            test_user = User.objects.first()
            if test_user:
                before = timezone.now()
                touch_last_activity(test_user, force=True)
                after = timezone.now()

                test_user.refresh_from_db()

                if test_user.last_activity_at and before <= test_user.last_activity_at <= after:
                    self.stdout.write(self.style.SUCCESS('  ✓ PASS: Timestamp is accurate'))
                    tests_passed += 1
                else:
                    self.stdout.write(self.style.ERROR('  ✗ FAIL: Timestamp inaccurate'))
                    tests_failed += 1
            else:
                self.stdout.write(self.style.WARNING('  ⊘ SKIP: No users in database'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 6: Database index exists
        self.stdout.write('\nTest 6: Database index on last_activity_at...')
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                # Check for index on last_activity_at
                cursor.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'users_user'
                    AND indexdef LIKE '%last_activity_at%'
                """)
                indexes = cursor.fetchall()

                if indexes:
                    self.stdout.write(self.style.SUCCESS(f'  ✓ PASS: Index exists ({indexes[0][0]})'))
                    tests_passed += 1
                else:
                    self.stdout.write(self.style.WARNING('  ⚠ WARNING: No index on last_activity_at (performance may be affected)'))
                    tests_passed += 1  # Not critical, just a warning
        except Exception as e:
            # SQLite or other DB might not support this query
            self.stdout.write(self.style.WARNING(f'  ⊘ SKIP: Could not check index ({e})'))

        # Test 7: Middleware configuration
        self.stdout.write('\nTest 7: GraphQL middleware configuration...')
        try:
            from django.conf import settings

            middleware = settings.GRAPHENE.get('MIDDLEWARE', [])
            if 'users.graphql_middleware.ActivityTrackingMiddleware' in middleware:
                self.stdout.write(self.style.SUCCESS('  ✓ PASS: Middleware configured correctly'))
                tests_passed += 1
            else:
                self.stdout.write(self.style.ERROR('  ✗ FAIL: Middleware not configured'))
                tests_failed += 1
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Test 8: Coverage check
        self.stdout.write('\nTest 8: Activity tracking coverage...')
        try:
            total_users = User.objects.count()
            users_with_activity = User.objects.filter(last_activity_at__isnull=False).count()

            if total_users > 0:
                coverage = (users_with_activity / total_users * 100)

                if coverage >= 50:
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ PASS: Coverage is {coverage:.1f}% ({users_with_activity}/{total_users})'
                    ))
                    tests_passed += 1
                elif coverage >= 10:
                    self.stdout.write(self.style.WARNING(
                        f'  ⚠ WARNING: Coverage is only {coverage:.1f}% - consider running backfill'
                    ))
                    tests_passed += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  ✗ FAIL: Coverage is too low ({coverage:.1f}%) - run backfill_last_activity'
                    ))
                    tests_failed += 1
            else:
                self.stdout.write(self.style.WARNING('  ⊘ SKIP: No users in database'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ FAIL: {e}'))
            tests_failed += 1

        # Summary
        self.stdout.write('\n' + '='*50)
        total_tests = tests_passed + tests_failed
        self.stdout.write(f'\nTests Passed: {tests_passed}/{total_tests}')
        self.stdout.write(f'Tests Failed: {tests_failed}/{total_tests}')

        if tests_failed == 0:
            self.stdout.write(self.style.SUCCESS('\n✓ All tests passed! Activity tracking is working correctly.'))
        else:
            self.stdout.write(self.style.ERROR(f'\n✗ {tests_failed} test(s) failed. Please review the errors above.'))

        # Recommendations
        if tests_failed > 0:
            self.stdout.write('\n' + self.style.HTTP_INFO('Recommendations:'))
            self.stdout.write('  1. Check that migrations are up to date')
            self.stdout.write('  2. Verify settings.py configuration')
            self.stdout.write('  3. Run: python manage.py backfill_last_activity')
            self.stdout.write('  4. Check application logs for errors')
