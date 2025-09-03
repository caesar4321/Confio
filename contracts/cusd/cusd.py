"""
Confío Dollar (cUSD) - Smart Contract for Managing an Algorand ASA

⚠️ IMPORTANT: This contract does NOT define the cUSD token parameters!
- Token parameters (supply, decimals, etc.) are defined in deploy_cusd.py
- This contract only controls the BEHAVIOR of an ASA
- The deployment order is: Contract first → ASA creation → setup_assets

What this contract does:
- Controls minting from reserve (via clawback)
- Enforces collateral requirements
- Manages pause/freeze functionality
- Tracks backing (USDC + T-bills)

What this contract does NOT do:
- Define token supply (that's in AssetConfigTxn)
- Create the token (that's done in deploy_cusd.py)
- Set decimals or name (that's in AssetConfigTxn)

Website: confio.lat
"""

from pyteal import *
from beaker import *
from typing import Final

# Note: USDC asset ID is now stored in global state via setup_assets
# No compile-time configuration needed

class CUSDState:
    """Global and local state for Confío Dollar management"""
    
    # Global state
    admin: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Admin address"
    )
    
    is_paused: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="System pause state (0=active, 1=paused)"
    )
    
    # ASA ID for Confío Dollar token
    cusd_asset_id: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Asset ID of Confío Dollar token"
    )
    
    # USDC asset ID for collateral
    usdc_asset_id: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="USDC asset ID (e.g., 31566704 on mainnet)"
    )
    
    # Collateral ratio (1e6 = 1:1)
    collateral_ratio: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(1000000),  # 1:1 ratio for user minting/burning
        descr="Collateral ratio (1e6 = 100%)"
    )
    
    # Statistics
    total_minted: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar minted"
    )
    
    total_burned: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total Confío Dollar burned"
    )
    
    # Collateral statistics
    total_usdc_locked: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total USDC locked as collateral"
    )
    
    cusd_circulating_supply: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Current circulating supply of collateral-backed cUSD"
    )
    
    # T-bills backed supply (admin minted)
    tbills_backed_supply: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="cUSD supply backed by T-bills/reserves (admin minted)"
    )
    
    # Reserve address (separate from admin)
    reserve_address: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="ASA reserve address for minting/burning"
    )
    
    # Sponsor address for fee sponsorship
    sponsor_address: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Sponsor address allowed to send app calls on behalf of users"
    )
    
    # Local state for accounts
    is_frozen: Final[LocalStateValue] = LocalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Account freeze status (0=active, 1=frozen)"
    )
    
    is_vault: Final[LocalStateValue] = LocalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Vault status (0=not vault, 1=is vault)"
    )

app = Application("ConfioDollar", state=CUSDState())

@app.create
def create():
    """Initialize the Confío Dollar contract"""
    return Seq(
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.admin.set(Txn.sender()),
        app.state.is_paused.set(Int(0)),
        app.state.collateral_ratio.set(Int(1000000)),  # 1:1 ratio for user operations
        Approve()
    )

@app.external
def set_sponsor_address(sponsor: abi.Address):
    """
    Set the sponsor address that can send app calls on behalf of users
    Admin only
    """
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        # Input validation for address
        Assert(Len(sponsor.get()) == Int(32)),
        Assert(sponsor.get() != Global.zero_address()),
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Set sponsor address
        app.state.sponsor_address.set(sponsor.get()),
        
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, usdc_id: abi.Uint64):
    """
    Setup asset IDs and opt-in to both assets with proper funding
    Must be called as part of atomic group with payment to app for fees/min balance
    
    Group structure:
    - Tx 0: Payment to app (at least 0.6 ALGO for opt-ins and fees)
    - Tx 1: This app call
    """
    # Funding buffer: 0.2 ALGO min balance (0.1 per ASA * 2) + 0.4 ALGO headroom for fees
    min_fund = Int(600000)  # 0.6 ALGO total
    
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.cusd_asset_id == Int(0)),  # Can only be set once
        Assert(app.state.usdc_asset_id == Int(0)),  # Both assets set-once
        
        # Verify atomic group with funding
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        Assert(Gtxn[0].amount() >= min_fund),
        Assert(Gtxn[0].rekey_to() == Global.zero_address()),
        Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
        
        # App call must fund 2 inner ASA opt-ins (app call + 2 inner)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(3)),
        
        # Guard distinct assets
        Assert(cusd_id.get() != usdc_id.get()),
        
        # Store asset IDs
        app.state.cusd_asset_id.set(cusd_id.get()),
        app.state.usdc_asset_id.set(usdc_id.get()),
        
        # Validate cUSD ASA parameters
        (claw := AssetParam.clawback(cusd_id.get())),
        Assert(claw.hasValue()),
        Assert(claw.value() == Global.current_application_address()),
        
        (freeze := AssetParam.freeze(cusd_id.get())),
        Assert(freeze.hasValue()),
        Assert(freeze.value() == Global.current_application_address()),
        # Manager will be locked to zero post-deploy; no assert here to allow setup flow
        
        # Validate cUSD decimals
        (cusd_decimals := AssetParam.decimals(cusd_id.get())),
        Assert(cusd_decimals.hasValue()),
        Assert(cusd_decimals.value() == Int(6)),
        
        # Get and store reserve address
        (reserve := AssetParam.reserve(cusd_id.get())),
        Assert(reserve.hasValue()),
        app.state.reserve_address.set(reserve.value()),
        
        # Validate USDC decimals
        (usdc_decimals := AssetParam.decimals(usdc_id.get())),
        Assert(usdc_decimals.hasValue()),
        Assert(usdc_decimals.value() == Int(6)),
        
        # Opt-in to USDC with fee=0 (outer txn pays)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: usdc_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Opt-in to cUSD with fee=0 (outer txn pays)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: cusd_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Log configuration for indexers
        Log(Concat(Bytes("assets_set:"), Itob(cusd_id.get()), Bytes(":"), Itob(usdc_id.get()))),
        
        Approve()
    )

@app.external
def pause():
    """Pause all operations"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.is_paused.set(Int(1)),
        Log(Bytes("paused")),
        Approve()
    )

@app.external
def unpause():
    """Unpause operations"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(1)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.is_paused.set(Int(0)),
        Log(Bytes("unpaused")),
        Approve()
    )

@app.opt_in
def opt_in():
    """Allow accounts to opt-in"""
    return Seq(
        Assert(Txn.rekey_to() == Global.zero_address()),
        app.state.is_frozen[Txn.sender()].set(Int(0)),
        app.state.is_vault[Txn.sender()].set(Int(0)),
        Approve()
    )

@app.external
def add_vault(vault_address: abi.Address):
    """Add a vault address"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        # Ensure vault has opted into the app
        Assert(App.optedIn(vault_address.get(), Global.current_application_id())),
        app.state.is_vault[vault_address.get()].set(Int(1)),
        Log(Concat(Bytes("vault_added:"), vault_address.get())),
        Approve()
    )

@app.external
def remove_vault(vault_address: abi.Address):
    """Remove a vault address"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        app.state.is_vault[vault_address.get()].set(Int(0)),
        Log(Concat(Bytes("vault_removed:"), vault_address.get())),
        Approve()
    )

@app.external
def freeze_address(target_address: abi.Address):
    """Freeze an address from transacting"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Re-assert freeze authority before freezing
        (freeze := AssetParam.freeze(app.state.cusd_asset_id)),
        Assert(freeze.hasValue()),
        Assert(freeze.value() == Global.current_application_address()),
        
        # Check target has opted into cUSD (ASA opt-in only)
        (balance := AssetHolding.balance(target_address.get(), app.state.cusd_asset_id)),
        Assert(balance.hasValue()),
        
        # App call must fund inner freeze transaction
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Set local state
        app.state.is_frozen[target_address.get()].set(Int(1)),
        
        # Issue actual ASA freeze transaction
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetFreeze,
            TxnField.freeze_asset: app.state.cusd_asset_id,
            TxnField.freeze_asset_account: target_address.get(),
            TxnField.freeze_asset_frozen: Int(1)
        }),
        InnerTxnBuilder.Submit(),
        
        Log(Concat(Bytes("freeze:"), target_address.get())),
        Approve()
    )

@app.external
def unfreeze_address(target_address: abi.Address):
    """Unfreeze an address"""
    return Seq(
        Assert(
            And(
                Txn.sender() == app.state.admin,
                app.state.is_paused == Int(0)
            )
        ),
        Assert(Txn.rekey_to() == Global.zero_address()),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Re-assert freeze authority before unfreezing
        (freeze := AssetParam.freeze(app.state.cusd_asset_id)),
        Assert(freeze.hasValue()),
        Assert(freeze.value() == Global.current_application_address()),
        
        # Check target has opted into cUSD (ASA opt-in only)
        (balance := AssetHolding.balance(target_address.get(), app.state.cusd_asset_id)),
        Assert(balance.hasValue()),
        
        # App call must fund inner freeze transaction
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Clear local state
        app.state.is_frozen[target_address.get()].set(Int(0)),
        
        # Issue actual ASA unfreeze transaction
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetFreeze,
            TxnField.freeze_asset: app.state.cusd_asset_id,
            TxnField.freeze_asset_account: target_address.get(),
            TxnField.freeze_asset_frozen: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        Log(Concat(Bytes("unfreeze:"), target_address.get())),
        Approve()
    )

@app.external
def mint_admin(
    amount: abi.Uint64,
    recipient: abi.Address
):
    """
    Admin minting backed by T-bills or other reserves
    This is separate from USDC collateralized minting
    Can be used for treasury-backed issuance
    """
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.is_paused == Int(0)),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        Assert(app.state.is_frozen[recipient.get()] == Int(0)),
        Assert(amount.get() > Int(0)),
        
        # Ensure asset is configured
        Assert(app.state.cusd_asset_id != Int(0)),
        
        # Re-assert clawback authority before minting
        (claw := AssetParam.clawback(app.state.cusd_asset_id)),
        Assert(claw.hasValue()),
        Assert(claw.value() == Global.current_application_address()),
        
        # App call must fund inner asset transfer (app call + 1 inner)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Verify reserve address hasn't changed
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        Assert(reserve.value() == app.state.reserve_address),
        
        # Verify recipient has opted into cUSD
        (r := AssetHolding.balance(recipient.get(), app.state.cusd_asset_id)),
        Assert(r.hasValue()),
        
        # Pre-check reserve has sufficient balance
        (res_bal := AssetHolding.balance(app.state.reserve_address, app.state.cusd_asset_id)),
        Assert(res_bal.hasValue()),
        Assert(res_bal.value() >= amount.get()),
        
        # Mint cUSD via clawback from reserve
        # The contract is the clawback authority, so it can transfer from reserve
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),  # Inner transaction fee=0
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: amount.get(),
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_sender: app.state.reserve_address  # Use stored reserve
        }),
        InnerTxnBuilder.Submit(),
        
        # Update statistics (separate from collateral-backed supply)
        app.state.total_minted.set(
            app.state.total_minted + amount.get()
        ),
        app.state.tbills_backed_supply.set(
            app.state.tbills_backed_supply + amount.get()
        ),
        
        # Log admin mint event
        Log(Concat(
            Bytes("admin_mint:"),
            Itob(amount.get()),
            Bytes(":"),
            recipient.get()
        )),
        
        Approve()
    )

@app.external
def burn_admin(
    amount: abi.Uint64
):
    """
    Admin burning to reduce supply (e.g., when selling T-bills)
    Must be called with cUSD transfer to app
    """
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.is_paused == Int(0)),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Verify atomic group with cUSD transfer
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[0].xfer_asset() == app.state.cusd_asset_id),
        Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[0].asset_amount() == amount.get()),
        
        # Tie cUSD deposit to admin & harden inputs
        Assert(Gtxn[0].sender() == Txn.sender()),
        Assert(Gtxn[0].rekey_to() == Global.zero_address()),
        Assert(Gtxn[0].asset_close_to() == Global.zero_address()),
        Assert(Gtxn[0].asset_sender() == Global.zero_address()),
        
        # Check underflow
        Assert(app.state.tbills_backed_supply >= amount.get()),
        
        # App call must fund inner transfer (app call + 1 inner)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Verify reserve address hasn't changed
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        Assert(reserve.value() == app.state.reserve_address),
        
        # Return burned cUSD to reserve
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: amount.get(),
            TxnField.asset_receiver: app.state.reserve_address,  # Use stored reserve
            TxnField.asset_sender: Global.current_application_address()
        }),
        InnerTxnBuilder.Submit(),
        
        # Update statistics
        app.state.total_burned.set(
            app.state.total_burned + amount.get()
        ),
        app.state.tbills_backed_supply.set(
            app.state.tbills_backed_supply - amount.get()
        ),
        
        # Log admin burn event
        Log(Concat(
            Bytes("admin_burn:"),
            Itob(amount.get())
        )),
        
        Approve()
    )

@app.external
def mint_with_collateral():
    """
    Mint cUSD by depositing USDC (1:1 ratio)
    Must be called as part of atomic group with USDC transfer
    
    Supports two group structures:
    
    Non-sponsored (2 transactions):
    - Tx 0: USDC transfer from user to app
    - Tx 1: This app call
    
    Sponsored (3 transactions):
    - Tx 0: Payment from sponsor to user (or app) for fees
    - Tx 1: USDC transfer from user to app
    - Tx 2: This app call
    """
    usdc_amount = ScratchVar(TealType.uint64)
    cusd_to_mint = ScratchVar(TealType.uint64)
    is_sponsored = ScratchVar(TealType.uint64)
    usdc_tx_index = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify system state
        Assert(app.state.is_paused == Int(0)),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.usdc_asset_id != Int(0)),
        Assert(app.state.cusd_asset_id != Int(0)),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Re-assert clawback authority before minting
        (claw := AssetParam.clawback(app.state.cusd_asset_id)),
        Assert(claw.hasValue()),
        Assert(claw.value() == Global.current_application_address()),
        
        # Verify atomic group - support both 2-tx and 3-tx groups
        Assert(Or(
            Global.group_size() == Int(2),  # Non-sponsored
            Global.group_size() == Int(3)   # Sponsored
        )),
        
        # Determine if sponsored and set indexes
        If(Global.group_size() == Int(3),
            Seq(
                is_sponsored.store(Int(1)),
                usdc_tx_index.store(Int(1)),  # USDC transfer is at index 1 in sponsored
                Assert(Txn.group_index() == Int(2)),  # App call is at index 2
                
                # Verify sponsor payment (Tx 0)
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].sender() == app.state.sponsor_address.get()),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == Gtxn[1].sender(),  # Payment to asset sender (the user)
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
            ),
            Seq(
                is_sponsored.store(Int(0)),
                usdc_tx_index.store(Int(0)),  # USDC transfer is at index 0 in non-sponsored
                Assert(Txn.group_index() == Int(1)),  # App call is at index 1
            )
        ),
        
        # Allow either the user (asset transfer sender) or sponsor to be the app call sender
        Assert(Or(
            Txn.sender() == Gtxn[usdc_tx_index.load()].sender(),  # User is sender
            Txn.sender() == app.state.sponsor_address.get()  # Sponsor is sender - need .get()!
        )),
        
        # Verify USDC deposit
        Assert(Gtxn[usdc_tx_index.load()].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[usdc_tx_index.load()].xfer_asset() == app.state.usdc_asset_id),
        Assert(Gtxn[usdc_tx_index.load()].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[usdc_tx_index.load()].asset_amount() > Int(0)),
        
        # Harden deposit inputs
        Assert(Gtxn[usdc_tx_index.load()].rekey_to() == Global.zero_address()),
        Assert(Gtxn[usdc_tx_index.load()].asset_close_to() == Global.zero_address()),
        Assert(Gtxn[usdc_tx_index.load()].asset_sender() == Global.zero_address()),
        
        # Verify sender is not frozen
        Assert(app.state.is_frozen[Gtxn[usdc_tx_index.load()].sender()] == Int(0)),
        
        # Verify receiver has opted into cUSD
        (h := AssetHolding.balance(Gtxn[usdc_tx_index.load()].sender(), app.state.cusd_asset_id)),
        Assert(h.hasValue()),
        
        # Store amounts
        usdc_amount.store(Gtxn[usdc_tx_index.load()].asset_amount()),

        # App call must fund inner asset transfer (app call + 1 inner)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Calculate cUSD to mint: always 1:1 for peg safety
        cusd_to_mint.store(usdc_amount.load()),
        
        # Guard against zero amount after ratio math
        Assert(cusd_to_mint.load() > Int(0)),
        
        # Verify reserve address hasn't changed
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        Assert(reserve.value() == app.state.reserve_address),
        
        # Pre-check reserve has sufficient balance
        (res_bal := AssetHolding.balance(app.state.reserve_address, app.state.cusd_asset_id)),
        Assert(res_bal.hasValue()),
        Assert(res_bal.value() >= cusd_to_mint.load()),
        
        # Mint cUSD via clawback from reserve
        # The contract is the clawback authority, so it can transfer from reserve
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),  # Inner transaction fee=0
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: cusd_to_mint.load(),
            TxnField.asset_receiver: Gtxn[usdc_tx_index.load()].sender(),  # Send to original USDC depositor
            TxnField.asset_sender: app.state.reserve_address  # Use stored reserve
        }),
        InnerTxnBuilder.Submit(),
        
        # Update statistics
        app.state.total_usdc_locked.set(
            app.state.total_usdc_locked + usdc_amount.load()
        ),
        app.state.total_minted.set(
            app.state.total_minted + cusd_to_mint.load()
        ),
        app.state.cusd_circulating_supply.set(
            app.state.cusd_circulating_supply + cusd_to_mint.load()
        ),
        
        # Log event
        Log(Concat(
            Bytes("mint:"),
            Itob(cusd_to_mint.load()),
            Bytes(":"),
            Gtxn[usdc_tx_index.load()].sender()
        )),
        
        Approve()
    )

@app.external
def burn_for_collateral():
    """
    Burn cUSD to redeem USDC (1:1 ratio)
    Must be called as part of atomic group with cUSD transfer
    
    Supports two group structures:
    
    Non-sponsored (2 transactions):
    - Tx 0: cUSD transfer from user to app
    - Tx 1: This app call
    
    Sponsored (3 transactions):
    - Tx 0: Payment from sponsor to user (or app) for fees
    - Tx 1: cUSD transfer from user to app
    - Tx 2: This app call
    """
    cusd_amount = ScratchVar(TealType.uint64)
    usdc_to_redeem = ScratchVar(TealType.uint64)
    is_sponsored = ScratchVar(TealType.uint64)
    cusd_tx_index = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify system state
        Assert(app.state.is_paused == Int(0)),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.usdc_asset_id != Int(0)),
        Assert(app.state.cusd_asset_id != Int(0)),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Re-assert clawback authority before burning
        (claw := AssetParam.clawback(app.state.cusd_asset_id)),
        Assert(claw.hasValue()),
        Assert(claw.value() == Global.current_application_address()),
        
        # Verify atomic group - support both 2-tx and 3-tx groups
        Assert(Or(
            Global.group_size() == Int(2),  # Non-sponsored
            Global.group_size() == Int(3)   # Sponsored
        )),
        
        # Determine if sponsored and set indexes
        If(Global.group_size() == Int(3),
            Seq(
                is_sponsored.store(Int(1)),
                cusd_tx_index.store(Int(1)),  # cUSD transfer is at index 1 in sponsored
                Assert(Txn.group_index() == Int(2)),  # App call is at index 2
                
                # Verify sponsor payment (Tx 0)
                Assert(Gtxn[0].type_enum() == TxnType.Payment),
                Assert(Gtxn[0].sender() == app.state.sponsor_address.get()),
                Assert(Gtxn[0].amount() >= Int(0)),  # Can be 0 if just covering fees
                Assert(Or(
                    Gtxn[0].receiver() == Gtxn[1].sender(),  # Payment to asset sender (the user)
                    Gtxn[0].receiver() == Global.current_application_address()  # Payment to app
                )),
            ),
            Seq(
                is_sponsored.store(Int(0)),
                cusd_tx_index.store(Int(0)),  # cUSD transfer is at index 0 in non-sponsored
                Assert(Txn.group_index() == Int(1)),  # App call is at index 1
            )
        ),
        
        # Allow either the user (asset transfer sender) or sponsor to be the app call sender
        Assert(Or(
            Txn.sender() == Gtxn[cusd_tx_index.load()].sender(),  # User is sender
            Txn.sender() == app.state.sponsor_address.get()  # Sponsor is sender - need .get()!
        )),
        
        # Verify cUSD deposit
        Assert(Gtxn[cusd_tx_index.load()].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[cusd_tx_index.load()].xfer_asset() == app.state.cusd_asset_id),
        Assert(Gtxn[cusd_tx_index.load()].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[cusd_tx_index.load()].asset_amount() > Int(0)),
        
        # Harden withdraw inputs
        Assert(Gtxn[cusd_tx_index.load()].rekey_to() == Global.zero_address()),
        Assert(Gtxn[cusd_tx_index.load()].asset_close_to() == Global.zero_address()),
        Assert(Gtxn[cusd_tx_index.load()].asset_sender() == Global.zero_address()),
        
        # Verify sender is not frozen
        Assert(app.state.is_frozen[Gtxn[cusd_tx_index.load()].sender()] == Int(0)),
        
        # Store amounts
        cusd_amount.store(Gtxn[cusd_tx_index.load()].asset_amount()),

        # App call must fund 2 inner transfers (USDC out + cUSD back to reserve)
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(3)),
        
        # Calculate USDC to redeem: always 1:1 for peg safety
        usdc_to_redeem.store(cusd_amount.load()),
        
        # Guard against zero amount after ratio math
        Assert(usdc_to_redeem.load() > Int(0)),
        
        # Verify sufficient USDC reserves
        (usdc_balance := AssetHolding.balance(
            Global.current_application_address(), 
            app.state.usdc_asset_id
        )),
        Assert(usdc_balance.hasValue()),
        Assert(usdc_balance.value() >= usdc_to_redeem.load()),
        
        # Send USDC back to user
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),  # Inner transaction fee=0
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.usdc_asset_id,
            TxnField.asset_amount: usdc_to_redeem.load(),
            TxnField.asset_receiver: Gtxn[cusd_tx_index.load()].sender()
        }),
        InnerTxnBuilder.Submit(),
        
        # Verify reserve address hasn't changed and send burned cUSD back
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        Assert(reserve.value() == app.state.reserve_address),
        
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: cusd_amount.load(),
            TxnField.asset_receiver: app.state.reserve_address,  # Use stored reserve
            TxnField.asset_sender: Global.current_application_address()
        }),
        InnerTxnBuilder.Submit(),
        
        # Check underflows and update statistics
        Assert(app.state.total_usdc_locked >= usdc_to_redeem.load()),
        Assert(app.state.cusd_circulating_supply >= cusd_amount.load()),
        
        app.state.total_usdc_locked.set(
            app.state.total_usdc_locked - usdc_to_redeem.load()
        ),
        app.state.total_burned.set(
            app.state.total_burned + cusd_amount.load()
        ),
        app.state.cusd_circulating_supply.set(
            app.state.cusd_circulating_supply - cusd_amount.load()
        ),
        
        # Log event
        Log(Concat(
            Bytes("burn:"),
            Itob(cusd_amount.load()),
            Bytes(":"),
            Gtxn[cusd_tx_index.load()].sender()
        )),
        
        Approve()
    )

@app.external
def transfer_cusd(
    asset_transfer: abi.AssetTransferTransaction,
    recipient: abi.Address
):
    """
    Transfer Confío Dollar with freeze checks
    Called alongside an ASA transfer transaction
    
    Note: For stricter group binding, could require:
    - Global.group_size() == Int(2)
    - Txn.group_index() == Int(1)
    - asset_transfer matches Gtxn[0]
    Current implementation is sufficient since ASA freeze is enforced globally.
    """
    return Seq(
        # Bind the transfer to the caller
        Assert(asset_transfer.get().sender() == Txn.sender()),
        
        # Verify the asset transfer is for Confío Dollar
        Assert(
            And(
                asset_transfer.get().xfer_asset() == app.state.cusd_asset_id,
                asset_transfer.get().asset_receiver() == recipient.get(),
                app.state.is_paused == Int(0),
                app.state.is_frozen[asset_transfer.get().sender()] == Int(0),
                app.state.is_frozen[recipient.get()] == Int(0)
            )
        ),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        # Disallow rekey/close/clawback on provided transfer and on this call
        Assert(asset_transfer.get().rekey_to() == Global.zero_address()),
        Assert(asset_transfer.get().asset_close_to() == Global.zero_address()),
        Assert(asset_transfer.get().asset_sender() == Global.zero_address()),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Approve()
    )

@app.external
def update_admin(new_admin: abi.Address):
    """
    Transfer admin rights to a new address (can be a multi-sig wallet)
    Only current admin can transfer rights
    """
    return Seq(
        # Only current admin can transfer
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(Len(new_admin.get()) == Int(32)),
        # Prevent setting admin to zero address
        Assert(new_admin.get() != Global.zero_address()),
        
        # Update admin
        app.state.admin.set(new_admin.get()),
        
        # Log admin change
        Log(Concat(
            Bytes("admin_changed:"),
            new_admin.get()
        )),
        
        Approve()
    )

@app.external
def update_collateral_ratio(new_ratio: abi.Uint64):
    """
    Update collateral ratio (admin only)
    1000000 = 1:1, 1500000 = 1.5:1 (150% collateralized)
    Range: 100%-200%
    """
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Assert(app.state.is_paused == Int(0)),
        Assert(new_ratio.get() >= Int(1000000)),  # Minimum 100% collateral
        Assert(new_ratio.get() <= Int(2000000)),  # Maximum 200% collateral
        
        app.state.collateral_ratio.set(new_ratio.get()),
        
        Log(Concat(
            Bytes("ratio:"),
            Itob(new_ratio.get())
        )),
        
        Approve()
    )

@app.external
def refresh_reserve():
    """
    Refresh the stored reserve address from ASA parameters
    Admin only - use if ASA reserve was intentionally rotated
    """
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Read current reserve from ASA
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        
        # Update stored reserve
        app.state.reserve_address.set(reserve.value()),
        
        Log(Bytes("reserve_refreshed")),
        Approve()
    )

@app.external
def withdraw_usdc(
    amount: abi.Uint64,
    recipient: abi.Address
):
    """
    Withdraw USDC for treasury rebalancing (e.g., to purchase mTBILL)
    Admin only - can be done while system is operational
    Maintains backing ratio by adjusting tracked reserves
    """
    remaining = ScratchVar(TealType.uint64)
    
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        # cUSD ASA manager must be permanently locked to zero
        (mgr := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(mgr.hasValue()),
        Assert(mgr.value() == Global.zero_address()),
        
        # Verify recipient is valid
        Assert(Len(recipient.get()) == Int(32)),
        
        # Check USDC balance
        (usdc_balance := AssetHolding.balance(
            Global.current_application_address(), 
            app.state.usdc_asset_id
        )),
        Assert(usdc_balance.hasValue()),
        Assert(usdc_balance.value() >= amount.get()),
        
        # Calculate remaining after withdrawal
        remaining.store(usdc_balance.value() - amount.get()),
        
        # Ensure withdrawal doesn't exceed 70% of circulating supply
        # Must keep at least 30% as liquid USDC for redemptions
        Assert(
            remaining.load() >= 
            WideRatio([app.state.cusd_circulating_supply, Int(300_000)], [Int(1_000_000)])
        ),
        # Ensure 100% on-chain USDC backing remains after withdrawal
        Assert(remaining.load() >= app.state.cusd_circulating_supply),
        
        # App call must fund inner transfer
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        
        # Send USDC to recipient
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.fee: Int(0),
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.usdc_asset_id,
            TxnField.asset_amount: amount.get(),
            TxnField.asset_receiver: recipient.get()
        }),
        InnerTxnBuilder.Submit(),
        
        # Update tracked USDC (for treasury management accounting)
        Assert(app.state.total_usdc_locked >= amount.get()),
        app.state.total_usdc_locked.set(
            app.state.total_usdc_locked - amount.get()
        ),
        
        # Log treasury rebalancing
        Log(Concat(
            Bytes("usdc_withdraw:"),
            Itob(amount.get()),
            Bytes(":"),
            recipient.get()
        )),
        
        Approve()
    )

@app.external(read_only=True)
def get_stats(*, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
    """Get minting and burning statistics"""
    minted = abi.Uint64()
    burned = abi.Uint64()
    return Seq(
        minted.set(app.state.total_minted),
        burned.set(app.state.total_burned),
        output.set(minted, burned)
    )

@app.external(read_only=True)
def get_reserves(*, output: abi.Tuple5[abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64, abi.Uint64]):
    """
    Get reserve statistics
    Returns: (total_usdc_locked, cusd_circulating_supply, tbills_backed_supply, collateral_ratio, total_supply)
    """
    usdc = abi.Uint64()
    cusd_collateral = abi.Uint64()
    tbills = abi.Uint64()
    ratio = abi.Uint64()
    total = abi.Uint64()
    
    return Seq(
        usdc.set(app.state.total_usdc_locked),
        cusd_collateral.set(app.state.cusd_circulating_supply),
        tbills.set(app.state.tbills_backed_supply),
        ratio.set(app.state.collateral_ratio),
        total.set(app.state.cusd_circulating_supply + app.state.tbills_backed_supply),
        output.set(usdc, cusd_collateral, tbills, ratio, total)
    )

@app.external(read_only=True)
def verify_backing(*, output: abi.Tuple2[abi.Bool, abi.Uint64]):
    """
    Verify that USDC reserves match or exceed cUSD supply
    Returns (is_backed, actual_usdc_balance)
    """
    result = abi.Bool()
    actual_balance = abi.Uint64()
    
    return Seq(
        # Get actual on-chain USDC balance
        (usdc_bal := AssetHolding.balance(
            Global.current_application_address(), 
            app.state.usdc_asset_id
        )),
        Assert(usdc_bal.hasValue()),
        actual_balance.set(usdc_bal.value()),
        
        # Peg safety: operational backing is 1:1 on-chain USDC
        result.set(usdc_bal.value() >= app.state.cusd_circulating_supply),
        output.set(result, actual_balance)
    )

@app.external(read_only=True)
def verify_policy_target(*, output: abi.Tuple2[abi.Bool, abi.Uint64]):
    """
    Telemetry: verify coverage against policy target (collateral_ratio)
    Returns (meets_target, actual_usdc_balance)
    """
    result = abi.Bool()
    actual_balance = abi.Uint64()
    return Seq(
        (usdc_bal := AssetHolding.balance(
            Global.current_application_address(),
            app.state.usdc_asset_id
        )),
        Assert(usdc_bal.hasValue()),
        actual_balance.set(usdc_bal.value()),
        # Compare USDC * 1e6 >= circulating * ratio
        result.set(
            WideRatio([usdc_bal.value(), Int(1_000_000)], [Int(1)]) >=
            WideRatio([app.state.cusd_circulating_supply, app.state.collateral_ratio], [Int(1)])
        ),
        output.set(result, actual_balance)
    )

@app.external(read_only=True)
def is_frozen(address: abi.Address, *, output: abi.Bool):
    """Check if an address is frozen"""
    return Seq(
        output.set(app.state.is_frozen[address.get()] == Int(1))
    )

@app.external(read_only=True)
def is_vault(address: abi.Address, *, output: abi.Bool):
    """Check if an address is a vault"""
    return Seq(
        output.set(app.state.is_vault[address.get()] == Int(1))
    )

@app.update
def update():
    """Only admin can update the application"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        Approve()
    )

@app.delete
def delete():
    """Only admin can delete - require no outstanding supply and ASA reconfigured"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
        Assert(Txn.rekey_to() == Global.zero_address()),
        
        # Defensive: ensure assets were configured
        Assert(app.state.cusd_asset_id != Int(0)),
        
        # Require no outstanding cUSD (tracked counters)
        Assert(app.state.cusd_circulating_supply == Int(0)),
        Assert(app.state.tbills_backed_supply == Int(0)),
        
        # Also verify on-chain: app holds no cUSD
        (app_bal := AssetHolding.balance(Global.current_application_address(), app.state.cusd_asset_id)),
        Assert(app_bal.hasValue()),
        Assert(app_bal.value() == Int(0)),
        
        # Verify all supply is back in reserve (use live reserve address)
        (total := AssetParam.total(app.state.cusd_asset_id)),
        Assert(total.hasValue()),
        # Read current reserve address in case it was rotated
        (reserve := AssetParam.reserve(app.state.cusd_asset_id)),
        Assert(reserve.hasValue()),
        (res_bal := AssetHolding.balance(reserve.value(), app.state.cusd_asset_id)),
        Assert(res_bal.hasValue()),
        Assert(res_bal.value() == total.value()),
        
        # Manager must be zero-address (immutability); claw/freeze may remain app
        (manager := AssetParam.manager(app.state.cusd_asset_id)),
        Assert(manager.hasValue()),
        Assert(manager.value() == Global.zero_address()),
        
        Approve()
    )

if __name__ == "__main__":
    import json
    
    # Export the contract
    spec = app.build()
    
    # Write approval program
    with open("cusd_approval.teal", "w") as f:
        f.write(spec.approval_program)
    
    # Write clear program  
    with open("cusd_clear.teal", "w") as f:
        f.write(spec.clear_program)
    
    # Write ABI with type-safety for Beaker version quirks
    abi_json = spec.export()
    if abi_json is None:
        # Create a minimal ABI manually for the methods we need
        abi_json = {
            "name": "ConfioDollar",
            "methods": [
                {
                    "name": "setup_assets",
                    "args": [
                        {"type": "uint64", "name": "cusd_id"},
                        {"type": "uint64", "name": "usdc_id"}
                    ],
                    "returns": {"type": "void"}
                }
            ],
            "desc": "Confío Dollar stablecoin contract"
        }
    with open("cusd.json", "w") as f:
        # Handle both string and dict returns from export()
        f.write(abi_json if isinstance(abi_json, str) else json.dumps(abi_json, indent=2))
    
    print("Confío Dollar contract compiled successfully!")
    print("Website: confio.lat")
