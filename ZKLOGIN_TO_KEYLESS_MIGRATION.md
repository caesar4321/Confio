# Migration Plan: Sui zkLogin to Aptos Keyless Account

## Overview

This document outlines the migration strategy from Sui's zkLogin to Aptos's Keyless Account system. Both systems use zero-knowledge proofs for Web2 authentication, but have different implementations.

## Current Status

### Sui zkLogin (Current Implementation)
- **SDK**: Python support via `pysui`
- **Providers**: Google, Apple, Twitch, Slack, Kakao
- **Key Features**: Salt-based privacy, epoch-based expiry
- **Production Ready**: Yes

### Aptos Keyless (Target Implementation)
- **SDK**: TypeScript only (Python pending)
- **Providers**: Google, Apple (more coming)
- **Key Features**: Pepper-based privacy, time-based expiry
- **Production Ready**: Yes (but no Python SDK)

## Key Differences

| Feature | zkLogin (Sui) | Keyless (Aptos) |
|---------|---------------|-----------------|
| Address Derivation | `hash(iss, sub, aud, salt)` | `hash(iss, sub, aud, pepper)` |
| Key Expiry | Epoch-based | Time-based (e.g., 24h) |
| Privacy Mechanism | User-controlled salt | App-scoped pepper |
| Python SDK | ✅ Available | ❌ Not yet available |
| ZK Proof Generation | Client-side with prover service | Client-side with SDK |

## Migration Strategy

### Phase 1: Proof of Concept ✅
1. **Install Aptos Python SDK** - ✅ Completed (`pip install aptos-sdk`)
2. **Understand Keyless implementation** - ✅ Completed
3. **Create test script** - ✅ Completed (`test_aptos_keyless.py`)
4. **Compare features** - ✅ Completed

### Phase 2: TypeScript Bridge (Recommended Next Step)
Since Aptos doesn't have Python Keyless support yet:

1. **Create TypeScript service** for Keyless operations:
   ```typescript
   // keyless-service.ts
   import { Aptos, AptosConfig, Network } from "@aptos-labs/ts-sdk";
   
   // Handle ephemeral key generation
   // Handle JWT verification
   // Handle account derivation
   // Expose REST API for Python backend
   ```

2. **Python wrapper** to call TypeScript service:
   ```python
   # aptos_keyless_client.py
   class AptosKeylessClient:
       def __init__(self, service_url: str):
           self.service_url = service_url
       
       async def derive_account(self, jwt: str, ephemeral_key: dict):
           # Call TypeScript service
           pass
   ```

### Phase 3: Database Migration
1. **User Account Mapping**:
   ```sql
   -- Add Aptos address column
   ALTER TABLE users ADD COLUMN aptos_address VARCHAR(66);
   
   -- Migration script to derive new addresses
   -- Note: Users will need to re-authenticate to get new addresses
   ```

2. **Authentication Flow Update**:
   - Keep zkLogin for Sui operations
   - Add Keyless for Aptos operations
   - Dual support during transition

### Phase 4: Frontend Updates
1. Update OAuth flow to support both systems
2. Add network selection (Sui vs Aptos)
3. Update wallet UI components

### Phase 5: Backend Services
1. Update GraphQL schema for Aptos support
2. Add Aptos transaction handlers
3. Update balance checking logic

## Implementation Checklist

- [ ] Set up TypeScript Keyless service
- [ ] Create Python client wrapper
- [ ] Update database schema
- [ ] Modify authentication service
- [ ] Update frontend OAuth flow
- [ ] Add Aptos transaction support
- [ ] Update GraphQL API
- [ ] Test end-to-end flow
- [ ] Plan user migration strategy

## Risks & Mitigation

1. **No Python SDK**: Use TypeScript bridge until official support
2. **Different address format**: Clear UX communication needed
3. **User migration**: Support both networks during transition
4. **Provider differences**: Start with common providers (Google, Apple)

## Recommendation

Given the lack of Python SDK support for Keyless, I recommend:

1. **Short term**: Keep zkLogin for authentication, focus on migrating other Sui components to Aptos
2. **Medium term**: Implement TypeScript bridge for Keyless
3. **Long term**: Switch to native Python SDK when available

The test script (`test_aptos_keyless.py`) demonstrates the concepts, but full implementation requires either:
- Waiting for official Python Keyless support
- Building a TypeScript service bridge
- Using the Aptos TypeScript SDK directly