#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from p2p_exchange.models import P2PTrade, P2PTradeRating
from users.models import User
from django.db import transaction

# Simulate rating trade 14 by user 8
trade_id = 14
user_id = 8

try:
    trade = P2PTrade.objects.get(id=trade_id)
    user = User.objects.get(id=user_id)
    
    print(f"Testing rating for trade {trade_id} by user {user_id}")
    print(f"Trade status: {trade.status}")
    print(f"User is buyer: {trade.buyer_user == user}")
    
    # Check if rating already exists
    existing_personal = P2PTradeRating.objects.filter(
        trade=trade,
        rater_user=user
    ).exists()
    print(f"Existing personal rating: {existing_personal}")
    
    if not existing_personal and trade.buyer_user == user:
        # Try to create the rating
        with transaction.atomic():
            rating = P2PTradeRating.objects.create(
                trade=trade,
                rater_user=user,
                ratee_business=trade.seller_business,
                overall_rating=5,
                comment="Test rating from script"
            )
            print(f"✓ Rating created successfully: {rating.id}")
    else:
        print("✗ Cannot create rating - either already exists or user not buyer")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()