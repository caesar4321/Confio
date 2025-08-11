# Smart Contract Permissions Documentation

This document outlines all privileged functions and admin capabilities across Confío's smart contracts. This is essential for setting up proper multi-signature wallets and permission distribution.

## Overview

Each contract has specific capability objects that grant administrative powers. These should be carefully managed and potentially transferred to multi-sig wallets for production deployment.

## Quick Reference Table

| Contract | Capability | Critical Level | Key Powers | Recommended Multi-Sig |
|----------|------------|----------------|------------|------------------------|
| **cUSD** | `TreasuryCap<CUSD>` | 🔴 CRITICAL | Mint/burn tokens | 3-of-5 |
| **cUSD** | `AdminCap` | 🔴 CRITICAL | Freeze accounts, pause system | 2-of-3 |
| **CONFIO** | `TreasuryCap<CONFIO>` | 🟢 LOW | Already frozen | N/A |
| **Pay** | `AdminCap` | 🟡 MEDIUM | Withdraw fees, pause | 2-of-3 |
| **Invite Send** | `AdminCap` | 🟡 MEDIUM | Claim invitations | Hot wallet |
| **P2P Trade** | `AdminCap` | 🟡 MEDIUM | Resolve disputes | 2-of-3 |

---

## 1. cUSD Contract (`cusd.move`)

### Admin Capabilities

#### `TreasuryCap<CUSD>`
**Purpose**: Controls minting and burning of cUSD tokens  
**Critical Level**: 🔴 CRITICAL - Can create unlimited tokens

**Functions**:
- `mint(treasury_cap, pause_state, freeze_registry, amount, deposit_address, recipient)` - Mint new cUSD tokens
- `mint_and_transfer(treasury_cap, pause_state, freeze_registry, amount, deposit_address, recipient)` - Mint and transfer in one transaction
- `execute_burn(registry, treasury_cap, pause_state, freeze_registry, request, vault_address)` - Execute burn request

#### `AdminCap`
**Purpose**: System-wide administrative control  
**Critical Level**: 🔴 CRITICAL - Can freeze accounts and pause system

**Functions**:
- `pause(admin_cap)` - Pause all cUSD operations
- `unpause(admin_cap)` - Resume cUSD operations
- `freeze_address(admin_cap, freeze_registry, address)` - Block an address
- `unfreeze_address(admin_cap, freeze_registry, address)` - Unblock an address
- `add_vault(admin_cap, vault_registry, vault_address)` - Add reserve vault
- `remove_vault(admin_cap, vault_registry, vault_address)` - Remove reserve vault
- `update_metadata(admin_cap, metadata, name, symbol, description, icon_url)` - Update token info

### Shared Objects
- `Metadata<CUSD>` - Token metadata (read-only)
- `FreezeRegistry` - List of frozen addresses
- `VaultRegistry` - Authorized reserve vaults

### Permission Recommendations
1. Transfer `TreasuryCapHolder` to 3-of-5 multi-sig for minting
2. Transfer `AdminCap` to 2-of-3 multi-sig for emergency actions
3. Consider time-locks for pause/freeze operations

---

## 2. CONFIO Contract (`confio.move`)

### Admin Capabilities

#### `TreasuryCap<CONFIO>`
**Purpose**: Would control minting (but is frozen)  
**Critical Level**: 🟢 LOW - Already frozen, cannot mint

**Status**: The TreasuryCap is frozen in the init function, preventing any future minting. Fixed supply of 1 billion tokens.

### Shared Objects
- `CoinMetadata<CONFIO>` - Token metadata (read-only)

### Permission Recommendations
- No admin functions available after deployment
- Fully decentralized with fixed supply
- No multi-sig needed for this contract

---

## 3. Pay Contract (`pay.move`)

### Admin Capabilities

#### `AdminCap`
**Purpose**: Fee withdrawal and system control  
**Critical Level**: 🟡 MEDIUM - Controls collected fees

**Functions**:
- `withdraw_fees(admin_cap, fee_collector)` - Withdraw all collected fees (both cUSD and CONFIO)
- `update_fee_recipient(admin_cap, fee_collector, new_recipient)` - Change fee recipient address
- `pause(admin_cap, fee_collector)` - Pause payment system
- `unpause(admin_cap, fee_collector)` - Resume payments

### Shared Objects
- `FeeCollector` - Stores collected fees and system state

### Permission Recommendations
1. Transfer `AdminCap` to 2-of-3 multi-sig for fee management
2. Implement withdrawal limits or time-locks
3. Consider separate keys for pause vs withdrawal functions

---

## 4. Invite Send Contract (`invite_send.move`)

### Admin Capabilities

#### `AdminCap`
**Purpose**: Claim invitations and system control  
**Critical Level**: 🟡 MEDIUM - Can claim any invitation

**Functions**:
- `claim_invitation(admin_cap, registry, vault, invitation_id, recipient)` - Claim on behalf of user
- `pause(admin_cap, registry)` - Pause invitation system
- `unpause(admin_cap, registry)` - Resume invitation system

### Shared Objects
- `InvitationRegistry` - Tracks all invitations
- `InvitationVault` - Holds locked funds

### Permission Recommendations
1. Transfer `AdminCap` to Django service account (hot wallet)
2. Implement backend validation before claims
3. Consider rate limiting at application level
4. Monitor for unusual claim patterns

---

## 5. P2P Trade Contract (`p2p_trade.move`)

### Admin Capabilities

#### `AdminCap`
**Purpose**: Dispute resolution and system control  
**Critical Level**: 🟡 MEDIUM - Can resolve disputes

**Functions**:
- `resolve_dispute(admin_cap, registry, vault, trade_id, winner)` - Resolve trade disputes
- `pause(admin_cap, registry)` - Pause trading system
- `unpause(admin_cap, registry)` - Resume trading

### Shared Objects
- `TradeRegistry` - Tracks all trades and statistics
- `EscrowVault` - Holds funds during trades

### Permission Recommendations
1. Transfer `AdminCap` to dispute resolution committee multi-sig
2. Require 2-of-3 signatures for dispute resolution
3. Implement time delays for dispute resolution
4. Log all dispute resolutions for transparency

---

## Multi-Sig Setup Recommendations

### Critical Infrastructure (3-of-5 Multi-Sig)
- cUSD `TreasuryCapHolder` - For minting operations
- cUSD `AdminCap` - For emergency freezing

### Operational (2-of-3 Multi-Sig)
- Pay `AdminCap` - For fee withdrawal
- P2P Trade `AdminCap` - For dispute resolution

### Service Accounts (Single Sig with Monitoring)
- Invite Send `AdminCap` - For automated claims
- Gas sponsor wallet - For transaction sponsorship

### Time-Lock Recommendations
1. 24-hour delay for minting operations
2. 6-hour delay for freeze operations
3. 48-hour delay for fee withdrawals > $10,000
4. Immediate execution for pause operations (emergency)

---

## Security Best Practices

1. **Capability Storage**
   - Never store capabilities in regular wallets
   - Use hardware wallets or secure key management
   - Implement key rotation procedures

2. **Access Control**
   - Principle of least privilege
   - Separate operational from emergency functions
   - Regular access reviews

3. **Monitoring**
   - Set up alerts for all admin function calls
   - Track unusual patterns (e.g., multiple disputes)
   - Regular audit of capability holders

4. **Incident Response**
   - Pre-approved emergency pause procedures
   - Clear escalation paths
   - Regular drills for key scenarios

---

## Migration Checklist

When moving to production:

- [ ] Deploy contracts with temporary admin control
- [ ] Create multi-sig wallets with proper thresholds
- [ ] Transfer capabilities to multi-sig wallets
- [ ] Verify capability transfers succeeded
- [ ] Test each admin function with multi-sig
- [ ] Document key holders and procedures
- [ ] Set up monitoring and alerts
- [ ] Conduct security audit
- [ ] Create operational runbooks
- [ ] Train team on procedures