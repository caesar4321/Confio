#[allow(unused_use, duplicate_alias, unused_variable)]
module confio::cusd {
    use sui::object::{Self, UID};
    use sui::tx_context::{Self, sender};
    use sui::transfer::{Self, public_transfer};
    use sui::coin::{Self, Coin, TreasuryCap};
    use sui::balance::{Self, Balance};
    use sui::url::{Self};
    use sui::event::{Self};
    use sui::vec_set::{Self, VecSet};
    use std::option::{Self};

    const ENotAuthorized: u64 = 1;
    const EInvalidVaultAddress: u64 = 2;
    const EAddressFrozen: u64 = 3;
    const ESystemPaused: u64 = 4;

    public struct CUSD has drop {}
    public struct AdminCap has key, store {
        id: UID,
    }
    public struct VaultRegistry has key, store {
        id: UID,
        vaults: VecSet<address>,
    }
    public struct FreezeRegistry has key, store {
        id: UID,
        frozen_addresses: VecSet<address>,
    }
    public struct PauseState has key, store {
        id: UID,
        is_paused: bool,
    }
    public struct BurnRequest has key, store {
        id: UID,
        cusd: Balance<CUSD>,
        requester: address,
    }
    public struct CUSDMinted has copy, drop {
        amount: u64,
        recipient: address,
        deposit_address: address
    }
    public struct CUSDBurned has copy, drop {
        amount: u64,
        deposit_address: address
    }
    public struct AddressFrozen has copy, drop {
        address: address,
    }
    public struct AddressUnfrozen has copy, drop {
        address: address,
    }
    public struct Paused has copy, drop {}
    public struct Unpaused has copy, drop {}

    fun init(witness: CUSD, ctx: &mut TxContext) {
        let (treasury_cap, metadata) = coin::create_currency(
            witness,
            6,
            b"CUSD",
            b"Confío Dollar",
            b"A USD-pegged stablecoin for Confío",
            option::some(url::new_unsafe_from_bytes(b"https://raw.githubusercontent.com/caesar4321/Confio/main/web/src/images/CUSD.png")),
            ctx
        );
        public_transfer(metadata, sender(ctx));
        public_transfer(treasury_cap, sender(ctx));
        transfer::transfer(AdminCap { id: object::new(ctx) }, sender(ctx));
        transfer::transfer(VaultRegistry {
            id: object::new(ctx),
            vaults: vec_set::empty(),
        }, sender(ctx));
        transfer::transfer(FreezeRegistry {
            id: object::new(ctx),
            frozen_addresses: vec_set::empty(),
        }, sender(ctx));
        transfer::transfer(PauseState {
            id: object::new(ctx),
            is_paused: false,
        }, sender(ctx));
    }

    public entry fun pause(admin: &AdminCap, pause_state: &mut PauseState, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        pause_state.is_paused = true;
        event::emit(Paused {});
    }

    public entry fun unpause(admin: &AdminCap, pause_state: &mut PauseState, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        pause_state.is_paused = false;
        event::emit(Unpaused {});
    }

    public entry fun add_vault(admin: &AdminCap, registry: &mut VaultRegistry, vault: address, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        vec_set::insert(&mut registry.vaults, vault);
    }

    public entry fun remove_vault(admin: &AdminCap, registry: &mut VaultRegistry, vault: address, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        vec_set::remove(&mut registry.vaults, &vault);
    }

    public entry fun freeze_address(admin: &AdminCap, registry: &mut FreezeRegistry, address: address, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        vec_set::insert(&mut registry.frozen_addresses, address);
        event::emit(AddressFrozen { address });
    }

    public entry fun unfreeze_address(admin: &AdminCap, registry: &mut FreezeRegistry, address: address, ctx: &mut TxContext) {
        assert!(sender(ctx) == object::uid_to_address(&admin.id), ENotAuthorized);
        vec_set::remove(&mut registry.frozen_addresses, &address);
        event::emit(AddressUnfrozen { address });
    }

    public fun mint(
        treasury_cap: &mut TreasuryCap<CUSD>,
        pause_state: &PauseState,
        freeze_registry: &FreezeRegistry,
        amount: u64,
        deposit_address: address,
        recipient: address,
        ctx: &mut TxContext
    ): Coin<CUSD> {
        assert!(!pause_state.is_paused, ESystemPaused);
        assert!(!vec_set::contains(&freeze_registry.frozen_addresses, &recipient), EAddressFrozen);
        let coin = coin::mint(treasury_cap, amount, ctx);
        event::emit(CUSDMinted { amount, recipient, deposit_address });
        coin
    }

    public entry fun request_burn(
        cusd: Coin<CUSD>,
        pause_state: &PauseState,
        freeze_registry: &FreezeRegistry,
        ctx: &mut TxContext
    ) {
        assert!(!pause_state.is_paused, ESystemPaused);
        let requester = sender(ctx);
        assert!(!vec_set::contains(&freeze_registry.frozen_addresses, &requester), EAddressFrozen);
        let balance = coin::into_balance(cusd);
        transfer::share_object(BurnRequest {
            id: object::new(ctx),
            cusd: balance,
            requester,
        });
    }

    public entry fun execute_burn(
        registry: &VaultRegistry,
        treasury_cap: &mut TreasuryCap<CUSD>,
        pause_state: &PauseState,
        freeze_registry: &FreezeRegistry,
        request: BurnRequest,
        vault_address: address,
        ctx: &mut TxContext
    ) {
        assert!(!pause_state.is_paused, ESystemPaused);
        assert!(vec_set::contains(&registry.vaults, &vault_address), EInvalidVaultAddress);
        let BurnRequest { id, cusd, requester } = request;
        assert!(!vec_set::contains(&freeze_registry.frozen_addresses, &requester), EAddressFrozen);
        let coin = coin::from_balance(cusd, ctx);
        let amount = coin::burn(treasury_cap, coin);
        event::emit(CUSDBurned { amount, deposit_address: vault_address });
        object::delete(id);
    }

    public entry fun mint_and_transfer(
        treasury_cap: &mut TreasuryCap<CUSD>,
        pause_state: &PauseState,
        freeze_registry: &FreezeRegistry,
        amount: u64,
        deposit_address: address,
        recipient: address,
        ctx: &mut TxContext
    ) {
        let coin = mint(treasury_cap, pause_state, freeze_registry, amount, deposit_address, recipient, ctx);
        public_transfer(coin, recipient);
    }

    public entry fun transfer_cusd(
        cusd: Coin<CUSD>,
        pause_state: &PauseState,
        freeze_registry: &FreezeRegistry,
        recipient: address,
        ctx: &mut TxContext
    ) {
        assert!(!pause_state.is_paused, ESystemPaused);
        let sender_addr = sender(ctx);
        assert!(!vec_set::contains(&freeze_registry.frozen_addresses, &sender_addr), EAddressFrozen);
        assert!(!vec_set::contains(&freeze_registry.frozen_addresses, &recipient), EAddressFrozen);
        public_transfer(cusd, recipient);
    }
}