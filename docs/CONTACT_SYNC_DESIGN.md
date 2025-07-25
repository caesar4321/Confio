# Contact Sync and Transaction Display Design

## Overview
Following WhatsApp's privacy-first approach for contact handling and transaction display.

## Core Principles

### 1. Privacy First (WhatsApp Model)
- **Contacts remain local** - Never upload user's contact list to servers
- **Server stores minimal data** - Only phone numbers and user-chosen display names
- **Local enrichment** - App enhances display with local contact names

### 2. Transaction Immutability
- **Snapshot at transaction time** - Store display name, phone number, and business name
- **Historical accuracy** - Show who the transaction was with at that moment
- **No retroactive updates** - If someone changes their name, old transactions keep original name

## Data Model

### Transaction Records Should Include:
```python
class TransactionRecord:
    # User/Business links (for queries)
    sender_user_id: Optional[int]
    recipient_user_id: Optional[int]
    sender_business_id: Optional[int]
    recipient_business_id: Optional[int]
    
    # Immutable snapshot data
    sender_display_name: str  # Name at transaction time
    recipient_display_name: str  # Name at transaction time
    sender_phone: Optional[str]  # Phone at transaction time
    recipient_phone: Optional[str]  # Phone at transaction time
    sender_type: str  # 'personal' or 'business'
    recipient_type: str  # 'personal' or 'business'
```

### User Profile:
```python
class UserProfile:
    # User-controlled
    display_name: str  # What they want others to see
    phone_number: str  # Their current number
    
    # System
    user_id: int
    username: str  # Unique, unchangeable
```

## Display Logic

### In Transaction Lists:
1. **Check local contacts** first
   - If phone number matches a contact, show contact name
   - Add indicator: "Juan (from contacts)" or small icon

2. **Fallback to transaction snapshot**
   - Use stored display_name from transaction
   - Never show "Unknown"

3. **For businesses**
   - Always show business name, not owner name
   - Can still match against contacts for recognition

### Example Flow:
```javascript
function getTransactionDisplayName(transaction) {
  // For recipient
  if (transaction.recipient_phone) {
    const localContact = getLocalContact(transaction.recipient_phone);
    if (localContact) {
      return {
        primary: localContact.name,
        secondary: transaction.recipient_display_name,
        isFromContacts: true
      };
    }
  }
  
  // Fallback to stored name
  return {
    primary: transaction.recipient_display_name,
    secondary: null,
    isFromContacts: false
  };
}
```

## Implementation Steps

### 1. Backend Changes
- Ensure all transaction models have display_name and phone fields
- Always populate these fields at transaction creation
- Never leave display_name empty

### 2. Frontend Contact Handling
```javascript
// Contact service (runs locally)
class ContactService {
  async loadDeviceContacts() {
    // Request permission
    // Load contacts from device
    // Store in local database/memory
  }
  
  enrichTransactionDisplay(transaction) {
    // Match phone numbers
    // Return enhanced display info
  }
  
  // Never sync to server!
  syncToServer() {
    throw new Error("Contacts must remain local");
  }
}
```

### 3. Migration for Existing Data
- Backfill empty display_names with user names or business names
- Add phone numbers where available

## Privacy Benefits
1. **User control** - Users decide what name to show others
2. **Contact privacy** - Your contact names never leave your device
3. **No tracking** - Server doesn't know who knows whom by name
4. **GDPR friendly** - Minimal personal data storage

## UI Mockups

### Transaction List Item:
```
[Avatar] María García               -$50.00 cUSD
         Coffee Shop                    10:23 AM
         ✓ From your contacts
```

### When Not in Contacts:
```
[Avatar] Panadería El Sol          +$25.00 cUSD
         Business                       Yesterday
```

## Security Considerations
1. **Phone number changes** - Old transactions keep old number
2. **Contact spoofing** - Always show stored name as secondary
3. **Business verification** - Show verified badge for businesses