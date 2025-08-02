#[test_only]
module p2p_trade::escrow_security_test {
    use sui::test_scenario;
    use p2p_trade::p2p_trade::{Self, TradeRegistry, EscrowVault};

    // Test that the escrow system is initialized correctly
    #[test]
    fun test_escrow_initialization() {
        let mut scenario = test_scenario::begin(@0x1);
        
        // Initialize the P2P trade contract
        {
            p2p_trade::test_init(test_scenario::ctx(&mut scenario));
        };

        // Verify the registry and vault are created
        test_scenario::next_tx(&mut scenario, @0x1);
        {
            assert!(test_scenario::has_most_recent_shared<TradeRegistry>(), 0);
            assert!(test_scenario::has_most_recent_shared<EscrowVault>(), 1);
            
            // Check registry initial state
            let registry = test_scenario::take_shared<TradeRegistry>(&scenario);
            let (created, completed, cancelled, disputed, cusd_vol, confio_vol) = p2p_trade::get_stats(&registry);
            
            assert!(created == 0, 100);
            assert!(completed == 0, 101);
            assert!(cancelled == 0, 102);
            assert!(disputed == 0, 103);
            assert!(cusd_vol == 0, 104);
            assert!(confio_vol == 0, 105);
            
            test_scenario::return_shared(registry);
        };

        test_scenario::end(scenario);
    }
}