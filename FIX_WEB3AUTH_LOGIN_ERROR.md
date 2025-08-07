# Fix: Web3Auth Login "Invalid Payload" Error

## Problem
The `WEB3AUTH_LOGIN` mutation was failing with "Invalid payload" error because:
1. The Apollo client was automatically adding JWT tokens from a previous session
2. The server-side mutation expected to be called without authentication (it's a login mutation)
3. The server was rejecting the request because it received an authenticated request for a login endpoint

## Root Cause
```javascript
// The client was sending:
Authorization: Bearer <old_jwt_token>

// But the server expected:
No Authorization header (this IS the login)
```

## Solution

### 1. Added `skipAuth` Context to Apollo Client (`apps/src/apollo/client.ts`)
```javascript
const authLink = setContext(async (operation, { headers }) => {
  // Check if we should skip authentication
  const context = operation.getContext();
  if (context.skipAuth) {
    console.log('Skipping authentication for operation:', operation.operationName);
    return { headers };
  }
  // ... rest of auth logic
});
```

### 2. Use `skipAuth` for Login Mutations (`apps/src/services/authService.ts`)
```javascript
const { data: authData } = await apolloClient.mutate({
  mutation: WEB3AUTH_LOGIN,
  variables: { /* ... */ },
  context: {
    skipAuth: true, // Tell auth link to skip adding JWT token
  },
});
```

### 3. Store New Tokens After Successful Login
```javascript
if (authData?.web3AuthLogin?.success) {
  // Store the NEW tokens from login
  if (authData.web3AuthLogin.accessToken && authData.web3AuthLogin.refreshToken) {
    await this.storeTokens({
      accessToken: authData.web3AuthLogin.accessToken,
      refreshToken: authData.web3AuthLogin.refreshToken,
    });
  }
  
  // Now subsequent mutations will use the new tokens
  const { data: walletData } = await apolloClient.mutate({
    mutation: ADD_ALGORAND_WALLET,
    // ... this will now use the new tokens
  });
}
```

## Applied To
- `authService.ts` - WEB3AUTH_LOGIN mutation
- `authServiceWeb3.ts` - WEB3AUTH_LOGIN mutation
- Any other login/signup mutations that don't require authentication

## Testing
1. Clear app data/cache to remove old tokens
2. Sign in with Google/Apple
3. Check console logs - should see:
   - "Skipping authentication for operation: Web3AuthLogin"
   - "WEB3AUTH_LOGIN successful"
   - "Stored new authentication tokens"
4. Verify no "Invalid payload" errors

## Prevention
For any new login/signup mutations:
```javascript
// Always add skipAuth context
await apolloClient.mutate({
  mutation: LOGIN_OR_SIGNUP_MUTATION,
  context: { skipAuth: true },
  variables: { /* ... */ }
});
```

## Related Files
- `/apps/src/apollo/client.ts` - Auth link configuration
- `/apps/src/services/authService.ts` - Main auth service
- `/apps/src/services/authServiceWeb3.ts` - Web3Auth service
- `/users/web3auth_schema.py` - Server-side mutation