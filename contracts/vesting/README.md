# Confio Vesting Contract

Smart contract for locking and vesting CONFIO tokens.

## Features
- **Admin Managed**: Only admin can fund the vault and start the vesting timer.
- **Linear Vesting**: Tokens vest linearly over a configurable period (e.g. 24 or 36 months).
- **Revocable/Transferable**: Admin can change the beneficiary address.
- **Claiming**: Beneficiary can claim vested tokens at any time.

## Deployment

1. Set environment variables:
   - `DEPLOYER_MNEMONIC`: Mnemonic of the deployer (admin).
   - `CONFIO_ASSET_ID`: Asset ID of CONFIO token.
   - `BENEFICIARY_ADDRESS`: Address of the initial beneficiary.
   - `VESTING_DURATION`: Duration in seconds (e.g., `63072000` for 2 years).
2. Run deployment script:
   ```bash
   python3 contracts/vesting/deploy_vesting.py
   ```

## Contract Methods

### Admin Actions
- **fund**: Deposit tokens into the contract and lock them.
    - Args: `['fund']`
    - Group: `[AssetTransfer(Admin->App), AppCall]`
- **start**: Start the vesting timer.
    - Args: `['start']`
- **change_beneficiary**: Update the beneficiary address.
    - Args: `['change_beneficiary', <new_address_bytes>]`
- **update_admin**: Update the admin address.
    - Args: `['update_admin', <new_address_bytes>]`
- **opt_in_asset**: Opt the contract into the CONFIO asset (required before funding).
    - Args: `['opt_in_asset']`
- **withdraw_before_start**: Withdraw all tokens if vesting hasn't started yet.
    - Args: `['withdraw_before_start']`
    - Logic: Can only be called if `start_time == 0`. Sends `total_locked` back to admin.

### Beneficiary Actions
- **claim**: Claim vested tokens.
    - Args: `['claim']`
    - Logic: Transfers `(Total * Elapsed / Duration) - AlreadyClaimed` to beneficiary.

## Global State
- `admin`: Manager address.
- `beneficiary`: Recipient address.
- `confio_id`: Asset ID.
- `start_time`: Timestamp of start (0 if inactive).
- `duration`: Vesting duration in seconds.
- `total_locked`: Total initialized/funded amount.
- `total_claimed`: Total amount withdrawn.
