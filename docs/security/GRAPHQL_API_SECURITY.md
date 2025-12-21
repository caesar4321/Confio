# GraphQL API Security Guidelines

## 1. Overview
This document outlines the security measures implemented in the Confío Django Graphene API to protect Personally Identifiable Information (PII) and prevent data harvesting/enumeration attacks.

## 2. Core Principles
1.  **Zero Unauthorized PII**: Sensitive fields (Phone, Email, Identity data) must never be returned to unauthorized users.
2.  **No Enumeration**: Public APIs (verification, lookup) must not allow sequential ID guessing.
3.  **Context-Based Access**: Access to objects (Invoices, Transactions) does not imply access to all nested data (e.g., Payer's detailed profile).

## 3. Implementation Details

### 3.1. Field-Level Security (`UserType`)
The `UserType` (in `users/schema.py`) is the most critical object.
-   **Vulnerability**: Default DjangoObjectType behavior exposes all model fields.
-   **Protection**:
    -   `phone_number` and `email` are implemented as **Computed Fields** with custom resolvers.
    -   **Rule**: These resolvers check `info.context.user`.
        -   If `user.id == self.id`: Return data.
        -   Otherwise: Return `None`.

```python
def resolve_phone_number(self, info):
    user = info.context.user
    if user.is_authenticated and user.id == self.id:
        return self.phone_number
    return None
```

### 3.2. Relationship Security (`InvoiceType`)
Invoices are often public (via Link/QR).
-   **Vulnerability**: An invoice might contain a list of `payment_transactions`. If these transactions contain the `payer_user` (and their phone number), a public invoice viewer could harvest payer data.
-   **Protection**: `InvoiceType.resolve_payment_transactions` enforces strict filtering:
    -   **Merchant (Owner/Employee)**: Sees ALL transactions.
    -   **Payer**: Sees ONLY their own transaction.
    -   **Public**: Sees NO transactions.

### 3.3. Anti-Enumeration (`verifyTransaction`)
The `verifyTransaction` query allows looking up transaction status.
-   **Vulnerability**: Allowing lookup by **Integer ID** (Primary Key) enables attackers to iterate (1, 2, 3...) and harvest partial data (First Name, Amounts).
-   **Protection**: Integer ID lookup is **DISABLED**.
-   **Requirement**: Clients must use the `internal_id` (32-char Hex UUID) or the unique `transaction_hash` (where applicable/safe). UUIDs are non-enumerable.

### 3.4. Transaction Masking
-   Direct transaction fields (`sender_phone`, `recipient_phone` on `SendTransaction`) are an **intentional security design**. By determining these values at transaction time and storing them directly, clients can display necessary transaction details without needing to query the full nested `User` object (which minimizes potential exposure surface). These fields are only accessible via Queries that enforce ownership.
-   Masked fields (`phone_number_masked`) were removed from schema to reduce bloat, as client-side logic handles display masking.

### 3.5. Secured Nested Contexts
-   **Notifications**: `NotificationType` links to related objects (e.g., `PaymentTransaction`). Access logic ensures that since the Notification itself is private to the user, valid related objects are safe to expose (Contextual Authority).
-   **P2P Trades**: `P2PTradeType` resolvers explicitly check that `info.context.user` is either the buyer, seller, or an admin before returning trade details or chat messages.

## 4. Checklist for New Schema Additions
- [ ] **PII Check**: Does the new Type expose User, Phone, Email, or Address?
- [ ] **Nested Access**: Can a public object (like an Invoice or Post) lead to a User object?
- [ ] **Enumeration**: Does a public Query accept an Integer ID? (Use UUIDs instead).
- [ ] **Authorization**: Do resolvers explicitly check `info.context.user`?
