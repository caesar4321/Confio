# Chain Decision Note

## Current Setup (Temporary)

**We are temporarily using the `aptos_address` field to store Algorand addresses** until a final decision is made on which blockchain to use.

### Why This Approach?
- Avoids database migrations for a temporary state
- Keeps the codebase simpler
- Easy to switch to either chain before launch

### Fields Being Reused:
- `Account.aptos_address` → Stores Algorand address (58 chars)
- `Account.web3auth_id` → Stores Web3Auth user ID
- `Account.web3auth_provider` → Stores provider (google/apple)

### Before Launch TODO:
1. **Decide on final blockchain**: Aptos OR Algorand
2. **If staying with Algorand**:
   - Rename field: `aptos_address` → `blockchain_address` or `wallet_address`
   - Update all references
   - Remove Aptos-specific code
3. **If switching back to Aptos**:
   - Remove Algorand integration
   - Restore Aptos keyless implementation
   - Clear any test Algorand addresses

### Current Integration Points:
- **Backend**: `users/web3auth_schema.py` - Using `aptos_address` for Algorand
- **Frontend**: `services/algorandExtension.ts` - Reads from `aptosAddress` field
- **GraphQL**: Queries already use `aptosAddress` field

### Testing:
Both Aptos (66 chars) and Algorand (58 chars) addresses fit in the same CharField(max_length=66).

### Migration Command (When Decision Made):
```python
# If staying with Algorand, rename the field:
python manage.py makemigrations --name rename_aptos_to_wallet_address
# Then update the migration to rename the field
```

## Remember:
This is a **temporary solution** to avoid unnecessary complexity while evaluating blockchains. The final implementation will use properly named fields.