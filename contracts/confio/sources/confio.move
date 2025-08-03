module confio::confio {
    use sui::coin;
    use sui::url;

    public struct CONFIO has drop {}

    fun init(witness: CONFIO, ctx: &mut TxContext) {
        let (mut treasury_cap, metadata) = coin::create_currency(
            witness, 6, b"CONFIO", b"Confío", b"Utility and governance coin for the Confío app", option::some(url::new_unsafe_from_bytes(b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png")), ctx
        );
        let supply = 1_000_000_000_000_000; // 1 billion CONFIO with 6 decimals (1B * 10^6)
        let coins = coin::mint(&mut treasury_cap, supply, ctx);
        transfer::public_transfer(coins, tx_context::sender(ctx));
        transfer::public_freeze_object(metadata);
        transfer::public_freeze_object(treasury_cap);
    }
}