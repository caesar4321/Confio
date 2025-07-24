from django.core.management.base import BaseCommand
from p2p_exchange.models import P2PUserStats
import random
from decimal import Decimal

class Command(BaseCommand):
    help = 'Populate P2P user stats with sample data'

    def handle(self, *args, **options):
        stats_records = P2PUserStats.objects.all()
        
        if not stats_records.exists():
            self.stdout.write(self.style.WARNING('No P2PUserStats records found'))
            return
        
        for stats in stats_records:
            # Generate random but realistic data
            total_trades = random.randint(10, 500)
            completed_trades = int(total_trades * random.uniform(0.85, 0.99))
            cancelled_trades = total_trades - completed_trades
            
            # Calculate success rate
            if total_trades > 0:
                success_rate = Decimal(str(round((completed_trades / total_trades) * 100, 2)))
            else:
                success_rate = Decimal('0.00')
            
            # Random response time between 5 and 60 minutes
            avg_response_time = random.randint(5, 60)
            
            # Update the stats
            stats.total_trades = total_trades
            stats.completed_trades = completed_trades
            stats.cancelled_trades = cancelled_trades
            stats.success_rate = success_rate
            stats.avg_response_time = avg_response_time
            stats.is_verified = random.choice([True, True, False])  # 66% chance of being verified
            
            # Add random average rating for users with completed trades
            if completed_trades > 0:
                # Higher success rate tends to have higher ratings
                base_rating = 3.5 if success_rate < 90 else 4.0 if success_rate < 95 else 4.5
                stats.avg_rating = Decimal(str(round(base_rating + random.uniform(-0.5, 0.5), 2)))
            else:
                stats.avg_rating = Decimal('0.00')
            
            stats.save()
            
            display_name = stats.stats_display_name
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated stats for {display_name}: '
                    f'{completed_trades}/{total_trades} trades, '
                    f'{success_rate}% success, '
                    f'{avg_response_time}min response time'
                )
            )
        
        self.stdout.write(self.style.SUCCESS(f'Successfully updated {stats_records.count()} user stats'))