#!/usr/bin/env python3
"""
CONFIO Token Presale Contract

Features:
- Full sponsor support (ALL fees covered by sponsor, users only need cUSD)
- cUSD-based caps for easy calculation
- Flexible exchange rates per round
- Lock/unlock mechanism
- Clean and simple implementation

Round Structure (configurable):
- Round 1: 0.25 cUSD per CONFIO (1M cUSD raise goal)
- Round 2: 0.50 cUSD per CONFIO (10M cUSD raise goal)
- Round 3: 1.00 cUSD per CONFIO (TBD raise goal)
"""

from pyteal import *

def confio_presale():
    """
    CONFIO presale contract with full sponsor support.
    """
    
    # Decimal scale constants (hardcoded for safety)
    CONFIO_DECIMALS = Int(1000000)    # 10^6 (6 decimals)
    CUSD_DECIMALS = Int(1000000)       # 10^6 (6 decimals)
    
    # Global state schema: 17 ints, 2 bytes
    # General settings
    confio_asset_id = Bytes("confio_id")
    cusd_asset_id = Bytes("cusd_id")
    admin_address = Bytes("admin")
    sponsor_address = Bytes("sponsor")
    
    # Round parameters
    current_round = Bytes("round")
    round_active = Bytes("active")  # 0 = paused, 1 = active
    cusd_per_confio = Bytes("price")  # Price in cUSD per CONFIO (with 6 decimals)
    round_cusd_cap = Bytes("cusd_cap")  # Max cUSD to raise this round
    round_cusd_raised = Bytes("cusd_raised")  # cUSD raised in current round
    min_buy_cusd = Bytes("min_buy")  # Minimum cUSD per transaction
    max_buy_cusd_per_address = Bytes("max_addr")  # Max cUSD per address per round
    
    # Lock mechanism
    tokens_locked = Bytes("locked")  # 0 = unlocked permanently, 1 = locked
    unlock_time = Bytes("unlock_time")  # Timestamp when unlocked
    
    # Statistics
    total_rounds = Bytes("total_rounds")
    total_confio_sold = Bytes("confio_sold")  # Total CONFIO sold across all rounds
    total_confio_claimed = Bytes("claimed_total")  # Total CONFIO claimed by users
    total_cusd_raised = Bytes("total_raised")  # Total cUSD raised across all rounds
    total_participants = Bytes("participants")
    
    # Contract state
    contract_paused = Bytes("paused")  # Emergency pause
    
    # Local state schema: 5 ints, 0 bytes (per user)
    user_total_confio = Bytes("user_confio")  # Total CONFIO purchased
    user_total_cusd = Bytes("user_cusd")  # Total cUSD spent
    user_claimed = Bytes("claimed")  # CONFIO already claimed
    user_round_cusd = Bytes("round_cusd")  # cUSD spent this round (for per-round cap)
    user_round = Bytes("user_round")  # User's last active round
    
    # Initialize contract
    @Subroutine(TealType.uint64)
    def initialize():
        confio_id_arg = Btoi(Txn.application_args[0])
        cusd_id_arg = Btoi(Txn.application_args[1])
        
        return Seq([
            # Verify arguments
            Assert(Txn.application_args.length() == Int(4)),
            
            # Validate asset IDs are non-zero
            Assert(confio_id_arg > Int(0)),  # CONFIO ID
            Assert(cusd_id_arg > Int(0)),  # cUSD ID
            
            # Validate addresses are 32 bytes
            Assert(Len(Txn.application_args[2]) == Int(32)),  # Admin address
            Assert(Len(Txn.application_args[3]) == Int(32)),  # Sponsor address
            
            # Verify ASA decimals match expected values
            (confio_decimals := AssetParam.decimals(confio_id_arg)),
            (cusd_decimals := AssetParam.decimals(cusd_id_arg)),
            Assert(confio_decimals.hasValue()),
            Assert(cusd_decimals.hasValue()),
            Assert(confio_decimals.value() == Int(6)),  # CONFIO must have 6 decimals
            Assert(cusd_decimals.value() == Int(6)),    # cUSD must have 6 decimals
            
            # Set asset IDs, admin, and sponsor
            App.globalPut(confio_asset_id, confio_id_arg),
            App.globalPut(cusd_asset_id, cusd_id_arg),
            App.globalPut(admin_address, Txn.application_args[2]),
            App.globalPut(sponsor_address, Txn.application_args[3]),
            
            # Initialize round parameters
            App.globalPut(current_round, Int(0)),
            App.globalPut(round_active, Int(0)),
            App.globalPut(cusd_per_confio, Int(250000)),     # Default: 0.25 cUSD per CONFIO (6 decimals)
            App.globalPut(round_cusd_cap, Int(0)),
            App.globalPut(round_cusd_raised, Int(0)),
            App.globalPut(min_buy_cusd, Int(10) * CUSD_DECIMALS),  # 10 cUSD minimum
            App.globalPut(max_buy_cusd_per_address, Int(100000) * CUSD_DECIMALS),  # 100k cUSD per address default
            
            # Lock tokens by default
            App.globalPut(tokens_locked, Int(1)),
            App.globalPut(unlock_time, Int(0)),
            
            # Initialize statistics
            App.globalPut(total_rounds, Int(0)),
            App.globalPut(total_confio_sold, Int(0)),
            App.globalPut(total_confio_claimed, Int(0)),
            App.globalPut(total_cusd_raised, Int(0)),
            App.globalPut(total_participants, Int(0)),
            
            # Set contract state
            App.globalPut(contract_paused, Int(0)),
            
            Int(1)
        ])
    
    # Start new presale round (admin only)
    @Subroutine(TealType.uint64)
    def start_round():
        new_price = Btoi(Txn.application_args[1])  # cUSD per CONFIO (6 decimals)
        new_cusd_cap = Btoi(Txn.application_args[2])  # Max cUSD to raise
        new_max_per_addr = Btoi(Txn.application_args[3])  # Max cUSD per address
        
        return Seq([
            # Verify arguments
            Assert(Txn.application_args.length() >= Int(4)),
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Cannot start while contract is paused
            Assert(App.globalGet(contract_paused) == Int(0)),
            
            # Cannot start if round is active
            Assert(App.globalGet(round_active) == Int(0)),
            
            # Verify parameters
            Assert(new_price > Int(0)),
            Assert(new_cusd_cap > Int(0)),
            Assert(new_max_per_addr > Int(0)),
            Assert(new_cusd_cap >= App.globalGet(min_buy_cusd)),  # Cap must allow at least min buy
            
            # Sanity checks
            Assert(App.globalGet(min_buy_cusd) <= new_max_per_addr),  # min_buy <= max_per_addr
            Assert(new_max_per_addr <= new_cusd_cap),  # max_per_addr can't exceed round cap
            
            # Calculate CONFIO needed for this round (avoid overflow with WideRatio)
            # confio_needed = cusd_cap * CONFIO_DECIMALS / price
            (confio_needed := WideRatio([new_cusd_cap, CONFIO_DECIMALS], [new_price])),
            
            # Ensure round can sell at least 1 token
            Assert(confio_needed > Int(0)),
            
            # Check contract has enough CONFIO accounting for outstanding obligations
            (confio_balance := AssetHolding.balance(
                Global.current_application_address(),
                App.globalGet(confio_asset_id)
            )),
            Assert(confio_balance.hasValue()),
            
            # Calculate outstanding (sold but not claimed)
            (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
            
            # Ensure we have enough for outstanding + new round
            Assert(confio_balance.value() >= outstanding + confio_needed),
            
            # Start new round
            App.globalPut(current_round, App.globalGet(current_round) + Int(1)),
            App.globalPut(round_active, Int(1)),
            App.globalPut(cusd_per_confio, new_price),
            App.globalPut(round_cusd_cap, new_cusd_cap),
            App.globalPut(round_cusd_raised, Int(0)),
            App.globalPut(max_buy_cusd_per_address, new_max_per_addr),
            App.globalPut(total_rounds, App.globalGet(total_rounds) + Int(1)),
            
            # Log round details (including max_addr for full snapshot)
            Log(Concat(
                Bytes("ADMIN|START_ROUND|"),
                Itoa(App.globalGet(current_round)),
                Bytes("|"),
                Itoa(new_price),
                Bytes("|"),
                Itoa(new_cusd_cap),
                Bytes("|"),
                Itoa(new_max_per_addr)
            )),
            
            Int(1)
        ])
    
    # Buy CONFIO tokens (fully sponsored)
    @Subroutine(TealType.uint64)
    def buy_tokens():
        return Seq([
            # User must be opted into the app
            Assert(App.optedIn(Txn.sender(), Global.current_application_id())),
            
            # Check presale is active
            If(App.globalGet(round_active) != Int(1),
                Log(Bytes("ERR|ROUND_INACTIVE"))
            ),
            Assert(App.globalGet(round_active) == Int(1)),
            If(App.globalGet(contract_paused) != Int(0),
                Log(Bytes("ERR|CONTRACT_PAUSED"))
            ),
            Assert(App.globalGet(contract_paused) == Int(0)),
            
            # Group structure (fully sponsored):
            # G0: Payment from sponsor (fee bump)
            # G1: cUSD payment from buyer to contract
            # G2: This app call
            Assert(Global.group_size() == Int(3)),
            Assert(Txn.group_index() == Int(2)),
            
            # Verify sponsor fee payment (strict validation)
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].amount() == Int(0)),
            Assert(Gtxn[0].rekey_to() == Global.zero_address()),
            Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
            # Sponsor must cover total group fee (3 txns) with reasonable upper bound
            Assert(Gtxn[0].fee() >= Global.min_txn_fee() * Int(3)),
            Assert(Gtxn[0].fee() <= Global.min_txn_fee() * Int(20)),
            
            # Verify cUSD payment (with guardrails against clawback/close/rekey)
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].sender() == Txn.sender()),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(cusd_asset_id)),
            Assert(Gtxn[1].asset_close_to() == Global.zero_address()),
            Assert(Gtxn[1].asset_sender() == Global.zero_address()),
            Assert(Gtxn[1].rekey_to() == Global.zero_address()),
            Assert(Gtxn[1].fee() == Int(0)),  # User pays ZERO fees - truly sponsored
            (cusd_amount := Gtxn[1].asset_amount()),
            
            # Verify this AppCall pays zero fees (sponsor covers all)
            Assert(Txn.fee() == Int(0)),  # User pays ZERO fees
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Check minimum buy amount
            Assert(cusd_amount >= App.globalGet(min_buy_cusd)),
            
            # Check per-address cap for this round in cUSD
            (user_prev_round := App.localGet(Txn.sender(), user_round)),
            If(user_prev_round != App.globalGet(current_round),
                # New round for this user, reset their round counter
                Seq([
                    App.localPut(Txn.sender(), user_round, App.globalGet(current_round)),
                    App.localPut(Txn.sender(), user_round_cusd, Int(0))
                ])
            ),
            If(App.localGet(Txn.sender(), user_round_cusd) + cusd_amount > App.globalGet(max_buy_cusd_per_address),
                Log(Bytes("ERR|MAX_PER_ADDR"))
            ),
            Assert(App.localGet(Txn.sender(), user_round_cusd) + cusd_amount 
                   <= App.globalGet(max_buy_cusd_per_address)),
            
            # Check round cap not exceeded
            Assert(App.globalGet(round_cusd_raised) + cusd_amount <= App.globalGet(round_cusd_cap)),
            
            # Calculate CONFIO amount (avoid overflow with WideRatio)
            # confio_amount = cusd_amount * CONFIO_DECIMALS / price
            (confio_amount := WideRatio([cusd_amount, CONFIO_DECIMALS], [App.globalGet(cusd_per_confio)])),
            Assert(confio_amount > Int(0)),
            
            # Verify contract has enough CONFIO for this purchase
            (confio_balance := AssetHolding.balance(
                Global.current_application_address(),
                App.globalGet(confio_asset_id)
            )),
            Assert(confio_balance.hasValue()),
            (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
            Assert(confio_balance.value() >= outstanding + confio_amount),
            
            # Track active participants (note: can be re-counted if user closes out and re-joins)
            If(App.localGet(Txn.sender(), user_total_confio) == Int(0),
                App.globalPut(total_participants, App.globalGet(total_participants) + Int(1))
            ),
            
            # Update round statistics
            App.globalPut(round_cusd_raised, App.globalGet(round_cusd_raised) + cusd_amount),
            App.globalPut(total_confio_sold, App.globalGet(total_confio_sold) + confio_amount),
            App.globalPut(total_cusd_raised, App.globalGet(total_cusd_raised) + cusd_amount),
            
            # Update user's local state
            App.localPut(Txn.sender(), user_total_confio, 
                App.localGet(Txn.sender(), user_total_confio) + confio_amount),
            App.localPut(Txn.sender(), user_total_cusd,
                App.localGet(Txn.sender(), user_total_cusd) + cusd_amount),
            App.localPut(Txn.sender(), user_round_cusd,
                App.localGet(Txn.sender(), user_round_cusd) + cusd_amount),
            
            # Log purchase for indexing
            Log(Concat(
                Bytes("BUY|"),
                Itoa(App.globalGet(current_round)),
                Bytes("|"),
                Itoa(App.globalGet(cusd_per_confio)),
                Bytes("|"),
                Itoa(cusd_amount),
                Bytes("|"),
                Itoa(confio_amount),
                Bytes("|"),
                Txn.sender()
            )),
            
            # Auto-end round at cap
            If(App.globalGet(round_cusd_raised) >= App.globalGet(round_cusd_cap),
                Seq([
                    App.globalPut(round_active, Int(0)),
                    Log(Concat(
                        Bytes("ADMIN|ROUND_ENDED_AT_CAP|"),
                        Itoa(App.globalGet(current_round))
                    ))
                ])
            ),
            
            Int(1)
        ])
    
    # Claim tokens (sponsor-preferred with self-funded fallback)
    @Subroutine(TealType.uint64)
    def claim_tokens():
        # Determine beneficiary based on path
        # Note: accounts[0] = sender, accounts[1] = first foreign account from caller
        beneficiary = If(
            Global.group_size() == Int(2),
            Txn.accounts[1],  # Sponsored path: beneficiary in accounts array
            Txn.sender()       # Self-funded fallback: sender is beneficiary
        )
        
        return Seq([
            # Contract must not be paused
            Assert(App.globalGet(contract_paused) == Int(0)),
            # Tokens must be unlocked
            Assert(App.globalGet(tokens_locked) == Int(0)),
            
            # Two paths: sponsored (preferred) or self-funded (resilience fallback)
            If(Global.group_size() == Int(2),
                # Sponsored path (sponsor pays all fees)
                Seq([
                    # Sender must be sponsor
                    Assert(Txn.sender() == App.globalGet(sponsor_address)),
                    Assert(Txn.group_index() == Int(1)),
                    
                    # Ensure beneficiary is specified (not zero address)
                    Assert(Txn.accounts[1] != Global.zero_address()),
                    
                    # Verify user's signature witness (0-ALGO self-payment)
                    Assert(Gtxn[0].type_enum() == TxnType.Payment),
                    Assert(Gtxn[0].sender() == beneficiary),
                    Assert(Gtxn[0].receiver() == beneficiary),
                    Assert(Gtxn[0].amount() == Int(0)),
                    Assert(Gtxn[0].rekey_to() == Global.zero_address()),
                    Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
                    Assert(Gtxn[0].fee() == Int(0)),  # User pays NO fees
                    
                    # Sponsor's app call carries fees with reasonable bounds
                    Assert(And(
                        Txn.fee() >= Global.min_txn_fee() * Int(2),  # At least app + 1 inner
                        Txn.fee() <= Global.min_txn_fee() * Int(5)   # Reasonable upper bound
                    )),
                ]),
                # Self-funded fallback (safety valve if sponsor disappears)
                Seq([
                    # Single transaction from beneficiary
                    Assert(Global.group_size() == Int(1)),
                    Assert(Txn.sender() == beneficiary),
                    
                    # User must pay fees for app call + inner transfer with reasonable bounds
                    Assert(And(
                        Txn.fee() >= Global.min_txn_fee() * Int(2),  # At least app + 1 inner
                        Txn.fee() <= Global.min_txn_fee() * Int(5)   # Reasonable upper bound
                    )),
                ])
            ),
            
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Beneficiary must be opted into the app
            Assert(App.optedIn(beneficiary, Global.current_application_id())),
            
            # Calculate claimable amount for beneficiary
            (total_purchased := App.localGet(beneficiary, user_total_confio)),
            (already_claimed := App.localGet(beneficiary, user_claimed)),
            (claimable := total_purchased - already_claimed),
            
            # Must have tokens to claim
            Assert(claimable > Int(0)),
            
            # Check beneficiary is opted into CONFIO
            (user_balance := AssetHolding.balance(beneficiary, App.globalGet(confio_asset_id))),
            Assert(user_balance.hasValue()),  # Must be opted in
            
            # Transfer CONFIO to beneficiary
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: beneficiary,
                TxnField.asset_amount: claimable,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update claimed amounts
            App.localPut(beneficiary, user_claimed, total_purchased),
            App.globalPut(total_confio_claimed,
                App.globalGet(total_confio_claimed) + claimable
            ),
            
            # Log claim for indexing
            Log(Concat(
                Bytes("CLAIM|"),
                Itoa(claimable),
                Bytes("|"),
                beneficiary
            )),
            
            Int(1)
        ])
    
    # Update round parameters (admin only)
    @Subroutine(TealType.uint64)
    def update_parameters():
        param_type = Txn.application_args[1]
        new_value = Btoi(Txn.application_args[2])
        
        return Seq([
            # Verify arguments
            Assert(Txn.application_args.length() >= Int(3)),
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            # Reject unknown parameter types
            Assert(Or(
                param_type == Bytes("price"),
                param_type == Bytes("cap"),
                param_type == Bytes("min"),
                param_type == Bytes("max")
            )),
            
            # Update based on parameter type
            If(param_type == Bytes("price"),
                Seq([
                    Assert(new_value > Int(0)),
                    # Check inventory for remaining round at new price
                    (remaining_cusd := App.globalGet(round_cusd_cap) - App.globalGet(round_cusd_raised)),
                    (confio_needed_rem := WideRatio([remaining_cusd, CONFIO_DECIMALS], [new_value])),
                    (confio_balance := AssetHolding.balance(
                        Global.current_application_address(), 
                        App.globalGet(confio_asset_id)
                    )),
                    Assert(confio_balance.hasValue()),
                    (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
                    Assert(confio_balance.value() >= outstanding + confio_needed_rem),
                    App.globalPut(cusd_per_confio, new_value)
                ])
            ).ElseIf(param_type == Bytes("cap"),
                Seq([
                    Assert(new_value >= App.globalGet(round_cusd_raised)),
                    # Check inventory for new cap at current price
                    (remaining_cusd := new_value - App.globalGet(round_cusd_raised)),
                    (confio_needed_rem := WideRatio([remaining_cusd, CONFIO_DECIMALS], [App.globalGet(cusd_per_confio)])),
                    (confio_balance := AssetHolding.balance(
                        Global.current_application_address(),
                        App.globalGet(confio_asset_id)
                    )),
                    Assert(confio_balance.hasValue()),
                    (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
                    Assert(confio_balance.value() >= outstanding + confio_needed_rem),
                    App.globalPut(round_cusd_cap, new_value)
                ])
            ).ElseIf(param_type == Bytes("min"),
                Seq([
                    Assert(new_value > Int(0)),
                    Assert(new_value <= App.globalGet(max_buy_cusd_per_address)),
                    # Ensure min doesn't exceed round cap (if active)
                    If(App.globalGet(round_cusd_cap) > Int(0),
                        Assert(new_value <= App.globalGet(round_cusd_cap))),
                    App.globalPut(min_buy_cusd, new_value)
                ])
            ).ElseIf(param_type == Bytes("max"),
                Seq([
                    Assert(new_value > Int(0)),
                    Assert(new_value >= App.globalGet(min_buy_cusd)),
                    # Ensure max doesn't exceed round cap (if active)
                    If(App.globalGet(round_cusd_cap) > Int(0),
                        Assert(new_value <= App.globalGet(round_cusd_cap))),
                    App.globalPut(max_buy_cusd_per_address, new_value)
                ])
            ),
            
            Int(1)
        ])
    
    # Permanent unlock (admin only, irreversible)
    @Subroutine(TealType.uint64)
    def permanent_unlock():
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # This action is irreversible
            Assert(App.globalGet(tokens_locked) == Int(1)),
            
            # Permanently unlock tokens
            App.globalPut(tokens_locked, Int(0)),
            App.globalPut(unlock_time, Global.latest_timestamp()),
            
            Log(Concat(
                Bytes("ADMIN|UNLOCK|PERMANENT|"),
                Itoa(App.globalGet(current_round))
            )),
            
            Int(1)
        ])
    
    # Withdraw unused CONFIO (admin only)
    @Subroutine(TealType.uint64)
    def withdraw_confio():
        # Optional receiver address (defaults to admin)
        receiver = If(
            Txn.application_args.length() >= Int(2),
            Txn.application_args[1],  # Custom receiver provided
            App.globalGet(admin_address)  # Default to admin
        )
        
        # Optional amount (defaults to all available)
        requested = If(
            Txn.application_args.length() >= Int(3),
            Btoi(Txn.application_args[2]),
            Int(0)  # 0 means withdraw all available
        )
        
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Get current CONFIO balance
            (confio_balance := AssetHolding.balance(
                Global.current_application_address(),
                App.globalGet(confio_asset_id)
            )),
            Assert(confio_balance.hasValue()),
            
            # Calculate outstanding obligations
            (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
            
            # Defensive check to prevent underflow
            Assert(confio_balance.value() >= outstanding),
            
            # Available = balance - outstanding (safe after check)
            (available := confio_balance.value() - outstanding),
            Assert(available > Int(0)),
            
            # Determine amount to withdraw
            (withdraw_amount := If(
                And(requested > Int(0), requested <= available),
                requested,
                available  # Withdraw all available if 0 or too much requested
            )),
            
            # Ensure receiver is opted-in to CONFIO
            (receiver_bal := AssetHolding.balance(receiver, App.globalGet(confio_asset_id))),
            Assert(receiver_bal.hasValue()),
            
            # Withdraw CONFIO
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: receiver,
                TxnField.asset_amount: withdraw_amount,
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            Log(Concat(
                Bytes("ADMIN|WITHDRAW_CONFIO|"),
                Itoa(App.globalGet(current_round)),
                Bytes("|"),
                Itoa(withdraw_amount),
                Bytes("|"),
                receiver
            )),
            
            Int(1)
        ])
    
    # Withdraw cUSD (admin only)
    @Subroutine(TealType.uint64)
    def withdraw_cusd():
        # Optional receiver address (defaults to admin)
        receiver = If(
            Txn.application_args.length() >= Int(2),
            Txn.application_args[1],  # Custom receiver provided
            App.globalGet(admin_address)  # Default to admin
        )
        
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Get current cUSD balance
            (cusd_balance := AssetHolding.balance(
                Global.current_application_address(),
                App.globalGet(cusd_asset_id)
            )),
            Assert(cusd_balance.hasValue()),
            
            # Ensure receiver is opted-in to cUSD
            (receiver_bal := AssetHolding.balance(receiver, App.globalGet(cusd_asset_id))),
            Assert(receiver_bal.hasValue()),
            
            # Withdraw all cUSD
            If(cusd_balance.value() > Int(0),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                        TxnField.asset_receiver: receiver,
                        TxnField.asset_amount: cusd_balance.value(),
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit(),
                    
                    Log(Concat(
                        Bytes("ADMIN|WITHDRAW_CUSD|"),
                        Itoa(App.globalGet(current_round)),
                        Bytes("|"),
                        Itoa(cusd_balance.value()), 
                        Bytes("|"),
                        receiver
                    ))
                ])
            ),
            
            Int(1)
        ])
    
    # Toggle round active state (admin only)
    @Subroutine(TealType.uint64)
    def toggle_round():
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Toggle round state
            If(App.globalGet(round_active) == Int(1),
                Seq([
                    App.globalPut(round_active, Int(0)),
                    Log(Concat(
                        Bytes("ADMIN|TOGGLE|"),
                        Itoa(App.globalGet(current_round)),
                        Bytes("|0")  # 0 = paused
                    ))
                ]),
                Seq([
                    # Cannot activate round while contract is paused
                    Assert(App.globalGet(contract_paused) == Int(0)),
                    
                    # Check inventory before re-activating
                    # Calculate remaining cUSD to raise
                    (remaining_cusd := App.globalGet(round_cusd_cap) - App.globalGet(round_cusd_raised)),
                    
                    # Calculate CONFIO needed for remaining cap
                    (confio_needed := WideRatio([remaining_cusd, CONFIO_DECIMALS], [App.globalGet(cusd_per_confio)])),
                    
                    # Check contract has enough CONFIO
                    (confio_balance := AssetHolding.balance(
                        Global.current_application_address(),
                        App.globalGet(confio_asset_id)
                    )),
                    Assert(confio_balance.hasValue()),
                    
                    # Calculate outstanding obligations
                    (outstanding := App.globalGet(total_confio_sold) - App.globalGet(total_confio_claimed)),
                    
                    # Ensure we have enough for outstanding + remaining round
                    Assert(confio_balance.value() >= outstanding + confio_needed),
                    
                    App.globalPut(round_active, Int(1)),
                    Log(Concat(
                        Bytes("ADMIN|TOGGLE|"),
                        Itoa(App.globalGet(current_round)),
                        Bytes("|1")  # 1 = active
                    ))
                ])
            ),
            
            Int(1)
        ])
    
    
    # Update sponsor address (admin only)
    @Subroutine(TealType.uint64)
    def update_sponsor():
        new_sponsor = Txn.application_args[1]
        old = ScratchVar(TealType.bytes)
        
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # Validate new sponsor address
            Assert(Len(new_sponsor) == Int(32)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Store old sponsor before updating
            old.store(App.globalGet(sponsor_address)),
            
            # Update sponsor
            App.globalPut(sponsor_address, new_sponsor),
            
            # Log the change (both old and new for audit trail)
            Log(Concat(
                Bytes("ADMIN|UPDATE_SPONSOR|"),
                old.load(),  # Old sponsor (stored before update)
                Bytes("|"),
                new_sponsor  # New sponsor
            )),
            
            Int(1)
        ])
    
    # Emergency pause (admin only)
    @Subroutine(TealType.uint64)
    def emergency_pause():
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Toggle pause state and log
            If(App.globalGet(contract_paused) == Int(0),
                Seq([
                    App.globalPut(contract_paused, Int(1)),
                    Log(Bytes("ADMIN|PAUSE|1"))  # 1 = paused
                ]),
                Seq([
                    App.globalPut(contract_paused, Int(0)),
                    Log(Bytes("ADMIN|PAUSE|0"))  # 0 = unpaused
                ])
            ),
            
            Int(1)
        ])
    
    # Opt contract into assets (sponsor-funded, uses inner transactions)
    @Subroutine(TealType.uint64)
    def opt_in_assets():
        return Seq([
            # Admin only
            Assert(Txn.sender() == App.globalGet(admin_address)),
            
            # Group structure:
            # G0: Payment from sponsor for fees
            # G1: This app call
            Assert(Global.group_size() == Int(2)),
            Assert(Txn.group_index() == Int(1)),
            
            # Verify sponsor payment (strict validation)
            Assert(Gtxn[0].type_enum() == TxnType.Payment),
            Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].receiver() == App.globalGet(sponsor_address)),
            Assert(Gtxn[0].amount() == Int(0)),
            Assert(Gtxn[0].rekey_to() == Global.zero_address()),
            Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
            
            # Sponsor must cover group fees with reasonable bounds
            Assert(And(
                Gtxn[0].fee() >= Global.min_txn_fee() * Int(2),  # At least cover both outer txns
                Gtxn[0].fee() <= Global.min_txn_fee() * Int(5)   # Reasonable upper bound
            )),
            # App call must carry fees for itself + 2 inner opt-ins with bounds
            Assert(And(
                Txn.fee() >= Global.min_txn_fee() * Int(3),  # At least app + 2 inners
                Txn.fee() <= Global.min_txn_fee() * Int(6)   # Reasonable upper bound
            )),
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # CONFIO opt-in (inner transaction)
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(confio_asset_id),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # cUSD opt-in (inner transaction)
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(cusd_asset_id),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            Int(1)
        ])
    
    # Get user info (read-only)
    @Subroutine(TealType.uint64)
    def get_user_info():
        return Seq([
            # Log user's purchase info
            Log(Itoa(App.localGet(Txn.sender(), user_total_confio))),
            Log(Itoa(App.localGet(Txn.sender(), user_total_cusd))),
            Log(Itoa(App.localGet(Txn.sender(), user_claimed))),
            Log(Itoa(App.localGet(Txn.sender(), user_round_cusd))),
            
            Int(1)
        ])
    
    # Opt-in (with or without sponsor support)
    @Subroutine(TealType.uint64)
    def opt_in():
        return Seq([
            # No rekeying allowed
            Assert(Txn.rekey_to() == Global.zero_address()),
            
            # Two paths: sponsored or self-funded
            If(Global.group_size() == Int(2),
                # Sponsored opt-in path
                Seq([
                    Assert(Txn.group_index() == Int(1)),
                    # Verify sponsor payment (strict validation)
                    Assert(Gtxn[0].type_enum() == TxnType.Payment),
                    Assert(Gtxn[0].sender() == App.globalGet(sponsor_address)),
                    Assert(Gtxn[0].receiver() == App.globalGet(sponsor_address)),
                    Assert(Gtxn[0].amount() == Int(0)),
                    Assert(Gtxn[0].rekey_to() == Global.zero_address()),
                    Assert(Gtxn[0].close_remainder_to() == Global.zero_address()),
                    # Sponsor must cover both txns in group
                    Assert(Gtxn[0].fee() >= Global.min_txn_fee() * Int(2)),
                    # App call (opt-in) pays ZERO fees (strict sponsor-only)
                    Assert(Txn.fee() == Int(0)),
                ]),
                # Self-funded opt-in path (fallback if sponsor unavailable)
                Seq([
                    Assert(Global.group_size() == Int(1)),
                    # User must pay their own fee
                    Assert(Txn.fee() >= Global.min_txn_fee()),
                ])
            ),
            
            # Accept opt-in
            Int(1)
        ])
    
    # Main router
    program = Cond(
        # Creation
        [Txn.application_id() == Int(0), initialize()],
        
        # Opt-in (users with sponsor support)
        [Txn.on_completion() == OnComplete.OptIn, opt_in()],
        
        # Explicitly block updates and deletes
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        
        # NoOp calls
        [And(Txn.on_completion() == OnComplete.NoOp, Txn.application_args.length() == Int(0)), Int(0)],
        [And(Txn.on_completion() == OnComplete.NoOp, Txn.application_args.length() > Int(0)),
         Cond(
             [Txn.application_args[0] == Bytes("opt_in_assets"), opt_in_assets()],
             [Txn.application_args[0] == Bytes("start_round"), start_round()],
             [Txn.application_args[0] == Bytes("toggle_round"), toggle_round()],
             [Txn.application_args[0] == Bytes("update"), update_parameters()],
             [Txn.application_args[0] == Bytes("buy"), buy_tokens()],
             [Txn.application_args[0] == Bytes("claim"), claim_tokens()],
             [Txn.application_args[0] == Bytes("unlock"), permanent_unlock()],
             [Txn.application_args[0] == Bytes("withdraw"), withdraw_cusd()],
             [Txn.application_args[0] == Bytes("withdraw_confio"), withdraw_confio()],
             [Txn.application_args[0] == Bytes("update_sponsor"), update_sponsor()],
             [Txn.application_args[0] == Bytes("pause"), emergency_pause()],
             [Txn.application_args[0] == Bytes("info"), get_user_info()],
         )],
        
        # CloseOut only if nothing unclaimed
        [Txn.on_completion() == OnComplete.CloseOut,
         Seq([
             Assert(
                 App.localGet(Txn.sender(), user_total_confio) ==
                 App.localGet(Txn.sender(), user_claimed)
             ),
             Int(1)
         ])],
        
        # Reject everything else
        [Int(1), Int(0)]
    )
    
    return program

def compile_presale():
    """Compile the presale contract"""
    program = confio_presale()
    return compileTeal(program, Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_presale())
    print("\n# CONFIO Presale Contract")
    print("# Features:")
    print("# - SPONSOR-ONLY MODEL (users NEVER need ALGO, custom wallet)")
    print("# - cUSD-based caps and pricing")
    print("# - Price: cUSD per CONFIO (6 decimals)")
    print("# - Per-round cUSD caps and per-address limits")
    print("# - Lock/unlock mechanism for token distribution")
    print("# - Update functions: price, cap, min, max")
    print("\n# Key Names:")
    print("# - price: cUSD per CONFIO (6d)")
    print("# - cusd_cap: Max cUSD to raise per round (6d)")  
    print("# - cusd_raised: cUSD raised in current round (6d)")
    print("# - confio_sold: Total CONFIO sold (6d)")
    print("# - max_addr: Max cUSD per address per round (6d)")
    print("\n# Example Rounds:")
    print("# Round 1: 0.25 cUSD/CONFIO (1M cUSD goal)")
    print("# Round 2: 0.50 cUSD/CONFIO (10M cUSD goal)")
    print("# Round 3: 1.00 cUSD/CONFIO (TBD goal)")
