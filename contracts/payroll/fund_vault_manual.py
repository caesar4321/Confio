#!/usr/bin/env python3
"""
Manual vault funding helper for the new payroll contract

This script shows how to fund the vault. The business owner should use the
mobile app or web interface to fund the vault through the Django backend.

For manual testing, this script can be used with the business account credentials.
"""

import os
import sys

print("=" * 80)
print("PAYROLL VAULT FUNDING")
print("=" * 80)
print(f"\nNew contract app ID: 750524790")
print(f"Business: PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME")
print(f"\nOld vault balance (cannot be recovered): ~1.18 cUSD")
print(f"\nTo fund the new vault:")
print(f"  1. Use the mobile app: Settings → Payroll → Add Funds")
print(f"  2. Or use GraphQL mutation: preparePayrollVaultFunding(amount: 1.2)")
print(f"  3. Or run from Django shell:")
print(f"")
print(f"     from payroll.schema import PreparePayrollVaultFunding")
print(f"     # (use as business account with proper context)")
print("=" * 80)
