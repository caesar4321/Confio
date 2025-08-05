module cusd::cusd {
    use aptos_framework::fungible_asset::{Self, MintRef, TransferRef, BurnRef, Metadata, FungibleAsset};
    use aptos_framework::object::{Self, Object};
    use aptos_framework::primary_fungible_store;
    use aptos_framework::signer;
    use aptos_framework::event;
    use std::error;
    use std::signer::address_of;
    use std::string::utf8;
    use std::option;
    use std::vector;

    // Error codes
    const E_NOT_ADMIN: u64 = 1;
    const E_SYSTEM_PAUSED: u64 = 2;
    const E_ADDRESS_FROZEN: u64 = 3;
    const E_NOT_VAULT: u64 = 4;

    #[resource_group_member(group = aptos_framework::object::ObjectGroup)]
    struct AdminConfig has key {
        admin: address,
        is_paused: bool,
        frozen_addresses: vector<address>,
        vault_addresses: vector<address>,
    }

    #[resource_group_member(group = aptos_framework::object::ObjectGroup)]
    struct ManagedFungibleAsset has key {
        mint_ref: MintRef,
        transfer_ref: TransferRef,
        burn_ref: BurnRef,
    }

    #[event]
    struct CUSDMinted has drop, store {
        amount: u64,
        recipient: address,
        deposit_address: address,
    }

    #[event]
    struct CUSDBurned has drop, store {
        amount: u64,
        deposit_address: address,
    }

    #[event]
    struct AddressFrozen has drop, store {
        address: address,
    }

    #[event]
    struct AddressUnfrozen has drop, store {
        address: address,
    }

    #[event]
    struct SystemPaused has drop, store {}

    #[event]
    struct SystemUnpaused has drop, store {}

    /// Initialize the cUSD fungible asset
    fun init_module(admin: &signer) {
        let constructor_ref = object::create_named_object(admin, b"CUSD");
        
        primary_fungible_store::create_primary_store_enabled_fungible_asset(
            &constructor_ref,
            option::none(),
            utf8(b"Conf\xc3\xado Dollar"),
            utf8(b"CUSD"),
            6,
            utf8(b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/cUSD.png"),
            utf8(b"https://confio.lat"),
        );

        // Create mint, burn, and transfer refs
        let mint_ref = fungible_asset::generate_mint_ref(&constructor_ref);
        let burn_ref = fungible_asset::generate_burn_ref(&constructor_ref);
        let transfer_ref = fungible_asset::generate_transfer_ref(&constructor_ref);
        let metadata_object_signer = object::generate_signer(&constructor_ref);

        move_to(
            &metadata_object_signer,
            ManagedFungibleAsset { mint_ref, transfer_ref, burn_ref }
        );

        // Initialize admin config
        move_to(admin, AdminConfig {
            admin: address_of(admin),
            is_paused: false,
            frozen_addresses: vector::empty(),
            vault_addresses: vector::empty(),
        });
    }

    #[view]
    public fun get_metadata(): Object<Metadata> {
        let asset_address = object::create_object_address(&@cusd, b"CUSD");
        object::address_to_object<Metadata>(asset_address)
    }

    /// Mint new cUSD tokens
    public entry fun mint_and_transfer(
        admin: &signer,
        amount: u64,
        deposit_address: address,
        recipient: address,
    ) acquires AdminConfig, ManagedFungibleAsset {
        let admin_config = borrow_global<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        assert!(!vector::contains(&admin_config.frozen_addresses, &recipient), error::invalid_state(E_ADDRESS_FROZEN));

        let asset = get_metadata();
        let managed_fungible_asset = borrow_global<ManagedFungibleAsset>(object::object_address(&asset));
        let fa = fungible_asset::mint(&managed_fungible_asset.mint_ref, amount);
        primary_fungible_store::deposit(recipient, fa);

        event::emit(CUSDMinted {
            amount,
            recipient,
            deposit_address,
        });
    }

    /// Burn cUSD tokens
    public entry fun burn(
        user: &signer,
        amount: u64,
        vault_address: address,
    ) acquires AdminConfig, ManagedFungibleAsset {
        let admin_config = borrow_global<AdminConfig>(@cusd);
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        assert!(vector::contains(&admin_config.vault_addresses, &vault_address), error::invalid_argument(E_NOT_VAULT));
        
        let user_address = address_of(user);
        assert!(!vector::contains(&admin_config.frozen_addresses, &user_address), error::invalid_state(E_ADDRESS_FROZEN));

        let asset = get_metadata();
        let managed_fungible_asset = borrow_global<ManagedFungibleAsset>(object::object_address(&asset));
        let fa = primary_fungible_store::withdraw(user, asset, amount);
        fungible_asset::burn(&managed_fungible_asset.burn_ref, fa);

        event::emit(CUSDBurned {
            amount,
            deposit_address: vault_address,
        });
    }

    /// Transfer cUSD tokens with freeze checks
    public entry fun transfer_cusd(
        sender: &signer,
        recipient: address,
        amount: u64,
    ) acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@cusd);
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        
        let sender_address = address_of(sender);
        assert!(!vector::contains(&admin_config.frozen_addresses, &sender_address), error::invalid_state(E_ADDRESS_FROZEN));
        assert!(!vector::contains(&admin_config.frozen_addresses, &recipient), error::invalid_state(E_ADDRESS_FROZEN));

        let asset = get_metadata();
        primary_fungible_store::transfer(sender, asset, recipient, amount);
    }

    /// Admin functions
    public entry fun pause(admin: &signer) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        admin_config.is_paused = true;
        event::emit(SystemPaused {});
    }

    public entry fun unpause(admin: &signer) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        admin_config.is_paused = false;
        event::emit(SystemUnpaused {});
    }

    public entry fun add_vault(admin: &signer, vault: address) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        vector::push_back(&mut admin_config.vault_addresses, vault);
    }

    public entry fun remove_vault(admin: &signer, vault: address) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        let (found, index) = vector::index_of(&admin_config.vault_addresses, &vault);
        if (found) {
            vector::remove(&mut admin_config.vault_addresses, index);
        };
    }

    public entry fun freeze_address(admin: &signer, address_to_freeze: address) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        vector::push_back(&mut admin_config.frozen_addresses, address_to_freeze);
        event::emit(AddressFrozen { address: address_to_freeze });
    }

    public entry fun unfreeze_address(admin: &signer, address_to_unfreeze: address) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@cusd);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        let (found, index) = vector::index_of(&admin_config.frozen_addresses, &address_to_unfreeze);
        if (found) {
            vector::remove(&mut admin_config.frozen_addresses, index);
        };
        event::emit(AddressUnfrozen { address: address_to_unfreeze });
    }
}