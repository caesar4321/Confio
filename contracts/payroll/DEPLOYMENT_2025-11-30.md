# Payroll Contract Redeployment - November 30, 2025

## Summary

Successfully redeployed the Confío payroll escrow contract to fix vault key mismatch issues that were preventing delegate-initiated payouts from working.

## Problem

The old contract (app ID: 750067819) was failing delegate payouts with "insufficient vault funds" errors even though the vault had ~1.18 cUSD. Analysis revealed:

1. Transaction structure was correct - `accounts[0]` was the business address
2. Vault existed on-chain with sufficient funds
3. **Root cause**: The deployed contract bytecode didn't match the source code, causing vault key lookups to fail

## Solution

Redeployed the contract from the current source code to ensure the deployed bytecode matches expectations.

## Deployment Details

### New Contract

- **App ID**: `750524790`
- **App Address**: `NXKVZAX4IL7ULHG3CBR2XO7PMFQ6XQ7GQCA3YYTQUIX4AKIDWOJA6XFQ4Q`
- **Deployment Date**: 2025-11-30
- **Network**: Algorand Testnet

### Configuration

- **Admin**: `PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY`
- **Fee Recipient**: `PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY`
- **Payroll Asset**: `744368179` (cUSD testnet)
- **Status**: Active (not paused)

### Delegates Configured

For business `PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME`:

1. `P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU` (delegate)
2. `PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME` (self)

## Django Settings Updated

File: `/Users/julian/Confio/config/settings.py`

```python
'ALGORAND_PAYROLL_APP_ID': config('ALGORAND_PAYROLL_APP_ID', default=750524790, cast=int),
'ALGORAND_PAYROLL_ASSET_ID': config('ALGORAND_PAYROLL_ASSET_ID', default=744368179, cast=int),
```

## Migration Notes

### Old Contract

- **App ID**: `750067819` (now deprecated)
- **Vault Balance**: ~1.18 cUSD (cannot be recovered - no withdrawal function)
- **Status**: Will remain on-chain but no longer used

### Vault Funds

The old contract does not have an admin withdrawal function, so the ~1.18 cUSD locked in the old vault cannot be recovered. The business will need to fund the new vault with fresh cUSD.

**Required action**: Business owner should fund the new vault with at least 1.2 cUSD to cover pending payroll obligations.

## Deployment Steps Completed

1. ✅ Deployed new contract (app ID: 750524790)
2. ✅ Funded contract with 0.5 ALGO for MBR
3. ✅ Opted contract into cUSD asset (744368179)
4. ✅ Set fee recipient to admin address
5. ✅ Added delegate allowlists (2 delegates for PZL4... business)
6. ✅ Updated Django settings with new app ID
7. ✅ Verified contract configuration

## Testing Recommendations

1. **Fund the vault**:
   - Business owner should use the mobile app: Settings → Payroll → Add Funds
   - Recommended amount: 1.2 cUSD (to replace old vault + buffer)

2. **Test delegate payout**:
   - Use delegate account (P7WYM...) to initiate a small test payout (0.01 cUSD)
   - Verify transaction succeeds end-to-end
   - Check recipient receives funds
   - Verify vault balance decrements correctly

3. **Monitor**:
   - Watch for any errors in production payouts
   - Verify vault box key is correct: `VAULT + PZL4...`
   - Confirm `accounts[0]` is always the business address

## Transaction Structure (Verified)

The new contract expects:
- **Sender**: Delegate address (e.g., P7WYM...)
- **accounts[0]**: Business address (PZL4...)
- **accounts[1]**: Recipient address
- **accounts[2]**: Fee recipient (PFFGG...)
- **Vault key**: `"VAULT" + business_address`
- **Allowlist key**: `business_address + delegate_address`

## Files Created

- `/Users/julian/Confio/contracts/payroll/debug_deployed_contract.py` - Diagnostic tool
- `/Users/julian/Confio/contracts/payroll/setup_delegates.py` - Delegate setup script
- `/Users/julian/Confio/contracts/payroll/fund_vault_manual.py` - Funding helper
- `/Users/julian/Confio/contracts/verify_deployment_simple.py` - Verification script
- `/Users/julian/Confio/contracts/payroll/DEPLOYMENT_2025-11-30.md` - This document

## Next Steps

1. **Restart Django server** to pick up new settings (if running)
2. **Fund the new vault** from business account (~1.2 cUSD)
3. **Test a payout** with delegate account to verify fix
4. **Update mobile app** if needed (settings should pick up new app ID automatically)
5. **Notify users** that payroll is back online

## Rollback Plan

If issues arise:
1. Revert `config/settings.py` to old app ID (750067819)
2. Restart Django server
3. Old vault still has 1.18 cUSD available
4. Investigate and redeploy as needed

## Contact

For questions about this deployment, refer to:
- Contract source: `/Users/julian/Confio/contracts/payroll/payroll.py`
- Transaction builder: `/Users/julian/Confio/blockchain/payroll_transaction_builder.py`
- Schema: `/Users/julian/Confio/payroll/schema.py`
