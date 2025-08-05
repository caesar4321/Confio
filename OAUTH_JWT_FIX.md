# OAuth JWT Fix for Aptos Keyless Addresses

## Problem
Aptos addresses weren't changing when OAuth Client ID was changed because:
1. The backend JWT (created by Django) was missing `iss` and `aud` fields from the OAuth provider
2. The client might have been using the backend JWT instead of the OAuth JWT for pepper generation

## Solution Implemented

### 1. Fixed Account Switching (authService.ts)
When switching accounts, the app now:
- Uses the OAuth JWT (stored in `currentAccount.jwt`) 
- Derives a new Keyless account with the new account context
- Updates the stored Keyless data with the new address

### 2. JWT Usage Clarification
- **OAuth JWT**: Contains `iss`, `sub`, `aud` from Google/Apple. Used for ALL Aptos Keyless operations
- **Backend JWT**: Created by Django for API authentication only. Should NEVER be used for address derivation

### 3. Pepper Generation Formula
The pepper is deterministically generated as:
```
SHA256(iss_sub_aud_account_type_[business_id_]account_index)
```
Where:
- `iss`: OAuth provider issuer (e.g., "https://accounts.google.com")
- `sub`: User's unique ID from OAuth provider
- `aud`: OAuth Client ID (THIS is what changed!)
- `account_type`: "personal" or "business"
- `business_id`: Only included for business accounts
- `account_index`: 0, 1, 2, etc.

## Testing the Fix

1. Sign in with Google/Apple
2. Check the console logs for:
   - `[AuthService] JWT decoded - aud:` should show your OAuth Client ID
   - `[AuthService] Using deterministic pepper for account:`
   - `[AuthService] New Keyless address for account:` when switching accounts

3. Switch between accounts and verify addresses change

## Key Files Modified
- `apps/src/services/authService.ts`: Added proper account derivation on switch
- Added logging to debug JWT contents and pepper generation

## Important Notes
- The OAuth JWT must be preserved throughout the session
- Never use the backend JWT for Aptos operations
- Each account context (personal_0, business_X_0, etc.) should have a unique address