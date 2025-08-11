#!/usr/bin/env python3
"""
P2P Escrow Contract for Algorand
Each trade gets its own escrow instance for isolation and security.
"""

from pyteal import *
from algosdk import encoding
from typing import Tuple

# Trade states
TRADE_CREATED = Int(1)
TRADE_FUNDED = Int(2)
TRADE_COMPLETED = Int(3)
TRADE_CANCELLED = Int(4)

def p2p_escrow_contract():
    """
    Per-trade escrow contract.
    Handles a single P2P trade between two parties.
    """
    
    # Global state schema: 10 ints, 4 bytes
    # Local state schema: 0 ints, 0 bytes (not used)
    
    # Global state keys
    seller_address = Bytes("seller")
    buyer_address = Bytes("buyer")
    seller_asset = Bytes("s_asset")  # Asset seller is selling
    buyer_asset = Bytes("b_asset")   # Asset buyer is providing
    seller_amount = Bytes("s_amt")   # Amount seller is selling
    buyer_amount = Bytes("b_amt")    # Amount buyer must provide
    trade_state = Bytes("state")
    creation_time = Bytes("created")
    expiry_time = Bytes("expiry")
    seller_funded = Bytes("s_funded")
    buyer_funded = Bytes("b_funded")
    
    # Initialize trade
    @Subroutine(TealType.uint64)
    def initialize_trade():
        return Seq([
            # Verify we have 6 arguments
            Assert(Txn.application_args.length() == Int(6)),
            
            # Store trade parameters
            App.globalPut(seller_address, Txn.application_args[0]),
            App.globalPut(buyer_address, Txn.application_args[1]),
            App.globalPut(seller_asset, Btoi(Txn.application_args[2])),
            App.globalPut(buyer_asset, Btoi(Txn.application_args[3])),
            App.globalPut(seller_amount, Btoi(Txn.application_args[4])),
            App.globalPut(buyer_amount, Btoi(Txn.application_args[5])),
            
            # Set initial state
            App.globalPut(trade_state, TRADE_CREATED),
            App.globalPut(creation_time, Global.latest_timestamp()),
            App.globalPut(expiry_time, Global.latest_timestamp() + Int(86400)),  # 24 hour expiry
            App.globalPut(seller_funded, Int(0)),
            App.globalPut(buyer_funded, Int(0)),
            
            Int(1)
        ])
    
    # Opt-in to assets
    @Subroutine(TealType.uint64)
    def opt_in_assets():
        return Seq([
            # Must be called by contract creator
            Assert(Txn.sender() == Global.creator_address()),
            
            # Must be in a group with 2 opt-in transactions
            Assert(Global.group_size() == Int(3)),
            
            # Verify opt-in transactions
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].asset_amount() == Int(0)),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(seller_asset)),
            
            Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[2].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[2].asset_amount() == Int(0)),
            Assert(Gtxn[2].xfer_asset() == App.globalGet(buyer_asset)),
            
            Int(1)
        ])
    
    # Deposit funds (seller or buyer)
    @Subroutine(TealType.uint64)
    def deposit_funds():
        is_seller = Txn.sender() == App.globalGet(seller_address)
        is_buyer = Txn.sender() == App.globalGet(buyer_address)
        
        return Seq([
            # Must be seller or buyer
            Assert(Or(is_seller, is_buyer)),
            
            # Must be in a group with asset transfer
            Assert(Global.group_size() == Int(2)),
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            
            # Verify correct asset and amount
            If(is_seller,
                Seq([
                    Assert(Gtxn[1].xfer_asset() == App.globalGet(seller_asset)),
                    Assert(Gtxn[1].asset_amount() == App.globalGet(seller_amount)),
                    App.globalPut(seller_funded, Int(1))
                ]),
                Seq([
                    Assert(Gtxn[1].xfer_asset() == App.globalGet(buyer_asset)),
                    Assert(Gtxn[1].asset_amount() == App.globalGet(buyer_amount)),
                    App.globalPut(buyer_funded, Int(1))
                ])
            ),
            
            # Update state if both funded
            If(And(
                App.globalGet(seller_funded) == Int(1),
                App.globalGet(buyer_funded) == Int(1)
            ),
                App.globalPut(trade_state, TRADE_FUNDED)
            ),
            
            Int(1)
        ])
    
    # Complete trade (swap assets)
    @Subroutine(TealType.uint64)
    def complete_trade():
        return Seq([
            # Trade must be funded
            Assert(App.globalGet(trade_state) == TRADE_FUNDED),
            
            # Either party can complete
            Assert(Or(
                Txn.sender() == App.globalGet(seller_address),
                Txn.sender() == App.globalGet(buyer_address)
            )),
            
            # Must be in a group with 2 asset transfers
            Assert(Global.group_size() == Int(3)),
            
            # Transfer seller's asset to buyer
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(seller_asset),
                TxnField.asset_receiver: App.globalGet(buyer_address),
                TxnField.asset_amount: App.globalGet(seller_amount),
                TxnField.fee: Int(0)  # Fee paid by outer transaction
            }),
            InnerTxnBuilder.Submit(),
            
            # Transfer buyer's asset to seller
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(buyer_asset),
                TxnField.asset_receiver: App.globalGet(seller_address),
                TxnField.asset_amount: App.globalGet(buyer_amount),
                TxnField.fee: Int(0)
            }),
            InnerTxnBuilder.Submit(),
            
            # Update state
            App.globalPut(trade_state, TRADE_COMPLETED),
            
            Int(1)
        ])
    
    # Cancel trade (return funds)
    @Subroutine(TealType.uint64)
    def cancel_trade():
        return Seq([
            # Can cancel if not completed
            Assert(App.globalGet(trade_state) != TRADE_COMPLETED),
            
            # Either party can cancel after expiry
            Assert(Or(
                Txn.sender() == App.globalGet(seller_address),
                Txn.sender() == App.globalGet(buyer_address),
                Global.latest_timestamp() > App.globalGet(expiry_time)
            )),
            
            # Return seller's funds if deposited
            If(App.globalGet(seller_funded) == Int(1),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(seller_asset),
                        TxnField.asset_receiver: App.globalGet(seller_address),
                        TxnField.asset_amount: App.globalGet(seller_amount),
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Return buyer's funds if deposited
            If(App.globalGet(buyer_funded) == Int(1),
                Seq([
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(buyer_asset),
                        TxnField.asset_receiver: App.globalGet(buyer_address),
                        TxnField.asset_amount: App.globalGet(buyer_amount),
                        TxnField.fee: Int(0)
                    }),
                    InnerTxnBuilder.Submit()
                ])
            ),
            
            # Update state
            App.globalPut(trade_state, TRADE_CANCELLED),
            
            Int(1)
        ])
    
    # Close escrow (recover ALGO)
    @Subroutine(TealType.uint64)
    def close_escrow():
        return Seq([
            # Trade must be completed or cancelled
            Assert(Or(
                App.globalGet(trade_state) == TRADE_COMPLETED,
                App.globalGet(trade_state) == TRADE_CANCELLED
            )),
            
            # Only creator can close
            Assert(Txn.sender() == Global.creator_address()),
            
            # Opt out of assets to recover ALGO
            # This happens via DeleteApplication automatically
            
            Int(1)
        ])
    
    # Main router
    program = Cond(
        # Creation
        [Txn.application_id() == Int(0), initialize_trade()],
        
        # NoOp calls
        [Txn.on_completion() == OnComplete.NoOp,
         Cond(
             [Txn.application_args[0] == Bytes("opt_in"), opt_in_assets()],
             [Txn.application_args[0] == Bytes("deposit"), deposit_funds()],
             [Txn.application_args[0] == Bytes("complete"), complete_trade()],
             [Txn.application_args[0] == Bytes("cancel"), cancel_trade()],
         )],
        
        # Delete (close escrow)
        [Txn.on_completion() == OnComplete.DeleteApplication, close_escrow()],
        
        # Reject everything else
        [Int(1), Int(0)]
    )
    
    return program

def compile_p2p_escrow():
    """Compile the P2P escrow contract"""
    program = p2p_escrow_contract()
    return compileTeal(program, Mode.Application, version=8)

if __name__ == "__main__":
    print(compile_p2p_escrow())