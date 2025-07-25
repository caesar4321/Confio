# Migration Plan: Salt Formula Update with Business ID

## Overview
We're updating the zkLogin salt generation formula to include `business_id` to support multiple accounts per business in the future. The new formula is:
```
salt = SHA256(issuer | subject | audience | account_type | business_id | account_index)
```

## Impact Analysis

### Affected Components
1. **Frontend (React Native App)**
   - `apps/src/utils/zkLogin.ts` - Salt generation function ✅ Updated
   - `apps/src/services/authService.ts` - Auth service integration ✅ Updated
   - `apps/src/screens/CreateBusinessScreen.tsx` - Business account creation ✅ Updated

2. **Backend (Django)**
   - Account model already has business reference ✅
   - No changes needed to database schema

3. **Existing Accounts**
   - Personal accounts: Not affected (business_id is empty string)
   - Business accounts: Will get new Sui addresses after migration

## Migration Strategy

### Phase 1: Code Deployment (Completed)
1. ✅ Update `generateZkLoginSalt` function to accept `businessId` parameter
2. ✅ Update `AccountContext` interface to include `businessId`
3. ✅ Update `AccountManager.getActiveAccountContext` to fetch businessId
4. ✅ Update `AuthService.switchAccount` to include businessId
5. ✅ Update `CreateBusinessScreen` to pass businessId when creating accounts

### Phase 2: User Migration (To Be Done)
Since Sui addresses are generated client-side, we need users to re-authenticate:

1. **Soft Migration Approach** (Recommended)
   - Deploy updated app version
   - When users open the app, detect if their account needs migration
   - Show a one-time migration prompt explaining the update
   - Re-generate Sui addresses with new salt formula
   - Update addresses on the server

2. **Implementation Steps**
   ```typescript
   // In AccountManager or AuthService
   async checkAccountMigration() {
     const accounts = await this.getStoredAccounts();
     for (const account of accounts) {
       if (account.type === 'business' && account.business?.id) {
         // Check if address was generated with old formula
         const oldSalt = generateZkLoginSalt(iss, sub, aud, 'business', '', account.index);
         const newSalt = generateZkLoginSalt(iss, sub, aud, 'business', account.business.id, account.index);
         
         if (oldSalt !== newSalt) {
           // Account needs migration
           return true;
         }
       }
     }
     return false;
   }
   ```

### Phase 3: Verification
1. Monitor logs for successful address updates
2. Verify business accounts can still access their funds
3. Test multi-account creation for businesses

## Rollback Plan
If issues arise:
1. Revert to previous app version
2. Salt formula for personal accounts remains unchanged
3. Business accounts can temporarily use old addresses

## Timeline
- Phase 1: ✅ Completed
- Phase 2: Deploy with next app update
- Phase 3: Monitor for 1 week after deployment

## Notes
- Personal accounts are unaffected (business_id = '')
- This change enables future scalability for multiple business accounts
- No data loss - only address calculation changes