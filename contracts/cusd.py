"""
Confío Dollar (cUSD) - Algorand ASA with admin controls
A USD-pegged stablecoin for Confío with freeze, pause, and vault management
Website: confio.lat
"""

from pyteal import *
from beaker import *
from typing import Final
import os

# USDC Asset IDs for different networks
USDC_MAINNET = 31566704  # Official USDC on Algorand mainnet
USDC_TESTNET = 10458941  # USDC on Algorand testnet

# Get USDC asset ID from environment or use defaults
def get_usdc_asset_id():
    """
    Get USDC asset ID from environment variable or detect network
    Set ALGORAND_NETWORK=mainnet or ALGORAND_NETWORK=testnet
    Or set USDC_ASSET_ID directly
    """
    # First check if USDC_ASSET_ID is explicitly set
    if os.getenv('USDC_ASSET_ID'):
        return int(os.getenv('USDC_ASSET_ID'))
    
    # Otherwise check network type
    network = os.getenv('ALGORAND_NETWORK', 'testnet').lower()
    
    if network == 'mainnet':
        print(f"Using mainnet USDC asset ID: {USDC_MAINNET}")
        return USDC_MAINNET
    else:
        print(f"Using testnet USDC asset ID: {USDC_TESTNET}")
        return USDC_TESTNET

# Get the USDC asset ID for current environment
USDC_ASSET_ID = get_usdc_asset_id()

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
        default=Int(1000000),  # 1:1 ratio with 6 decimals
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
        app.state.admin.set(Txn.sender()),
        app.state.is_paused.set(Int(0)),
        app.state.collateral_ratio.set(Int(1000000)),  # 1:1 ratio
        Approve()
    )

@app.external
def setup_assets(cusd_id: abi.Uint64, usdc_id: abi.Uint64):
    """
    Setup asset IDs and opt-in to both assets
    Note: cUSD reserve address should be rekeyed to this app for minting authority
    """
    return Seq(
        # Admin only
        Assert(Txn.sender() == app.state.admin),
        Assert(app.state.cusd_asset_id == Int(0)),  # Can only be set once
        
        # Store asset IDs
        app.state.cusd_asset_id.set(cusd_id.get()),
        app.state.usdc_asset_id.set(usdc_id.get()),
        
        # Opt-in to USDC
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: usdc_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
        # Opt-in to cUSD
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: cusd_id.get(),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0)
        }),
        InnerTxnBuilder.Submit(),
        
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
        app.state.is_paused.set(Int(1)),
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
        app.state.is_paused.set(Int(0)),
        Approve()
    )

@app.opt_in
def opt_in():
    """Allow accounts to opt-in"""
    return Seq(
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
        app.state.is_vault[vault_address.get()].set(Int(1)),
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
        app.state.is_vault[vault_address.get()].set(Int(0)),
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
        app.state.is_frozen[target_address.get()].set(Int(1)),
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
        app.state.is_frozen[target_address.get()].set(Int(0)),
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
        Assert(app.state.is_paused == Int(0)),
        Assert(app.state.is_frozen[recipient.get()] == Int(0)),
        Assert(amount.get() > Int(0)),
        
        # Mint cUSD via clawback from reserve
        # The contract is the clawback authority, so it can transfer from reserve
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: amount.get(),
            TxnField.asset_receiver: recipient.get(),
            TxnField.asset_sender: app.state.admin  # Clawback from admin/reserve account
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
        Assert(app.state.is_paused == Int(0)),
        
        # Verify atomic group with cUSD transfer
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[0].xfer_asset() == app.state.cusd_asset_id),
        Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[0].asset_amount() == amount.get()),
        
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
    
    Group structure:
    - Tx 0: USDC transfer from user to app
    - Tx 1: This app call
    """
    usdc_amount = ScratchVar(TealType.uint64)
    cusd_to_mint = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify system state
        Assert(app.state.is_paused == Int(0)),
        
        # Verify atomic group
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        
        # Verify USDC deposit (Tx 0)
        Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[0].xfer_asset() == app.state.usdc_asset_id),
        Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[0].asset_amount() > Int(0)),
        
        # Verify sender is not frozen
        Assert(app.state.is_frozen[Gtxn[0].sender()] == Int(0)),
        
        # Store amounts
        usdc_amount.store(Gtxn[0].asset_amount()),
        
        # Calculate cUSD to mint (1:1 ratio)
        # cusd_amount = usdc_amount * 1e6 / collateral_ratio
        # Since ratio is 1e6 (1:1), cusd_amount = usdc_amount
        cusd_to_mint.store(
            usdc_amount.load() * Int(1000000) / app.state.collateral_ratio
        ),
        
        # Mint cUSD via clawback from reserve
        # The contract is the clawback authority, so it can transfer from reserve
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.cusd_asset_id,
            TxnField.asset_amount: cusd_to_mint.load(),
            TxnField.asset_receiver: Gtxn[0].sender(),  # Send to original USDC depositor
            TxnField.asset_sender: app.state.admin  # Clawback from admin/reserve account
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
            Gtxn[0].sender()
        )),
        
        Approve()
    )

@app.external
def burn_for_collateral():
    """
    Burn cUSD to redeem USDC (1:1 ratio)
    Must be called as part of atomic group with cUSD transfer
    
    Group structure:
    - Tx 0: cUSD transfer from user to app
    - Tx 1: This app call
    """
    cusd_amount = ScratchVar(TealType.uint64)
    usdc_to_redeem = ScratchVar(TealType.uint64)
    
    return Seq(
        # Verify system state
        Assert(app.state.is_paused == Int(0)),
        
        # Verify atomic group
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(1)),
        
        # Verify cUSD deposit (Tx 0)
        Assert(Gtxn[0].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[0].xfer_asset() == app.state.cusd_asset_id),
        Assert(Gtxn[0].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[0].asset_amount() > Int(0)),
        
        # Verify sender is not frozen
        Assert(app.state.is_frozen[Gtxn[0].sender()] == Int(0)),
        
        # Store amounts
        cusd_amount.store(Gtxn[0].asset_amount()),
        
        # Calculate USDC to redeem (1:1 ratio)
        usdc_to_redeem.store(
            cusd_amount.load() * app.state.collateral_ratio / Int(1000000)
        ),
        
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
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: app.state.usdc_asset_id,
            TxnField.asset_amount: usdc_to_redeem.load(),
            TxnField.asset_receiver: Gtxn[0].sender()
        }),
        InnerTxnBuilder.Submit(),
        
        # Burn the cUSD (keep it in the app for simplicity)
        # In production, you might send to a burn address
        
        # Update statistics
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
            Gtxn[0].sender()
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
    """
    return Seq(
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
    """
    return Seq(
        Assert(Txn.sender() == app.state.admin),
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
def verify_backing(*, output: abi.Bool):
    """
    Verify that USDC reserves match or exceed cUSD supply
    Returns true if properly backed
    """
    result = abi.Bool()
    
    return Seq(
        # Check if USDC locked >= cUSD supply (considering ratio)
        result.set(
            app.state.total_usdc_locked >= 
            (app.state.cusd_circulating_supply * app.state.collateral_ratio / Int(1000000))
        ),
        output.set(result)
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

@app.delete
def delete():
    """Only admin can delete the application"""
    return Seq(
        Assert(Txn.sender() == app.state.admin),
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
    
    # Write ABI
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
        f.write(json.dumps(abi_json, indent=2))
    
    print("Confío Dollar contract compiled successfully!")
    print(f"USDC Asset ID configured: {USDC_ASSET_ID}")
    print("Website: confio.lat")
    print("\nConfiguration options:")
    print("  - Set ALGORAND_NETWORK=mainnet for mainnet USDC (31566704)")
    print("  - Set ALGORAND_NETWORK=testnet for testnet USDC (10458941)")
    print("  - Set USDC_ASSET_ID=<custom_id> for custom asset ID")