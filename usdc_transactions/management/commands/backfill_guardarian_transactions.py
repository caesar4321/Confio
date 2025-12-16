import logging
import requests
import time
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from usdc_transactions.models import GuardarianTransaction, USDCDeposit
from users.models import User

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Backfill Guardarian transactions from specific list of IDs'

    def handle(self, *args, **options):
        self.stdout.write("Starting Guardarian backfill from ID list...")
        
        # provided by user
        # provided by user (Focusing on New/Finished/Recent)
        ids = [
            '5952424252', # new 16/12
            '5054126340', # new 16/12
            '5882230476', # finished 15/12
            '4497890235', # finished 11/12
        ]
        
        total = len(ids)
        self.stdout.write(f"Processing {total} transactions...")
        
        updated_count = 0
        
        for idx, g_id in enumerate(ids, 1):
            if idx % 10 == 0:
                self.stdout.write(f"  Progress: {idx}/{total}")
            
            retries = 3
            while retries > 0:
                try:
                    data = self.fetch_single_transaction(g_id)
                    if data == 429:
                        self.stdout.write(self.style.WARNING(f"  Rate limit hit for {g_id}. Waiting 5s..."))
                        time.sleep(5)
                        retries -= 1
                        continue
                    
                    if not data:
                        self.stdout.write(self.style.WARNING(f"  Tx {g_id}: Not found or API error"))
                        break
                        
                    self.process_transaction(data)
                    updated_count += 1
                    
                    # Sleep to respect rate limits
                    time.sleep(1.0)
                    break
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Tx {g_id} error: {e}"))
                    break

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Processed {updated_count}/{total} transactions."))

    def fetch_single_transaction(self, g_id):
        api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
        base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
        url = f'{base_url.rstrip("/")}/transaction/{g_id}'
        try:
             resp = requests.get(url, headers={'x-api-key': api_key}, timeout=10)
             if resp.ok:
                 return resp.json()
             elif resp.status_code == 429:
                 return 429
             else:
                 self.stdout.write(f"  API Error for {g_id}: {resp.status_code}")
        except Exception as e:
             self.stdout.write(f"  Net Error for {g_id}: {e}")
        return None

    def process_transaction(self, data):
        g_id = str(data.get('id'))
        
        try:
            tx = GuardarianTransaction.objects.get(guardarian_id=g_id)
            created = False
        except GuardarianTransaction.DoesNotExist:
            tx = GuardarianTransaction(guardarian_id=g_id)
            created = True
            
        action = "Created" if created else "Updated"
        
        # Update fields
        tx.status = data.get('status', 'waiting')
        
        if data.get('from_amount') is not None:
            tx.from_amount = Decimal(str(data.get('from_amount')))
        elif created:
            tx.from_amount = Decimal('0')
                
        if data.get('to_amount'):
            tx.to_amount_actual = Decimal(str(data.get('to_amount')))
        if data.get('expected_to_amount'):
             tx.to_amount_estimated = Decimal(str(data.get('expected_to_amount')))

        # Use fetched currency or keep existing
        if data.get('from_currency'):
            tx.from_currency = data.get('from_currency')
        elif created and not tx.from_currency:
            tx.from_currency = 'USD' # Default
            
        tx.to_currency = data.get('to_currency') or 'USDC'
        tx.network = data.get('to_network') or 'ALGO'
        
        if data.get('external_partner_link_id'):
            tx.external_id = data.get('external_partner_link_id')

        # Link User
        user_email = data.get('email') or (data.get('customer') or {}).get('contact_info', {}).get('email')
        self.stdout.write(f"  Debug {g_id}: API Email='{user_email}'")
        
        if user_email and not tx.user:
             user = User.objects.filter(email__iexact=user_email).first()
             if user:
                 tx.user = user
             else:
                 self.stdout.write(f"  Debug {g_id}: No user found for '{user_email}'")
        
        # Match OnChain Deposit
        if tx.user and tx.status == 'finished' and not tx.onchain_deposit:
            self.match_onchain_deposit(tx)
            
        if tx.user:
            tx.save()
            self.stdout.write(f"  {action} {g_id}: {tx.status} ({user_email})")
        else:
            self.stdout.write(self.style.WARNING(f"  Skipped {g_id} (No User Matched: '{user_email}')"))
            # Optional: Print why?
            if user_email:
                 # Check partial match?
                 pass

    def match_onchain_deposit(self, tx):
        candidates = USDCDeposit.objects.filter(
            actor_user=tx.user,
            status='COMPLETED',
            guardarian_source__isnull=True
        ).order_by('-created_at')
        
        matched_dep = None
        
        # Strategy 1: Exact
        if tx.to_amount_actual:
            matched_dep = candidates.filter(amount=tx.to_amount_actual).first()
            
        # Strategy 2: Fuzzy (5%)
        if not matched_dep and tx.to_amount_estimated:
            tolerance = tx.to_amount_estimated * Decimal('0.05')
            for dep in candidates:
                diff = abs(tx.to_amount_estimated - dep.amount)
                if diff <= tolerance:
                    matched_dep = dep
                    break
        
        if matched_dep:
            tx.onchain_deposit = matched_dep
            self.stdout.write(self.style.SUCCESS(f"    Matched Deposit: {matched_dep.deposit_id}"))
