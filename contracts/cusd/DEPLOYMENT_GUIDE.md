# cUSD Deployment Guide

Complete step-by-step guide for deploying Confío Dollar (cUSD) on Algorand.

## Quick Deploy (recommended)

Use the Make target for a strict, verified deployment:

```bash
export ALGORAND_NETWORK=testnet
export ALGORAND_ALGOD_ADDRESS=https://testnet-api.algonode.cloud
export ALGORAND_ALGOD_TOKEN=""  # empty ok for Algonode
export ALGORAND_SPONSOR_MNEMONIC="your 25 words..."
export ALGORAND_SPONSOR_ADDRESS=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ

make deploy-cusd
```

This does:
- Deploys the app and creates the cUSD ASA
- Calls `setup_assets` and sets `sponsor_address`
- Verifies global-state asset IDs, sponsor, and app opt-ins

## Prerequisites

### 1. Environment Setup
```bash
# Install Python dependencies
pip install pyteal py-algorand-sdk beaker-pyteal

# Clone the repository
git clone [repository-url]
cd contracts/cusd
```

### 2. Account Setup

#### Option A: Create New Account
```bash
# The deployment script will create a new account
# Save the mnemonic securely when displayed
python deploy_cusd.py
```

#### Option B: Use Existing Account
```bash
# Set your sponsor mnemonic as environment variable
export ALGORAND_SPONSOR_MNEMONIC="your twenty five word mnemonic phrase here..."
python deploy_cusd.py
```

### 3. Fund Account
- **Testnet**: Get free ALGO from [Algorand Testnet Dispenser](https://bank.testnet.algorand.network/)
- **Required**: At least 2 ALGO for deployment and transactions

## Deployment Process

### Step 1: Compile Contract
```bash
# Generate TEAL files and ABI
python cusd.py
```

This creates:
- `cusd_approval.teal` - Approval program
- `cusd_clear.teal` - Clear state program  
- `cusd.json` - ABI specification

### Step 2: Deploy to Testnet
```bash
# Run automated deployment
python deploy_cusd.py
```

The script automatically:
1. Deploys the smart contract
2. Creates cUSD ASA with proper authorities
3. Configures assets in the contract
4. Saves deployment info

### Step 3: Verify Deployment
```bash
# Check deployment info
cat deployment_info.json
```

Expected output:
```json
{
  "network": "testnet",
  "deployer_address": "...",
  "app_id": 123456,
  "app_address": "...",
  "cusd_asset_id": 789012,
  "usdc_asset_id": 10458941,
  "deployment_status": "Complete - Contract deployed and configured"
}
```

## Manual Deployment Steps

If you prefer manual deployment or need custom configuration:

### 1. Deploy Contract
```python
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, StateSchema

# Initialize client
algod_client = algod.AlgodClient("", "https://testnet-api.algonode.cloud")

# Compile TEAL programs
with open("cusd_approval.teal", "r") as f:
    approval_program = compile_program(algod_client, f.read())
    
with open("cusd_clear.teal", "r") as f:
    clear_program = compile_program(algod_client, f.read())

# Define state schemas
global_schema = StateSchema(num_uints=9, num_byte_slices=2)
local_schema = StateSchema(num_uints=2, num_byte_slices=0)

# Create application
txn = ApplicationCreateTxn(
    sender=address,
    sp=params,
    on_complete=OnComplete.NoOpOC,
    approval_program=approval_program,
    clear_program=clear_program,
    global_schema=global_schema,
    local_schema=local_schema
)
```

### 2. Create cUSD Asset
```python
from algosdk.transaction import AssetConfigTxn

# Create ASA with app as authorities
txn = AssetConfigTxn(
    sender=creator_address,
    sp=params,
    total=10_000_000_000_000,  # 10 million cUSD
    default_frozen=False,
    unit_name="cUSD",
    asset_name="Confío Dollar",
    manager=creator_address,     # Asset manager
    reserve=creator_address,     # Reserve address
    freeze=app_address,          # App controls freezing
    clawback=app_address,        # App controls clawback
    url="https://confio.lat",
    decimals=6
)
```

### 3. Configure Contract
```python
# Call setup_assets to configure the contract
from algosdk.atomic_transaction_composer import AtomicTransactionComposer

atc = AtomicTransactionComposer()

# Add payment for opt-ins
payment_txn = PaymentTxn(
    sender=admin_address,
    receiver=app_address,
    amt=600000  # 0.6 ALGO
)

# Add setup_assets call (with flat fee for inner transactions)
method_params = algod_client.suggested_params()
method_params.flat_fee = True
method_params.fee = 3000  # 3x min fee for 2 inner opt-in transactions

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("setup_assets"),
    sender=admin_address,
    sp=method_params,
    signer=signer,
    method_args=[cusd_asset_id, usdc_asset_id]
)

result = atc.execute(algod_client, 4)
```

## Post-Deployment Operations

### Test Minting Functions

#### 1. Admin Mint (T-bills backed)
```python
# Mint cUSD backed by treasury bills
# Set flat fee for deterministic fee handling
params = algod_client.suggested_params()
params.flat_fee = True
params.fee = 2000  # 2x min fee for 1 inner transaction

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("mint_admin"),
    sender=admin_address,
    sp=params,
    signer=signer,
    method_args=[amount, recipient_address]
)
```

#### 2. Admin Burn (T-bills reduction)
```python
# Burn cUSD to reduce T-bills backed supply
# Requires atomic group with cUSD transfer

from algosdk.transaction import AssetTransferTxn
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner

# Transaction 1: Send cUSD to app (normal fee)
params = algod_client.suggested_params()
cusd_transfer = AssetTransferTxn(
    sender=admin_address,
    sp=params,
    receiver=app_address,
    amt=burn_amount,
    index=cusd_asset_id
)

# Transaction 2: Call burn_admin (flat fee)
method_params = algod_client.suggested_params()
method_params.flat_fee = True
method_params.fee = 2000  # 2x min fee for 1 inner transaction

atc = AtomicTransactionComposer()
atc.add_transaction(TransactionWithSigner(cusd_transfer, signer))
atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("burn_admin"),
    sender=admin_address,
    sp=method_params,
    signer=signer
)
```

#### 3. Collateral Mint (USDC backed)
```python
# User deposits USDC to mint cUSD
# Requires atomic group with USDC transfer

from algosdk.transaction import AssetTransferTxn
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner

# Transaction 1: Send USDC to app (normal fee)
params = algod_client.suggested_params()
usdc_transfer = AssetTransferTxn(
    sender=user_address,
    sp=params,
    receiver=app_address,
    amt=usdc_amount,
    index=usdc_asset_id
)

# Transaction 2: Call mint_with_collateral (flat fee)
method_params = algod_client.suggested_params()
method_params.flat_fee = True
method_params.fee = 2000  # 2x min fee for 1 inner transaction

atc = AtomicTransactionComposer()
atc.add_transaction(TransactionWithSigner(usdc_transfer, signer))
atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("mint_with_collateral"),
    sender=user_address,
    sp=method_params,
    signer=signer
)
```

#### 3. Burn for Collateral (USDC redemption)
```python
# User burns cUSD to redeem USDC
# Requires atomic group with cUSD transfer

from algosdk.transaction import AssetTransferTxn
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner

# Transaction 1: Send cUSD to app (normal fee)
params = algod_client.suggested_params()
cusd_transfer = AssetTransferTxn(
    sender=user_address,
    sp=params,
    receiver=app_address,
    amt=cusd_amount,
    index=cusd_asset_id
)

# Transaction 2: Call burn_for_collateral (flat fee)
method_params = algod_client.suggested_params()
method_params.flat_fee = True
method_params.fee = 3000  # 3x min fee for 2 inner transactions

atc = AtomicTransactionComposer()
atc.add_transaction(TransactionWithSigner(cusd_transfer, signer))
atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("burn_for_collateral"),
    sender=user_address,
    sp=method_params,
    signer=signer
)
```

#### 4. Treasury Rebalancing (USDC to mTBILL)
```python
# Withdraw USDC for mTBILL purchase while system remains operational
# Users can continue minting/burning cUSD during rebalancing

params = algod_client.suggested_params()
params.flat_fee = True
params.fee = 2000  # 2x min fee for 1 inner transaction

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("withdraw_usdc"),
    sender=admin_address,
    sp=params,
    signer=signer,
    method_args=[usdc_amount, treasury_wallet]
)

# System continues operating normally - no downtime
# The withdrawal maintains proper backing ratios automatically
```

#### 5. Freeze/Unfreeze Operations
```python
# Freeze an address (admin only)
params = algod_client.suggested_params()
params.flat_fee = True
params.fee = 2000  # 2x min fee for 1 inner transaction

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("freeze_address"),
    sender=admin_address,
    sp=params,
    signer=signer,
    method_args=[target_address]
)

# Unfreeze an address (admin only)
unfreeze_params = algod_client.suggested_params()
unfreeze_params.flat_fee = True
unfreeze_params.fee = 2000  # 2x min fee for 1 inner transaction

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("unfreeze_address"),
    sender=admin_address,
    sp=unfreeze_params,
    signer=signer,
    method_args=[target_address]
)
```

### Verify Contract State
```python
# Check reserves and backing (read-only, normal fee)
params = algod_client.suggested_params()

atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("get_reserves"),
    sender=any_address,
    sp=params
)

# Verify backing status
atc.add_method_call(
    app_id=app_id,
    method=contract.get_method_by_name("verify_backing"),
    sender=any_address,
    sp=params
)
```

## Network Configurations

### Testnet
```python
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
USDC_ASSET_ID = 10458941
INDEXER_ADDRESS = "https://testnet-idx.algonode.cloud"
```

### Mainnet
```python
ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
USDC_ASSET_ID = 31566704
INDEXER_ADDRESS = "https://mainnet-idx.algonode.cloud"
```

### LocalNet (Development)
```python
ALGOD_ADDRESS = "http://localhost:4001"
ALGOD_TOKEN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
# Create test USDC asset locally
```

## Security Checklist

Before mainnet deployment:

- [ ] Audit smart contract code
- [ ] Test all functions on testnet
- [ ] Verify ASA authorities are correctly set
- [ ] Confirm reserve address holds initial supply
- [ ] Test freeze/unfreeze functionality
- [ ] Verify collateral ratio calculations
- [ ] Test pause/unpause mechanisms
- [ ] Confirm admin transfer works correctly
- [ ] Validate all underflow protections
- [ ] Test atomic transaction groups
- [ ] **Post-setup**: Rotate ASA manager to multisig or zero address to lock configuration

## Troubleshooting

### Common Issues

#### "Insufficient balance"
- Ensure account has at least 2 ALGO
- Check for minimum balance requirements

#### "Asset not found"
- Verify USDC asset ID for your network
- Ensure assets are created before setup_assets

#### "Transaction group failed"
- Check atomic transaction ordering
- Verify all transactions are properly signed
- Ensure fees cover all inner transactions

#### "Compilation failed"
- Update beaker-pyteal to latest version
- Check Python version (3.8+ required)

## Monitoring

### Track Contract Activity
```python
# Use indexer to query transactions
from algosdk.v2client import indexer

indexer_client = indexer.IndexerClient(
    "",
    "https://testnet-idx.algonode.cloud"
)

# Get application transactions
txns = indexer_client.search_transactions_by_application(app_id)
```

### Monitor Reserves
```python
# Regular backing verification
def check_backing_status():
    # Get reserve information
    reserves = contract.get_reserves()
    usdc_locked = reserves[0]
    cusd_collateral_supply = reserves[1]
    tbills_supply = reserves[2]
    ratio = reserves[3]
    total_supply = reserves[4]
    
    # Check if properly backed
    backed, actual_usdc = contract.verify_backing()
    
    print(f"USDC Locked (tracked): {usdc_locked}")
    print(f"USDC on-chain (actual): {actual_usdc}")
    print(f"cUSD Collateral Supply: {cusd_collateral_supply}")
    print(f"T-bills Backed Supply: {tbills_supply}")
    print(f"Total Supply: {total_supply}")
    print(f"Collateral Ratio: {ratio / 1e6:.2%}")
    print(f"Fully Backed: {backed}")
```

## Support

For deployment assistance or issues:
- Website: [confio.lat](https://confio.lat)
- Documentation: See README.md for contract details
