module confio::cusd {
    use std::option;
    use sui::coin;
    use sui::object;
    use sui::tx_context;
    use sui::transfer;
    use sui::url;
    use std::ascii::string;

    /// Error codes
    const ENotEnoughBalance: u64 = 0;

    /// The cUSD coin type (Confío Dollar). One-time witness.
    public struct CUSD has drop {}

    /// Minting authority for USDC vaults
    public struct USDCVaultMintAuthority has key, store {
        id: object::UID
    }

    /// Minting authority for Treasury vaults
    public struct TreasuryVaultMintAuthority has key, store {
        id: object::UID
    }

    /// Initialize Confío Dollar (cUSD)
    fun init(witness: CUSD, ctx: &mut TxContext) {
        let (mut treasury_cap, metadata) = coin::create_currency(
            witness,
            6, // decimals
            b"CUSD",
            b"Conf\xC3\xADo Dollar",
            b"A USD-pegged stablecoin for Conf\xC3\xADo app",
            option::some(
                url::new_unsafe(
                    string(
                        b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CUSD.png"
                    )
                )
            ),
            ctx
        );
        transfer::public_freeze_object(metadata);
        transfer::public_transfer(treasury_cap, tx_context::sender(ctx));
    }

    /// Mint cUSD using USDC vault authority
    public fun mint_with_usdc_vault(
        treasury_cap: &mut coin::TreasuryCap<CUSD>,
        _authority: &USDCVaultMintAuthority,
        amount: u64,
        ctx: &mut TxContext
    ): coin::Coin<CUSD> {
        coin::mint(treasury_cap, amount, ctx)
    }

    /// Burn cUSD using USDC vault authority
    public fun burn_with_usdc_vault(
        treasury_cap: &mut coin::TreasuryCap<CUSD>,
        _authority: &USDCVaultMintAuthority,
        coin: coin::Coin<CUSD>
    ): u64 {
        coin::burn(treasury_cap, coin)
    }

    /// Mint cUSD using Treasury vault authority
    public fun mint_with_treasury_vault(
        treasury_cap: &mut coin::TreasuryCap<CUSD>,
        _authority: &TreasuryVaultMintAuthority,
        amount: u64,
        ctx: &mut TxContext
    ): coin::Coin<CUSD> {
        coin::mint(treasury_cap, amount, ctx)
    }

    /// Burn cUSD using Treasury vault authority
    public fun burn_with_treasury_vault(
        treasury_cap: &mut coin::TreasuryCap<CUSD>,
        _authority: &TreasuryVaultMintAuthority,
        coin: coin::Coin<CUSD>
    ): u64 {
        coin::burn(treasury_cap, coin)
    }

    /// Transfer cUSD
    public entry fun transfer(
        coin: &mut coin::Coin<CUSD>,
        amount: u64,
        recipient: address,
        ctx: &mut TxContext
    ) {
        assert!(coin::value(coin) >= amount, ENotEnoughBalance);
        let split_coin = coin::split(coin, amount, ctx);
        transfer::public_transfer(split_coin, recipient);
    }

    /// Split cUSD
    public fun split(
        coin: &mut coin::Coin<CUSD>,
        amount: u64,
        ctx: &mut TxContext
    ): coin::Coin<CUSD> {
        coin::split(coin, amount, ctx)
    }
}