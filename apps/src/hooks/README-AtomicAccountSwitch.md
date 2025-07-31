# Atomic Account Switching

## Problem

The app was experiencing partial account switches where different parts of the app would be in different account states:
- Profile and balance showing Business account, but acting like Personal account
- Offers created by Business account requiring Personal account permissions
- JWT token, Sui address, and zkLogin private values getting out of sync

## Solution

The `useAtomicAccountSwitch` hook ensures all account-related state is synchronized atomically:

1. **Validates** the target account exists
2. **Pauses** all Apollo queries to prevent race conditions
3. **Clears** Apollo cache to prevent stale data
4. **Updates** account context in Keychain
5. **Obtains** new JWT token with updated context
6. **Refreshes** profile data
7. **Refreshes** accounts list
8. **Resumes** Apollo queries
9. **Validates** everything is in sync

## Usage

```typescript
import { useAtomicAccountSwitch } from '../hooks/useAtomicAccountSwitch';
import { AccountSwitchOverlay } from '../components/AccountSwitchOverlay';

function MyComponent() {
  const { 
    switchAccount, 
    state, 
    isAccountSwitchInProgress 
  } = useAtomicAccountSwitch();
  
  const handleAccountSwitch = async (accountId: string) => {
    const success = await switchAccount(accountId);
    if (success) {
      // Account switched successfully
    }
  };
  
  return (
    <>
      {/* Your UI */}
      
      {/* Always include the overlay to block UI during switch */}
      <AccountSwitchOverlay
        visible={state.isLoading}
        progress={state.progress}
      />
    </>
  );
}
```

## Important Notes

1. **Always use `useAtomicAccountSwitch`** instead of the raw `switchAccount` from `useAccount`
2. **Always include `AccountSwitchOverlay`** in your component to block UI during switch
3. **Never bypass the atomic switch** - it ensures data consistency
4. **Account context comes from JWT** - never pass accountId to mutations

## What Gets Synchronized

- Keychain account context
- JWT authentication token
- Apollo cache (cleared and refetched)
- Profile data (personal or business)
- Active queries
- UI state

## Error Handling

The hook handles errors gracefully:
- Shows user-friendly error messages
- Attempts to recover by resuming queries
- Prevents concurrent account switches
- Validates final state matches expected state