from django.test import TestCase
from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from usdc_transactions.models import GuardarianTransaction, USDCDeposit
from usdc_transactions.tasks import poll_guardarian_transactions
from users.models import User

class GuardarianTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser', email='test@example.com')
        self.tx = GuardarianTransaction.objects.create(
            guardarian_id='test_gid_123',
            user=self.user,
            from_amount=100,
            from_currency='USD',
            status='waiting',
            created_at=timezone.now()
        )
        
    @patch('usdc_transactions.tasks.requests.get')
    def test_poll_rate_limit_handling(self, mock_get):
        """Test that polling stops on 429 rate limit"""
        # Create multiple transactions to ensure loop would continue without break
        GuardarianTransaction.objects.create(
            guardarian_id='test_gid_456',
            user=self.user,
            from_amount=50,
            from_currency='USD',
            status='waiting',
            created_at=timezone.now()
        )
        
        # Mock 429 response
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp
        
        result = poll_guardarian_transactions()
        
        # Should break after first call
        self.assertEqual(mock_get.call_count, 1)
        self.assertIn('Polled', result)

    @patch('usdc_transactions.tasks.requests.get')
    def test_poll_links_deposit_on_finish(self, mock_get):
        """Test that polling links deposit when status becomes finished"""
        # Create matching deposit
        deposit = USDCDeposit.objects.create(
            actor_user=self.user,
            actor_type='user',
            amount=Decimal('95.000000'),
            source_address='addr1',
            status='COMPLETED'
        )
        
        # Mock successful finished response
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'id': 'test_gid_123',
            'status': 'finished',
            'to_amount': '95.000000'
        }
        mock_get.return_value = mock_resp
        
        poll_guardarian_transactions()
        
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'finished')
        self.assertEqual(self.tx.onchain_deposit, deposit)

    def test_fuzzy_matching_logic(self):
        """Test the fuzzy matching logic in model method"""
        self.tx.status = 'finished'
        self.tx.to_amount_estimated = Decimal('100.000000') # Estimated
        self.tx.to_amount_actual = None # Actual unknown
        self.tx.save()
        
        # Create deposit with 2% difference (within 5% tolerance)
        deposit = USDCDeposit.objects.create(
            actor_user=self.user,
            actor_type='user',
            amount=Decimal('98.000000'),
            source_address='addr_fuzzy',
            status='COMPLETED'
        )
        
        matched = self.tx.attempt_match_deposit()
        
        self.assertEqual(matched, deposit)
        self.assertEqual(self.tx.onchain_deposit, deposit)

    def test_fuzzy_matching_out_of_range(self):
        """Test that fuzzy matching rejects > 5% diff"""
        self.tx.status = 'finished'
        self.tx.to_amount_estimated = Decimal('100.000000')
        self.tx.to_amount_actual = None
        self.tx.save()
        
        # Create deposit with 10% difference
        deposit = USDCDeposit.objects.create(
            actor_user=self.user,
            actor_type='user',
            amount=Decimal('80.000000'),
            source_address='addr_far',
            status='COMPLETED'
        )
        
        matched = self.tx.attempt_match_deposit()
        
        self.assertIsNone(matched)
        self.assertIsNone(self.tx.onchain_deposit)
