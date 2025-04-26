module confio::confio {
    use sui::coin;
    use sui::transfer;
    use sui::tx_context::{Self, TxContext};
    use std::option;
    use sui::url;
    use std::ascii::string;

    /// One-time witness type
    public struct CONFIO has drop {}

    /// Create a new CONFIO coin with a fixed supply
    fun init(witness: CONFIO, ctx: &mut TxContext) {
        // Create currency with accent in the name and description
        let (mut treasury_cap, metadata) = coin::create_currency(
            witness,
            6,                                // decimals
            b"CONFIO",                      // ASCII symbol
            b"Conf\xC3\xADo",             // "Confío" with UTF-8 escape
            b"Utility and governance coin for the Conf\xC3\xADo app", // description with accent
            option::some(
                url::new_unsafe(
                    string(
                        b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png"
                    )
                )
            ),
            ctx
        );

        // Mint fixed supply
        let supply = 1_000_000_000; // 1 billion CONFIO
        let coins = coin::mint(&mut treasury_cap, supply, ctx);
        transfer::public_transfer(coins, tx_context::sender(ctx));

        // Freeze metadata and treasury cap
        transfer::public_freeze_object(metadata);
        transfer::public_freeze_object(treasury_cap);
    }
}
