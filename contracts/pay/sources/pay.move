module pay::pay {
    use sui::object::{Self, UID};
    use sui::tx_context::{Self, sender, TxContext};
    use sui::transfer::{Self, public_transfer, share_object};
    use sui::coin::{Self, Coin};
    use sui::balance::{Self, Balance};
    use sui::event;
    use cusd::cusd::CUSD;
    use confio::confio::CONFIO;

    // Error codes
    const EInvalidAmount: u64 = 2;
    const ESystemPaused: u64 = 3;

    // Constants
    const FEE_PERCENTAGE: u64 = 90; // 0.9% = 90 basis points
    const BASIS_POINTS: u64 = 10000; // 100% = 10000 basis points

    // Objects
    struct AdminCap has key, store {
        id: UID
    }

    struct FeeCollector has key {
        id: UID,
        // Collected fees
        cusd_fees: Balance<CUSD>,
        confio_fees: Balance<CONFIO>,
        // Fee collector address (can be updated by admin)
        fee_recipient: address,
        // System state
        is_paused: bool,
        // Total volume tracking for analytics
        total_cusd_volume: u64,
        total_confio_volume: u64,
        total_cusd_fees_collected: u64,
        total_confio_fees_collected: u64
    }

    // Events
    struct PaymentMade has copy, drop {
        payer: address,
        recipient: address,
        amount: u64,
        fee_amount: u64,
        net_amount: u64,
        token_type: vector<u8>, // "CUSD" or "CONFIO"
        payment_id: vector<u8>, // Optional payment ID from Django
        timestamp: u64
    }

    struct FeesWithdrawn has copy, drop {
        admin: address,
        recipient: address,
        cusd_amount: u64,
        confio_amount: u64,
        timestamp: u64
    }

    struct FeeRecipientUpdated has copy, drop {
        old_recipient: address,
        new_recipient: address,
        timestamp: u64
    }

    struct SystemPaused has copy, drop {
        timestamp: u64
    }

    struct SystemUnpaused has copy, drop {
        timestamp: u64
    }

    // Initialize
    fun init(ctx: &mut TxContext) {
        let admin_cap = AdminCap {
            id: object::new(ctx)
        };
        
        let fee_collector = FeeCollector {
            id: object::new(ctx),
            cusd_fees: balance::zero<CUSD>(),
            confio_fees: balance::zero<CONFIO>(),
            fee_recipient: sender(ctx), // Initially set to deployer
            is_paused: false,
            total_cusd_volume: 0,
            total_confio_volume: 0,
            total_cusd_fees_collected: 0,
            total_confio_fees_collected: 0
        };

        transfer::transfer(admin_cap, sender(ctx));
        share_object(fee_collector);
    }

    // Payment Functions - Simple and permissionless
    public entry fun pay_with_cusd(
        fee_collector: &mut FeeCollector,
        payment: Coin<CUSD>,
        recipient: address,
        payment_id: vector<u8>, // Optional payment ID from Django for tracking
        ctx: &mut TxContext
    ) {
        assert!(!fee_collector.is_paused, ESystemPaused);
        
        let payment_amount = coin::value(&payment);
        assert!(payment_amount > 0, EInvalidAmount);
        
        // Calculate fee (0.9%)
        let fee_amount = (payment_amount * FEE_PERCENTAGE) / BASIS_POINTS;
        let net_amount = payment_amount - fee_amount;
        
        // Split the payment
        let fee_coin = coin::split(&mut payment, fee_amount, ctx);
        
        // Add fee to collector
        let fee_balance = coin::into_balance(fee_coin);
        balance::join(&mut fee_collector.cusd_fees, fee_balance);
        
        // Send remaining to recipient
        public_transfer(payment, recipient);
        
        // Update statistics
        fee_collector.total_cusd_volume = fee_collector.total_cusd_volume + payment_amount;
        fee_collector.total_cusd_fees_collected = fee_collector.total_cusd_fees_collected + fee_amount;
        
        // Emit event
        event::emit(PaymentMade {
            payer: sender(ctx),
            recipient,
            amount: payment_amount,
            fee_amount,
            net_amount,
            token_type: b"CUSD",
            payment_id,
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    public entry fun pay_with_confio(
        fee_collector: &mut FeeCollector,
        payment: Coin<CONFIO>,
        recipient: address,
        payment_id: vector<u8>, // Optional payment ID from Django for tracking
        ctx: &mut TxContext
    ) {
        assert!(!fee_collector.is_paused, ESystemPaused);
        
        let payment_amount = coin::value(&payment);
        assert!(payment_amount > 0, EInvalidAmount);
        
        // Calculate fee (0.9%)
        let fee_amount = (payment_amount * FEE_PERCENTAGE) / BASIS_POINTS;
        let net_amount = payment_amount - fee_amount;
        
        // Split the payment
        let fee_coin = coin::split(&mut payment, fee_amount, ctx);
        
        // Add fee to collector
        let fee_balance = coin::into_balance(fee_coin);
        balance::join(&mut fee_collector.confio_fees, fee_balance);
        
        // Send remaining to recipient
        public_transfer(payment, recipient);
        
        // Update statistics
        fee_collector.total_confio_volume = fee_collector.total_confio_volume + payment_amount;
        fee_collector.total_confio_fees_collected = fee_collector.total_confio_fees_collected + fee_amount;
        
        // Emit event
        event::emit(PaymentMade {
            payer: sender(ctx),
            recipient,
            amount: payment_amount,
            fee_amount,
            net_amount,
            token_type: b"CONFIO",
            payment_id,
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    // Admin Functions
    public entry fun withdraw_fees(
        _admin: &AdminCap,
        fee_collector: &mut FeeCollector,
        ctx: &mut TxContext
    ) {
        let cusd_amount = balance::value(&fee_collector.cusd_fees);
        let confio_amount = balance::value(&fee_collector.confio_fees);
        let recipient = fee_collector.fee_recipient;
        
        if (cusd_amount > 0) {
            let cusd_coin = coin::from_balance(
                balance::split(&mut fee_collector.cusd_fees, cusd_amount),
                ctx
            );
            public_transfer(cusd_coin, recipient);
        };
        
        if (confio_amount > 0) {
            let confio_coin = coin::from_balance(
                balance::split(&mut fee_collector.confio_fees, confio_amount),
                ctx
            );
            public_transfer(confio_coin, recipient);
        };
        
        event::emit(FeesWithdrawn {
            admin: sender(ctx),
            recipient,
            cusd_amount,
            confio_amount,
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    public entry fun update_fee_recipient(
        _admin: &AdminCap,
        fee_collector: &mut FeeCollector,
        new_recipient: address,
        ctx: &mut TxContext
    ) {
        let old_recipient = fee_collector.fee_recipient;
        fee_collector.fee_recipient = new_recipient;
        
        event::emit(FeeRecipientUpdated {
            old_recipient,
            new_recipient,
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    public entry fun pause(_admin: &AdminCap, fee_collector: &mut FeeCollector, ctx: &mut TxContext) {
        assert!(!fee_collector.is_paused, ESystemPaused);
        fee_collector.is_paused = true;
        
        event::emit(SystemPaused {
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    public entry fun unpause(_admin: &AdminCap, fee_collector: &mut FeeCollector, ctx: &mut TxContext) {
        assert!(fee_collector.is_paused, ESystemPaused);
        fee_collector.is_paused = false;
        
        event::emit(SystemUnpaused {
            timestamp: tx_context::epoch_timestamp_ms(ctx)
        });
    }

    // View Functions
    public fun get_fee_balances(fee_collector: &FeeCollector): (u64, u64) {
        (
            balance::value(&fee_collector.cusd_fees),
            balance::value(&fee_collector.confio_fees)
        )
    }

    public fun get_total_volume(fee_collector: &FeeCollector): (u64, u64) {
        (fee_collector.total_cusd_volume, fee_collector.total_confio_volume)
    }

    public fun get_total_fees_collected(fee_collector: &FeeCollector): (u64, u64) {
        (fee_collector.total_cusd_fees_collected, fee_collector.total_confio_fees_collected)
    }

    public fun get_fee_recipient(fee_collector: &FeeCollector): address {
        fee_collector.fee_recipient
    }

    public fun is_paused(fee_collector: &FeeCollector): bool {
        fee_collector.is_paused
    }
}