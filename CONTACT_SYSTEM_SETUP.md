# Contact System Setup Guide

## Overview
We've implemented a privacy-focused contact management system for Confío that:
- Stores contacts locally on the device (never sent to servers)
- Shows user's contact names instead of phone numbers in transactions
- Provides a beautiful permission request screen explaining the benefits
- Syncs contacts once per day automatically

## Required Dependencies

### 1. Install NPM Packages
```bash
cd apps
npm install react-native-contacts libphonenumber-js
```

### 2. iOS Setup (if building for iOS)
```bash
cd ios
pod install
```

Add to your `Info.plist`:
```xml
<key>NSContactsUsageDescription</key>
<string>Confío needs access to your contacts to show familiar names in your transactions. Your contacts are stored locally and never sent to our servers.</string>
```

### 3. Android Setup
The permissions are already handled in the code, but ensure your `android/app/src/main/AndroidManifest.xml` includes:
```xml
<uses-permission android:name="android.permission.READ_CONTACTS" />
```

## Implementation Details

### New Files Created:

1. **`apps/src/services/contactService.ts`**
   - Core service for contact management
   - Handles permission requests
   - Syncs and stores contacts in Keychain
   - Phone number normalization and matching

2. **`apps/src/components/ContactPermissionModal.tsx`**
   - Beautiful permission explanation modal
   - Shows benefits and privacy information
   - Step-by-step explanation of how it works

3. **`apps/src/hooks/useContactName.ts`**
   - React hook for getting contact names
   - Caches results for performance
   - Falls back to original name if no contact found

### Modified Files:

1. **`apps/src/screens/ContactsScreen.tsx`**
   - Added contact permission flow
   - Pull-to-refresh to sync contacts
   - Loading states and permission handling

2. **`apps/src/screens/AccountDetailScreen.tsx`**
   - Updated Transaction interface to include phone numbers
   - Enhanced TransactionItem to show contact names
   - Shows original name in italic if contact name is used

## How It Works

1. **First Launch**: When user opens Contacts screen, they see a permission modal explaining the benefits
2. **Permission Grant**: If granted, contacts are synced and stored encrypted in Keychain
3. **Transaction Display**: When showing transactions, the system looks up phone numbers in local contacts
4. **Privacy**: All processing happens on-device, no contact data is sent to servers
5. **Updates**: Contacts sync automatically once per day or on pull-to-refresh

## API Integration Needed

The frontend is ready, but you'll need to ensure the GraphQL API returns phone numbers in the transaction data:

```graphql
# Ensure these fields are populated in UnifiedTransaction:
senderPhone
counterpartyPhone
```

## Testing

1. Install dependencies and rebuild the app
2. Open the Contacts screen
3. Allow contact permissions when prompted
4. Create a transaction with someone in your contacts
5. Check the transaction history - it should show contact names

## Privacy & Security

- Contacts are stored using React Native Keychain (encrypted)
- No contact data leaves the device
- Users can deny permission and the app works normally (shows phone numbers)
- Permission status is stored to avoid repeated prompts

## Future Enhancements

1. Add contact avatar support
2. Allow users to manually link contacts to Confío users
3. Show "Invite to Confío" option for non-users
4. Add contact search in send screens