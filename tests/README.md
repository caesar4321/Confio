# Confío Test Suite

This directory contains integration tests and utility scripts for the Confío project, focusing on Algorand blockchain functionality.

## Directory Structure

```
tests/
├── integration/           # Integration tests requiring Django setup
│   ├── algorand/         # Algorand account & authentication tests
│   ├── rewards/          # Reward claim & referral system tests
│   ├── encoding/         # Transaction encoding/decoding tests
│   └── flows/            # End-to-end flow tests
└── scripts/              # Utility scripts for verification
```

## Test Categories

### Algorand Tests (`integration/algorand/`)
Tests for Algorand account management, authentication, and asset opt-in:
- `test_auto_optin.py` - Auto asset opt-in functionality
- `test_auto_optin_simple.py` - Simplified opt-in test
- `test_sponsor_auth.py` - Sponsor authentication flow
- `test_comprehensive_auth.py` - Complete authentication test suite

### Rewards Tests (`integration/rewards/`)
Tests for the referral reward system and claim functionality:
- `test_actual_claim.py` - Real referrer claim transactions
- `test_new_referrer_claim.py` - New referrer claim flow
- `test_referrer_claim_build.py` - Claim transaction building
- `test_rewards_via_service.py` - Rewards service integration
- `test_two_sided_final.py` - Two-sided reward finalization
- `test_two_sided_reward.py` - Two-sided reward system
- `test_manual_price.py` - Manual price verification

### Encoding Tests (`integration/encoding/`)
Tests for Algorand transaction encoding and decoding:
- `test_backend_transaction_encoding.py` - Backend transaction encoding
- `test_decode_client_signed.py` - Client-signed transaction decoding
- `test_python_encoding_boxes.py` - Box reference encoding
- `test_signed_transaction_encoding.py` - Signed transaction encoding

### Flow Tests (`integration/flows/`)
End-to-end integration tests:
- `test_full_flow.py` - Complete user flow testing

### Scripts (`scripts/`)
Utility scripts for verification and debugging:
- `verify_contract_price.py` - Contract price verification

## Running Tests

All integration tests require Django to be set up. Each test is a standalone script:

```bash
# From project root
cd /Users/julian/Confio

# Run a specific test
myvenv/bin/python tests/integration/algorand/test_auto_optin.py

# Or make executable and run directly
chmod +x tests/integration/rewards/test_actual_claim.py
./tests/integration/rewards/test_actual_claim.py
```

## Environment Requirements

These tests require:
- Django environment with proper settings (`config.settings`)
- Algorand testnet access (configured in environment variables)
- Database with test data (users, accounts, etc.)

## Important Notes

1. **Manual Tests**: These are integration tests designed to be run manually, not automated unit tests
2. **Django Setup**: All tests include Django setup code at the top
3. **Test Data**: Some tests reference specific users/addresses and may need updating
4. **Network Access**: Tests interact with Algorand testnet and require network connectivity

## Converting to Unit Tests

To convert these into proper Django unit tests:

1. Use `django.test.TestCase` base class
2. Use fixtures for test data
3. Mock external blockchain calls
4. Add to Django test runner configuration
5. Create proper assertions instead of print statements

Example:
```python
from django.test import TestCase
from users.models import User

class RewardsTestCase(TestCase):
    fixtures = ['test_users.json']

    def test_referrer_claim(self):
        user = User.objects.get(username='test_user')
        # ... test logic
        self.assertEqual(expected, actual)
```

## Contributing

When adding new tests:
1. Place in appropriate category directory
2. Use descriptive filenames starting with `test_`
3. Include docstrings explaining what the test does
4. Document any required test data or environment setup
5. Update this README if adding new categories
