module confio::cusd_vault_usdc {
    use sui::coin;
    use sui::transfer;
    use sui::tx_context::{Self, TxContext};
    use sui::object;
    use sui::event;
    use std::option;
    use confio::cusd::{Self, CUSD};

    /// Error codes
    const ENotAuthorized: u64 = 1;
    const EInsufficientBalance: u64 = 2;

    /// One-time witness for module initialization
    public struct CUSD_VAULT_USDC has drop {}

    /// The USDC currency type
    public struct USDC has drop {}

    /// The treasury cap for USDC
    public struct USDCTreasuryCap has key, store {
        id: object::UID,
        cap: coin::TreasuryCap<USDC>
    }

    /// The mint authority for USDC
    public struct USDCMintAuthority has key, store {
        id: object::UID
    }

    /// The USDC vault that holds treasury caps for both USDC and CUSD
    public struct USDCVault has key {
        id: object::UID,
        cusd_treasury_cap: coin::TreasuryCap<CUSD>,
        usdc_treasury_cap: USDCTreasuryCap
    }

    /// The mint authority for the USDC vault
    public struct USDCVaultMintAuthority has key, store {
        id: object::UID
    }

    /// Event emitted when USDC is locked and CUSD is minted
    public struct USDCLocked has copy, drop {
        amount: u64
    }

    /// Event emitted when CUSD is burned and USDC is redeemed
    public struct USDCRedeemed has copy, drop {
        amount: u64
    }

    /// Initialize the USDC currency
    fun init(_witness: CUSD_VAULT_USDC, ctx: &mut TxContext) {
        let (treasury_cap, metadata) = coin::create_currency(
            USDC {},
            6,  // decimals
            b"USDC",  // symbol
            b"USD Coin",  // name
            b"",  // description
            option::none(),  // icon_url
            ctx
        );

        // Transfer treasury cap to the sender
        transfer::transfer(USDCTreasuryCap {
            id: object::new(ctx),
            cap: treasury_cap
        }, tx_context::sender(ctx));

        // Transfer metadata to the sender
        transfer::public_transfer(metadata, tx_context::sender(ctx));
    }

    /// Create a new USDC treasury cap and mint authority
    public fun create_treasury_cap(
        witness: USDC,
        ctx: &mut TxContext
    ): (USDCTreasuryCap, USDCMintAuthority, coin::CoinMetadata<USDC>) {
        let (treasury_cap, metadata) = coin::create_currency(
            witness,
            6,  // decimals
            b"USDC",  // symbol
            b"USD Coin",  // name
            b"",  // description
            option::none(),  // icon_url
            ctx
        );

        let treasury_cap = USDCTreasuryCap {
            id: object::new(ctx),
            cap: treasury_cap
        };

        let mint_authority = USDCMintAuthority {
            id: object::new(ctx)
        };

        (treasury_cap, mint_authority, metadata)
    }

    /// Create a new USDC vault with treasury caps for both USDC and CUSD
    public fun create_vault(
        cusd_treasury_cap: coin::TreasuryCap<CUSD>,
        usdc_treasury_cap: USDCTreasuryCap,
        ctx: &mut TxContext
    ): (USDCVault, USDCVaultMintAuthority) {
        let vault = USDCVault {
            id: object::new(ctx),
            cusd_treasury_cap,
            usdc_treasury_cap
        };

        let mint_authority = USDCVaultMintAuthority {
            id: object::new(ctx)
        };

        (vault, mint_authority)
    }

    /// Lock USDC and mint CUSD
    public fun lock_and_mint(
        vault: &mut USDCVault,
        usdc_coins: coin::Coin<USDC>,
        ctx: &mut TxContext
    ): coin::Coin<CUSD> {
        let amount = coin::value(&usdc_coins);
        coin::burn(&mut vault.usdc_treasury_cap.cap, usdc_coins);
        event::emit(USDCLocked { amount });

        let cusd_coins = coin::mint(&mut vault.cusd_treasury_cap, amount, ctx);
        cusd_coins
    }

    /// Burn CUSD and redeem USDC
    public fun burn_and_redeem(
        vault: &mut USDCVault,
        cusd_coins: coin::Coin<CUSD>,
        ctx: &mut TxContext
    ): coin::Coin<USDC> {
        let amount = coin::value(&cusd_coins);
        coin::burn(&mut vault.cusd_treasury_cap, cusd_coins);

        let usdc_coins = coin::mint(&mut vault.usdc_treasury_cap.cap, amount, ctx);
        event::emit(USDCRedeemed { amount });
        usdc_coins
    }
}
