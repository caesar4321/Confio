module confio::cusd_vault_treasury {
    use sui::coin::{Self, Coin, TreasuryCap};
    use sui::tx_context::{Self, TxContext};
    use sui::clock::{Self, Clock};
    use sui::event;
    use confio::cusd::{Self, CUSD, TreasuryVaultMintAuthority};

    /// Event emitted when cUSD is minted from the treasury
    public struct MintEvent has copy, drop {
        amount: u64,
        timestamp_ms: u64,
    }

    /// Event emitted when cUSD is burned back to the treasury
    public struct BurnEvent has copy, drop {
        amount: u64,
        timestamp_ms: u64,
    }

    /// Mint new cUSD tokens from the treasury
    public fun mint_from_treasury(
        treasury_cap: &mut TreasuryCap<CUSD>,
        authority: &TreasuryVaultMintAuthority,
        amount: u64,
        clock: &Clock,
        ctx: &mut TxContext
    ): Coin<CUSD> {
        // Emit the mint event
        event::emit(MintEvent {
            amount,
            timestamp_ms: clock::timestamp_ms(clock),
        });

        // Delegate to cUSD module
        cusd::mint_with_treasury_vault(treasury_cap, authority, amount, ctx)
    }

    /// Burn cUSD tokens and return value to the treasury
    public fun burn_for_treasury(
        treasury_cap: &mut TreasuryCap<CUSD>,
        authority: &TreasuryVaultMintAuthority,
        cusd_coin: Coin<CUSD>,
        clock: &Clock,
        ctx: &mut TxContext
    ): u64 {
        // Capture the amount before burning
        let amount = coin::value(&cusd_coin);

        // Emit the burn event
        event::emit(BurnEvent {
            amount,
            timestamp_ms: clock::timestamp_ms(clock),
        });

        // Delegate to cUSD module
        cusd::burn_with_treasury_vault(treasury_cap, authority, cusd_coin)
    }
}
