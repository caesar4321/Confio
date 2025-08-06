module pay::pay {
    use aptos_framework::fungible_asset::{Self, FungibleAsset, Metadata};
    use aptos_framework::primary_fungible_store;
    use aptos_framework::object::{Self, Object};
    use aptos_framework::signer::address_of;
    use aptos_framework::timestamp;
    use aptos_framework::event;
    use std::error;
    use cusd::cusd;
    use confio::confio;

    // Error codes
    const E_INVALID_AMOUNT: u64 = 2;
    const E_SYSTEM_PAUSED: u64 = 3;
    const E_NOT_ADMIN: u64 = 4;

    // Constants
    const FEE_PERCENTAGE: u64 = 90; // 0.9% = 90 basis points
    const BASIS_POINTS: u64 = 10000; // 100% = 10000 basis points

    // Resources
    #[resource_group_member(group = aptos_framework::object::ObjectGroup)]
    struct AdminConfig has key {
        admin: address,
        fee_recipient: address,
        is_paused: bool,
        // Total volume tracking for analytics
        total_cusd_volume: u64,
        total_confio_volume: u64,
        total_cusd_fees_collected: u64,
        total_confio_fees_collected: u64
    }

    // Events
    #[event]
    struct PaymentMade has drop, store {
        payer: address,
        recipient: address,
        amount: u64,
        fee_amount: u64,
        net_amount: u64,
        token_type: vector<u8>, // "CUSD" or "CONFIO"
        payment_id: vector<u8>, // Optional payment ID from Django
        timestamp: u64
    }

    #[event]
    struct FeesWithdrawn has drop, store {
        admin: address,
        recipient: address,
        cusd_amount: u64,
        confio_amount: u64,
        timestamp: u64
    }

    #[event]
    struct FeeRecipientUpdated has drop, store {
        old_recipient: address,
        new_recipient: address,
        timestamp: u64
    }

    #[event]
    struct SystemPaused has drop, store {
        timestamp: u64
    }

    #[event]
    struct SystemUnpaused has drop, store {
        timestamp: u64
    }

    // Initialize
    fun init_module(admin: &signer) {
        // Initialize admin config
        move_to(admin, AdminConfig {
            admin: address_of(admin),
            fee_recipient: address_of(admin), // Initially set to deployer
            is_paused: false,
            total_cusd_volume: 0,
            total_confio_volume: 0,
            total_cusd_fees_collected: 0,
            total_confio_fees_collected: 0
        });
    }

    // Payment Functions - Simple and permissionless
    public entry fun pay_with_cusd(
        payer: &signer,
        amount: u64,
        recipient: address,
        payment_id: vector<u8>, // Optional payment ID from Django for tracking
    ) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@pay);
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        assert!(amount > 0, error::invalid_argument(E_INVALID_AMOUNT));
        
        // Calculate fee (0.9%)
        let fee_amount = (amount * FEE_PERCENTAGE) / BASIS_POINTS;
        let net_amount = amount - fee_amount;
        
        let cusd_metadata = cusd::get_metadata();
        
        // Transfer fee to fee collector
        if (fee_amount > 0) {
            primary_fungible_store::transfer(payer, cusd_metadata, admin_config.fee_recipient, fee_amount);
        };
        
        // Transfer remaining to recipient
        primary_fungible_store::transfer(payer, cusd_metadata, recipient, net_amount);
        
        // Update statistics
        admin_config.total_cusd_volume = admin_config.total_cusd_volume + amount;
        admin_config.total_cusd_fees_collected = admin_config.total_cusd_fees_collected + fee_amount;
        
        // Emit event
        event::emit(PaymentMade {
            payer: address_of(payer),
            recipient,
            amount,
            fee_amount,
            net_amount,
            token_type: b"CUSD",
            payment_id,
            timestamp: timestamp::now_microseconds()
        });
    }

    public entry fun pay_with_confio(
        payer: &signer,
        amount: u64,
        recipient: address,
        payment_id: vector<u8>, // Optional payment ID from Django for tracking
    ) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@pay);
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        assert!(amount > 0, error::invalid_argument(E_INVALID_AMOUNT));
        
        // Calculate fee (0.9%)
        let fee_amount = (amount * FEE_PERCENTAGE) / BASIS_POINTS;
        let net_amount = amount - fee_amount;
        
        let confio_metadata = confio::get_metadata();
        
        // Transfer fee to fee collector
        if (fee_amount > 0) {
            primary_fungible_store::transfer(payer, confio_metadata, admin_config.fee_recipient, fee_amount);
        };
        
        // Transfer remaining to recipient
        primary_fungible_store::transfer(payer, confio_metadata, recipient, net_amount);
        
        // Update statistics
        admin_config.total_confio_volume = admin_config.total_confio_volume + amount;
        admin_config.total_confio_fees_collected = admin_config.total_confio_fees_collected + fee_amount;
        
        // Emit event
        event::emit(PaymentMade {
            payer: address_of(payer),
            recipient,
            amount,
            fee_amount,
            net_amount,
            token_type: b"CONFIO",
            payment_id,
            timestamp: timestamp::now_microseconds()
        });
    }

    // Admin Functions
    public entry fun withdraw_fees(
        admin: &signer,
    ) acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        
        let recipient = admin_config.fee_recipient;
        let cusd_metadata = cusd::get_metadata();
        let confio_metadata = confio::get_metadata();
        
        // Get current balances
        let cusd_amount = primary_fungible_store::balance(recipient, cusd_metadata);
        let confio_amount = primary_fungible_store::balance(recipient, confio_metadata);
        
        // Note: In this simplified version, we just emit the event since fees are already 
        // in the fee_recipient's account. In a more complex implementation, 
        // you might want to track fees separately.
        
        event::emit(FeesWithdrawn {
            admin: address_of(admin),
            recipient,
            cusd_amount,
            confio_amount,
            timestamp: timestamp::now_microseconds()
        });
    }

    public entry fun update_fee_recipient(
        admin: &signer,
        new_recipient: address,
    ) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@pay);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        
        let old_recipient = admin_config.fee_recipient;
        admin_config.fee_recipient = new_recipient;
        
        event::emit(FeeRecipientUpdated {
            old_recipient,
            new_recipient,
            timestamp: timestamp::now_microseconds()
        });
    }

    public entry fun pause(admin: &signer) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@pay);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        assert!(!admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        
        admin_config.is_paused = true;
        
        event::emit(SystemPaused {
            timestamp: timestamp::now_microseconds()
        });
    }

    public entry fun unpause(admin: &signer) acquires AdminConfig {
        let admin_config = borrow_global_mut<AdminConfig>(@pay);
        assert!(address_of(admin) == admin_config.admin, error::permission_denied(E_NOT_ADMIN));
        assert!(admin_config.is_paused, error::invalid_state(E_SYSTEM_PAUSED));
        
        admin_config.is_paused = false;
        
        event::emit(SystemUnpaused {
            timestamp: timestamp::now_microseconds()
        });
    }

    // View Functions
    #[view]
    public fun get_fee_balances(): (u64, u64) acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        let cusd_metadata = cusd::get_metadata();
        let confio_metadata = confio::get_metadata();
        (
            primary_fungible_store::balance(admin_config.fee_recipient, cusd_metadata),
            primary_fungible_store::balance(admin_config.fee_recipient, confio_metadata)
        )
    }

    #[view]
    public fun get_total_volume(): (u64, u64) acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        (admin_config.total_cusd_volume, admin_config.total_confio_volume)
    }

    #[view]
    public fun get_total_fees_collected(): (u64, u64) acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        (admin_config.total_cusd_fees_collected, admin_config.total_confio_fees_collected)
    }

    #[view]
    public fun get_fee_recipient(): address acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        admin_config.fee_recipient
    }

    #[view]
    public fun is_paused(): bool acquires AdminConfig {
        let admin_config = borrow_global<AdminConfig>(@pay);
        admin_config.is_paused
    }
}