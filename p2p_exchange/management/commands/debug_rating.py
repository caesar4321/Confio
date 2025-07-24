from django.core.management.base import BaseCommand
from django.db import models
from p2p_exchange.models import P2PTrade, P2PTradeRating
from users.models import User

class Command(BaseCommand):
    help = 'Debug rating issues for a specific trade'

    def add_arguments(self, parser):
        parser.add_argument('trade_id', type=int, help='Trade ID to debug')
        parser.add_argument('user_id', type=int, help='User ID trying to rate')
        parser.add_argument('--account-type', default='personal', help='Account type (personal/business)')
        parser.add_argument('--account-index', type=int, default=0, help='Account index')

    def handle(self, *args, **options):
        trade_id = options['trade_id']
        user_id = options['user_id']
        account_type = options['account_type']
        account_index = options['account_index']

        try:
            trade = P2PTrade.objects.get(id=trade_id)
            user = User.objects.get(id=user_id)
            
            self.stdout.write(f"\n=== Debugging Trade {trade_id} ===")
            self.stdout.write(f"Status: {trade.status}")
            self.stdout.write(f"Buyer: user={trade.buyer_user_id}, business={trade.buyer_business_id}")
            self.stdout.write(f"Seller: user={trade.seller_user_id}, business={trade.seller_business_id}")
            
            self.stdout.write(f"\n=== User {user_id} ({user.username}) ===")
            self.stdout.write(f"Trying to rate as: {account_type}_{account_index}")
            
            # Check if user is part of the trade
            is_buyer = False
            is_seller = False
            
            if account_type == 'business':
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=account_index).exists():
                    is_buyer = True
                    self.stdout.write(f"✓ User is buyer as business {trade.buyer_business.id}")
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=account_index).exists():
                    is_seller = True
                    self.stdout.write(f"✓ User is seller as business {trade.seller_business.id}")
                else:
                    self.stdout.write("✗ User not found as business in this trade")
            else:
                if trade.buyer_user == user:
                    is_buyer = True
                    self.stdout.write("✓ User is buyer (personal)")
                elif trade.seller_user == user:
                    is_seller = True
                    self.stdout.write("✓ User is seller (personal)")
                else:
                    self.stdout.write("✗ User not found as personal account in this trade")
            
            # Check existing ratings
            self.stdout.write(f"\n=== Existing Ratings ===")
            ratings = P2PTradeRating.objects.filter(trade=trade)
            for rating in ratings:
                rater = f"user {rating.rater_user_id}" if rating.rater_user else f"business {rating.rater_business_id}"
                ratee = f"user {rating.ratee_user_id}" if rating.ratee_user else f"business {rating.ratee_business_id}"
                self.stdout.write(f"Rating {rating.id}: {rater} rated {ratee} with {rating.overall_rating} stars")
            
            # Check if this specific account has already rated
            self.stdout.write(f"\n=== Can User Rate? ===")
            if account_type == 'business':
                business_accounts = list(user.accounts.filter(
                    account_type='business',
                    deleted_at__isnull=True
                ).select_related('business').order_by('account_index'))
                
                if account_index < len(business_accounts):
                    business = business_accounts[account_index].business
                    if business:
                        existing = P2PTradeRating.objects.filter(
                            trade=trade,
                            rater_business=business
                        ).exists()
                        if existing:
                            self.stdout.write(f"✗ Business {business.id} has already rated this trade")
                        else:
                            self.stdout.write(f"✓ Business {business.id} can rate this trade")
            else:
                existing = P2PTradeRating.objects.filter(
                    trade=trade,
                    rater_user=user
                ).exists()
                if existing:
                    self.stdout.write(f"✗ User {user.id} has already rated this trade")
                else:
                    self.stdout.write(f"✓ User {user.id} can rate this trade")
                    
        except P2PTrade.DoesNotExist:
            self.stdout.write(f"Trade {trade_id} not found")
        except User.DoesNotExist:
            self.stdout.write(f"User {user_id} not found")