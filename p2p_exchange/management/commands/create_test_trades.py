from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from p2p_exchange.models import P2POffer, P2PTrade, P2PPaymentMethod
from decimal import Decimal
from datetime import datetime, timedelta
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Create test trades for P2P WebSocket testing'

    def handle(self, *args, **options):
        # Use existing users
        try:
            user1 = User.objects.get(username='julianmoonluna')
            user2 = User.objects.get(username='julian')
        except User.DoesNotExist:
            # Fallback to any two users
            users = list(User.objects.all()[:2])
            if len(users) < 2:
                self.stdout.write(
                    self.style.ERROR('Need at least 2 users in the database to create test trades')
                )
                return
            user1, user2 = users[0], users[1]
            
        self.stdout.write(f'Using users: {user1.username} and {user2.username}')
        
        # Create test payment method
        payment_method, created = P2PPaymentMethod.objects.get_or_create(
            name='test_payment',
            defaults={
                'display_name': 'Test Payment Method',
                'is_active': True,
                'icon': 'test',
                'country_code': 'VE'
            }
        )
        
        # Create test offer
        offer, created = P2POffer.objects.get_or_create(
            offer_user=user1,
            exchange_type='SELL',
            token_type='cUSD',
            rate=Decimal('36.50'),
            min_amount=Decimal('10.00'),
            max_amount=Decimal('1000.00'),
            available_amount=Decimal('500.00'),
            country_code='VE',
            defaults={
                'user': user1,  # Backward compatibility
                'terms': 'Test offer for WebSocket testing',
                'response_time_minutes': 15,
                'status': 'ACTIVE'
            }
        )
        
        if created:
            offer.payment_methods.add(payment_method)
        
        # Create test trade
        trade, created = P2PTrade.objects.get_or_create(
            offer=offer,
            buyer_user=user2,
            seller_user=user1,
            crypto_amount=Decimal('100.00'),
            fiat_amount=Decimal('3650.00'),
            rate_used=Decimal('36.50'),
            payment_method=payment_method,
            defaults={
                'buyer': user2,  # Backward compatibility
                'seller': user1,  # Backward compatibility
                'status': 'PENDING',
                'expires_at': timezone.now() + timedelta(hours=1)
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created test trade with ID: {trade.id}')
            )
            self.stdout.write(
                self.style.SUCCESS(f'WebSocket URL: ws://localhost:8000/ws/trade/{trade.id}/')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Test trade already exists with ID: {trade.id}')
            )
            self.stdout.write(
                self.style.SUCCESS(f'WebSocket URL: ws://localhost:8000/ws/trade/{trade.id}/')
            )