module confio::confio {
    use aptos_framework::fungible_asset::{Self, MintRef, TransferRef, BurnRef, Metadata, FungibleAsset};
    use aptos_framework::object::{Self, Object};
    use aptos_framework::primary_fungible_store;
    use aptos_framework::signer::address_of;
    use std::string::utf8;
    use std::option;

    #[resource_group_member(group = aptos_framework::object::ObjectGroup)]
    struct ManagedFungibleAsset has key {
        mint_ref: MintRef,
        transfer_ref: TransferRef,
        burn_ref: BurnRef,
    }

    /// Initialize the CONFIO fungible asset with fixed supply
    fun init_module(admin: &signer) {
        let constructor_ref = object::create_named_object(admin, b"CONFIO");
        
        primary_fungible_store::create_primary_store_enabled_fungible_asset(
            &constructor_ref,
            option::none(),
            utf8(b"Conf\xc3\xado"),
            utf8(b"CONFIO"),
            6,
            utf8(b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CONFIO.png"),
            utf8(b"https://confio.lat"),
        );

        // Create mint, burn, and transfer refs
        let mint_ref = fungible_asset::generate_mint_ref(&constructor_ref);
        let burn_ref = fungible_asset::generate_burn_ref(&constructor_ref);
        let transfer_ref = fungible_asset::generate_transfer_ref(&constructor_ref);
        let metadata_object_signer = object::generate_signer(&constructor_ref);

        // Mint the total supply (1 billion CONFIO with 6 decimals)
        let supply = 1_000_000_000_000_000; // 1B * 10^6
        let initial_supply = fungible_asset::mint(&mint_ref, supply);
        
        // Transfer all tokens to the admin
        primary_fungible_store::deposit(address_of(admin), initial_supply);

        // Store the refs (they're frozen after init, so they can't be used again)
        move_to(
            &metadata_object_signer,
            ManagedFungibleAsset { mint_ref, transfer_ref, burn_ref }
        );
    }

    #[view]
    public fun get_metadata(): Object<Metadata> {
        let asset_address = object::create_object_address(&@confio, b"CONFIO");
        object::address_to_object<Metadata>(asset_address)
    }

    /// Transfer CONFIO tokens
    public entry fun transfer_confio(
        sender: &signer,
        recipient: address,
        amount: u64,
    ) {
        let asset = get_metadata();
        primary_fungible_store::transfer(sender, asset, recipient, amount);
    }
}