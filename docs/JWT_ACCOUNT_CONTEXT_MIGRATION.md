# JWT Account Context Migration Guide

## Overview
We're migrating from using custom headers (`X-Active-Account-Type` and `X-Active-Account-Index`) to embedding account context directly in the JWT token. This provides better security and consistency.

## Changes Made

### 1. Backend (Django)
- ✅ Updated `jwt_payload_handler` to include account context fields:
  - `account_type`: 'personal' or 'business'
  - `account_index`: Account index (0, 1, 2, etc.)
  - `business_id`: Business ID for business accounts (None for personal)
- ✅ Updated `RefreshToken` mutation to preserve account context
- ✅ Modified middleware to extract account context from JWT (with fallback to headers)

### 2. Frontend (React Native)
- ✅ Removed X-Active-Account headers from Apollo client
- ⚠️ Need to implement JWT refresh on account switch

## Implementation Notes

### JWT Payload Structure
```json
{
  "user_id": 123,
  "username": "user@example.com",
  "exp": 1234567890,
  "type": "access",
  "auth_token_version": 1,
  // New fields:
  "account_type": "business",
  "account_index": 0,
  "business_id": "uuid-here"
}
```

### Account Switching Flow
1. User selects different account
2. Client needs to request new JWT with updated account context
3. Store new JWT and use for subsequent requests

### Migration Strategy
1. **Phase 1**: Deploy backend changes (✅ Complete)
   - JWT now includes account context
   - Middleware reads from JWT first, falls back to headers

2. **Phase 2**: Update mobile app
   - Remove X-Active-Account headers
   - Implement JWT refresh on account switch
   - Test with both personal and business accounts

3. **Phase 3**: Remove deprecated code
   - Remove header fallback from middleware
   - Clean up any remaining header references

## Testing Checklist
- [ ] Login with personal account
- [ ] Switch to business account
- [ ] Verify correct account context in requests
- [ ] Test refresh token flow
- [ ] Verify business_id is included for business accounts
- [ ] Test multi-account scenarios

## Security Benefits
1. Account context cannot be manipulated by client
2. Single source of truth for authentication and authorization
3. Reduced attack surface (no custom headers)
4. Better audit trail (account context in JWT)