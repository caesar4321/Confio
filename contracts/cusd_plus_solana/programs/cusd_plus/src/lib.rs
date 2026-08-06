#![allow(unexpected_cfgs)]

use anchor_lang::prelude::*;
use anchor_lang::solana_program::program_option::COption;
use anchor_spl::token_interface::{
    self, Burn, Mint, MintTo, TokenAccount, TokenInterface, TransferChecked,
};

mod math;
use math::{apply_growth, mul_div_down, mul_div_up, BPS, WAD};

declare_id!("2qmE51mm77tEzfxApr2JJDgWG8vGdgBufMEMc3n4sjs7");

const CONFIG_SEED: &[u8] = b"config";
const AUTHORITY_SEED: &[u8] = b"vault-authority";
const SPONSOR_SEED: &[u8] = b"sponsor";
const MAX_FUTURE_SKEW_SECONDS: i64 = 60;

#[program]
pub mod cusd_plus {
    use super::*;

    pub fn initialize(ctx: Context<Initialize>, args: InitializeArgs) -> Result<()> {
        validate_price(args.initial_usdy_price_wad)?;
        require!(args.price_authority != Pubkey::default(), VaultError::ZeroAddress);
        require!(
            args.confio_yield_share_bps <= 3_000,
            VaultError::YieldShareTooHigh
        );
        require!(args.max_price_age_seconds > 0, VaultError::InvalidPriceAge);
        require!(args.max_accrual_jump_bps > 0, VaultError::InvalidJumpLimit);
        let now = Clock::get()?.unix_timestamp;
        validate_observation_window(
            now,
            args.initial_observed_at,
            args.max_price_age_seconds,
        )?;
        require!(
            ctx.accounts.cusd_mint.decimals == ctx.accounts.usdy_mint.decimals,
            VaultError::DecimalMismatch
        );
        require!(
            ctx.accounts.cusd_mint.mint_authority
                == COption::Some(ctx.accounts.vault_authority.key()),
            VaultError::InvalidMintAuthority
        );
        require!(
            ctx.accounts.cusd_mint.freeze_authority == COption::None,
            VaultError::InvalidFreezeAuthority
        );
        require!(ctx.accounts.cusd_mint.supply == 0, VaultError::NonzeroInitialSupply);
        require_keys_neq!(
            ctx.accounts.cusd_mint.key(),
            ctx.accounts.usdy_mint.key(),
            VaultError::SameMint
        );
        require_keys_eq!(
            ctx.accounts.usdy_token_program.key(),
            anchor_spl::token::ID,
            VaultError::UnsupportedTokenProgram
        );

        let config = &mut ctx.accounts.config;
        config.version = 1;
        config.authority = ctx.accounts.authority.key();
        config.pending_authority = Pubkey::default();
        config.price_authority = args.price_authority;
        config.usdy_mint = ctx.accounts.usdy_mint.key();
        config.cusd_mint = ctx.accounts.cusd_mint.key();
        config.reserve = ctx.accounts.reserve.key();
        config.treasury_usdy_account = ctx.accounts.treasury_usdy.key();
        config.future_settlement_program = Pubkey::default();
        config.p_plus_wad = WAD;
        config.last_usdy_price_wad = args.initial_usdy_price_wad;
        config.guarded_usdy_price_wad = 0;
        config.last_price_timestamp = args.initial_observed_at;
        config.max_price_age_seconds = args.max_price_age_seconds;
        config.confio_yield_share_bps = args.confio_yield_share_bps;
        config.max_accrual_jump_bps = args.max_accrual_jump_bps;
        config.paused = false;
        config.oracle_guard_tripped = false;
        config.config_bump = ctx.bumps.config;
        config.authority_bump = ctx.bumps.vault_authority;
        config.reserved = [0; 128];
        Ok(())
    }

    /// Records an address allowed to co-sign primary issuance. The recipient
    /// is always the depositor, so a sponsor can never redirect minted shares.
    pub fn set_sponsor(ctx: Context<SetSponsor>, sponsor_key: Pubkey, allowed: bool) -> Result<()> {
        let record = &mut ctx.accounts.sponsor_record;
        record.sponsor = sponsor_key;
        record.allowed = allowed;
        record.bump = ctx.bumps.sponsor_record;
        emit!(SponsorSet {
            sponsor: sponsor_key,
            allowed
        });
        Ok(())
    }

    /// Jupiter-composed entry path. Jupiter swaps into `depositor_usdy`
    /// earlier in this same Solana transaction; this instruction transfers
    /// the exact USDY backing into the reserve and only then mints cUSD+.
    pub fn deposit_and_mint(
        ctx: Context<DepositAndMint>,
        usdy_in: u64,
        min_shares_out: u64,
    ) -> Result<()> {
        require!(usdy_in > 0, VaultError::ZeroAmount);
        require!(
            ctx.accounts.sponsor_record.allowed,
            VaultError::NotSponsored
        );
        assert_value_path_open(&ctx.accounts.config)?;

        let p = ctx.accounts.config.last_usdy_price_wad;
        let shares_out = mul_div_down(usdy_in, p, ctx.accounts.config.p_plus_wad)?;
        require!(shares_out > 0, VaultError::Dust);
        require!(shares_out >= min_shares_out, VaultError::SlippageExceeded);

        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.usdy_token_program.key(),
                TransferChecked {
                    mint: ctx.accounts.usdy_mint.to_account_info(),
                    from: ctx.accounts.depositor_usdy.to_account_info(),
                    to: ctx.accounts.reserve.to_account_info(),
                    authority: ctx.accounts.depositor.to_account_info(),
                },
            ),
            usdy_in,
            ctx.accounts.usdy_mint.decimals,
        )?;

        let authority_bump = [ctx.accounts.config.authority_bump];
        let signer: &[&[&[u8]]] = &[&[AUTHORITY_SEED, &authority_bump]];
        token_interface::mint_to(
            CpiContext::new(
                ctx.accounts.cusd_token_program.key(),
                MintTo {
                    mint: ctx.accounts.cusd_mint.to_account_info(),
                    to: ctx.accounts.depositor_cusd.to_account_info(),
                    authority: ctx.accounts.vault_authority.to_account_info(),
                },
            )
            .with_signer(signer),
            shares_out,
        )?;

        ctx.accounts.reserve.reload()?;
        ctx.accounts.cusd_mint.reload()?;
        assert_fully_backed(
            ctx.accounts.reserve.amount,
            ctx.accounts.cusd_mint.supply,
            ctx.accounts.config.p_plus_wad,
            p,
        )?;
        emit!(Minted {
            recipient: ctx.accounts.depositor.key(),
            shares: shares_out,
            usdy_in,
            p_plus_wad: ctx.accounts.config.p_plus_wad,
        });
        Ok(())
    }

    /// Adapter-neutral exit. It returns raw USDY; Jupiter swap instructions
    /// can follow this instruction in the same atomic transaction today.
    /// A later program upgrade may add an InstantManager CPI path without
    /// changing this core accounting instruction or the cUSD+ mint.
    pub fn redeem_to_usdy(
        ctx: Context<RedeemToUsdy>,
        shares: u64,
        min_usdy_out: u64,
    ) -> Result<()> {
        require!(shares > 0, VaultError::ZeroAmount);
        assert_value_path_open(&ctx.accounts.config)?;
        let p = ctx.accounts.config.last_usdy_price_wad;
        let usdy_out = mul_div_down(shares, ctx.accounts.config.p_plus_wad, p)?;
        require!(usdy_out > 0, VaultError::Dust);
        require!(usdy_out >= min_usdy_out, VaultError::SlippageExceeded);

        token_interface::burn(
            CpiContext::new(
                ctx.accounts.cusd_token_program.key(),
                Burn {
                    mint: ctx.accounts.cusd_mint.to_account_info(),
                    from: ctx.accounts.holder_cusd.to_account_info(),
                    authority: ctx.accounts.holder.to_account_info(),
                },
            ),
            shares,
        )?;

        let authority_bump = [ctx.accounts.config.authority_bump];
        let signer: &[&[&[u8]]] = &[&[AUTHORITY_SEED, &authority_bump]];
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.usdy_token_program.key(),
                TransferChecked {
                    mint: ctx.accounts.usdy_mint.to_account_info(),
                    from: ctx.accounts.reserve.to_account_info(),
                    to: ctx.accounts.holder_usdy.to_account_info(),
                    authority: ctx.accounts.vault_authority.to_account_info(),
                },
            )
            .with_signer(signer),
            usdy_out,
            ctx.accounts.usdy_mint.decimals,
        )?;

        ctx.accounts.reserve.reload()?;
        ctx.accounts.cusd_mint.reload()?;
        assert_fully_backed(
            ctx.accounts.reserve.amount,
            ctx.accounts.cusd_mint.supply,
            ctx.accounts.config.p_plus_wad,
            p,
        )?;
        emit!(Redeemed {
            holder: ctx.accounts.holder.key(),
            shares,
            usdy_out,
            p_plus_wad: ctx.accounts.config.p_plus_wad,
        });
        Ok(())
    }

    /// Confío pushes Ondo's published USDY reference price because no
    /// synchronous Ondo oracle is currently documented on Solana. Freshness,
    /// monotonicity and jump checks gate every value path.
    pub fn update_price(
        ctx: Context<UpdatePrice>,
        new_price_wad: u128,
        observed_at: i64,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        validate_price(new_price_wad)?;
        require!(
            observed_at >= ctx.accounts.config.last_price_timestamp,
            VaultError::OldPrice
        );
        require!(
            observed_at <= now + MAX_FUTURE_SKEW_SECONDS,
            VaultError::FuturePrice
        );
        require!(
            !ctx.accounts.config.oracle_guard_tripped,
            VaultError::OracleGuardTripped
        );

        let config = &mut ctx.accounts.config;
        let last = config.last_usdy_price_wad;
        let abnormal = new_price_wad < last
            || jump_bps(last, new_price_wad)? > config.max_accrual_jump_bps as u128;
        if abnormal {
            config.oracle_guard_tripped = true;
            config.guarded_usdy_price_wad = new_price_wad;
            emit!(OracleJumpGuard {
                last_price_wad: last,
                observed_price_wad: new_price_wad
            });
            return Ok(());
        }
        if new_price_wad > last {
            config.p_plus_wad = apply_growth(
                config.p_plus_wad,
                last,
                new_price_wad,
                config.confio_yield_share_bps,
            )?;
            config.last_usdy_price_wad = new_price_wad;
            emit!(Accrued {
                usdy_price_wad: new_price_wad,
                p_plus_wad: config.p_plus_wad
            });
        }
        config.last_price_timestamp = observed_at;
        Ok(())
    }

    pub fn accept_verified_growth(
        ctx: Context<ResolveOracleGuard>,
        resolved_price_wad: u128,
        observed_at: i64,
        min_verified_price_wad: u128,
        max_verified_price_wad: u128,
        evidence_hash: [u8; 32],
    ) -> Result<()> {
        require!(
            ctx.accounts.config.oracle_guard_tripped,
            VaultError::OracleGuardNotTripped
        );
        require!(evidence_hash != [0; 32], VaultError::MissingEvidence);
        validate_price(resolved_price_wad)?;
        require!(
            resolved_price_wad >= min_verified_price_wad
                && resolved_price_wad <= max_verified_price_wad,
            VaultError::OutsideVerifiedRange
        );
        require!(
            resolved_price_wad > ctx.accounts.config.last_usdy_price_wad,
            VaultError::NoPositiveGrowth
        );
        validate_resolution_time(&ctx.accounts.config, observed_at)?;

        let config = &mut ctx.accounts.config;
        let old = config.last_usdy_price_wad;
        let guarded = config.guarded_usdy_price_wad;
        config.p_plus_wad = apply_growth(
            config.p_plus_wad,
            old,
            resolved_price_wad,
            config.confio_yield_share_bps,
        )?;
        config.last_usdy_price_wad = resolved_price_wad;
        config.last_price_timestamp = observed_at;
        config.guarded_usdy_price_wad = 0;
        config.oracle_guard_tripped = false;
        emit!(OracleGrowthAccepted {
            old_price_wad: old,
            guarded_price_wad: guarded,
            resolved_price_wad,
            evidence_hash
        });
        Ok(())
    }

    pub fn rebaseline_verified_fault(
        ctx: Context<ResolveOracleGuard>,
        corrected_price_wad: u128,
        observed_at: i64,
        min_corrected_price_wad: u128,
        max_corrected_price_wad: u128,
        evidence_hash: [u8; 32],
    ) -> Result<()> {
        require!(
            ctx.accounts.config.oracle_guard_tripped,
            VaultError::OracleGuardNotTripped
        );
        require!(evidence_hash != [0; 32], VaultError::MissingEvidence);
        validate_price(corrected_price_wad)?;
        require!(
            corrected_price_wad >= min_corrected_price_wad
                && corrected_price_wad <= max_corrected_price_wad,
            VaultError::OutsideVerifiedRange
        );
        validate_resolution_time(&ctx.accounts.config, observed_at)?;

        let config = &mut ctx.accounts.config;
        let old = config.last_usdy_price_wad;
        let guarded = config.guarded_usdy_price_wad;
        config.last_usdy_price_wad = corrected_price_wad;
        config.last_price_timestamp = observed_at;
        config.guarded_usdy_price_wad = 0;
        config.oracle_guard_tripped = false;
        emit!(OracleFaultRebaselined {
            old_price_wad: old,
            guarded_price_wad: guarded,
            resolved_price_wad: corrected_price_wad,
            evidence_hash
        });
        Ok(())
    }

    pub fn collect_fees(ctx: Context<CollectFees>, usdy_amount: u64) -> Result<()> {
        require!(usdy_amount > 0, VaultError::ZeroAmount);
        assert_price_fresh(&ctx.accounts.config)?;
        require!(
            !ctx.accounts.config.oracle_guard_tripped,
            VaultError::OracleGuardTripped
        );
        let owed = mul_div_up(
            ctx.accounts.cusd_mint.supply,
            ctx.accounts.config.p_plus_wad,
            ctx.accounts.config.last_usdy_price_wad,
        )?;
        let surplus = ctx.accounts.reserve.amount.saturating_sub(owed);
        require!(usdy_amount <= surplus, VaultError::ExceedsSurplus);

        let authority_bump = [ctx.accounts.config.authority_bump];
        let signer: &[&[&[u8]]] = &[&[AUTHORITY_SEED, &authority_bump]];
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.usdy_token_program.key(),
                TransferChecked {
                    mint: ctx.accounts.usdy_mint.to_account_info(),
                    from: ctx.accounts.reserve.to_account_info(),
                    to: ctx.accounts.treasury_usdy.to_account_info(),
                    authority: ctx.accounts.vault_authority.to_account_info(),
                },
            )
            .with_signer(signer),
            usdy_amount,
            ctx.accounts.usdy_mint.decimals,
        )?;
        emit!(FeesCollected {
            usdy_amount,
            surplus_before: surplus
        });
        Ok(())
    }

    pub fn set_paused(ctx: Context<AdminOnly>, paused: bool) -> Result<()> {
        ctx.accounts.config.paused = paused;
        emit!(PauseSet { paused });
        Ok(())
    }

    /// Reserved wiring for a future InstantManager adapter. Version 1 never
    /// invokes this address; recording it now keeps the state layout stable.
    pub fn set_future_settlement_program(ctx: Context<AdminOnly>, program: Pubkey) -> Result<()> {
        ctx.accounts.config.future_settlement_program = program;
        emit!(FutureSettlementProgramSet { program });
        Ok(())
    }

    pub fn set_price_authority(ctx: Context<AdminOnly>, price_authority: Pubkey) -> Result<()> {
        require!(
            price_authority != Pubkey::default(),
            VaultError::ZeroAddress
        );
        ctx.accounts.config.price_authority = price_authority;
        emit!(PriceAuthoritySet { price_authority });
        Ok(())
    }

    pub fn propose_authority(ctx: Context<AdminOnly>, pending: Pubkey) -> Result<()> {
        require!(pending != Pubkey::default(), VaultError::ZeroAddress);
        ctx.accounts.config.pending_authority = pending;
        Ok(())
    }

    pub fn accept_authority(ctx: Context<AcceptAuthority>) -> Result<()> {
        ctx.accounts.config.authority = ctx.accounts.pending_authority.key();
        ctx.accounts.config.treasury_usdy_account = ctx.accounts.new_treasury_usdy.key();
        ctx.accounts.config.pending_authority = Pubkey::default();
        Ok(())
    }
}

fn jump_bps(last: u128, new_price: u128) -> Result<u128> {
    require!(last > 0, VaultError::InvalidPrice);
    if new_price <= last {
        return Ok(0);
    }
    let delta = new_price
        .checked_sub(last)
        .ok_or_else(|| error!(VaultError::ArithmeticOverflow))?;
    let scaled = delta
        .checked_mul(BPS)
        .ok_or_else(|| error!(VaultError::ArithmeticOverflow))?;
    scaled
        .checked_div(last)
        .ok_or_else(|| error!(VaultError::ArithmeticOverflow))
}

fn validate_price(price: u128) -> Result<()> {
    require!(
        price > 0 && price <= u64::MAX as u128,
        VaultError::InvalidPrice
    );
    Ok(())
}

fn validate_observation_window(now: i64, observed_at: i64, max_age_seconds: i64) -> Result<()> {
    require!(
        observed_at <= now.saturating_add(MAX_FUTURE_SKEW_SECONDS),
        VaultError::FuturePrice
    );
    require!(
        now.saturating_sub(observed_at) <= max_age_seconds,
        VaultError::StalePrice
    );
    Ok(())
}

fn assert_value_path_open(config: &Config) -> Result<()> {
    require!(!config.paused, VaultError::Paused);
    require!(!config.oracle_guard_tripped, VaultError::OracleGuardTripped);
    assert_price_fresh(config)
}

fn assert_price_fresh(config: &Config) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(now >= config.last_price_timestamp, VaultError::FuturePrice);
    require!(
        now - config.last_price_timestamp <= config.max_price_age_seconds,
        VaultError::StalePrice
    );
    Ok(())
}

fn validate_resolution_time(config: &Config, observed_at: i64) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(
        observed_at >= config.last_price_timestamp,
        VaultError::OldPrice
    );
    require!(
        observed_at <= now + MAX_FUTURE_SKEW_SECONDS,
        VaultError::FuturePrice
    );
    Ok(())
}

fn assert_fully_backed(reserve: u64, supply: u64, p_plus: u128, usdy_price: u128) -> Result<()> {
    let owed = mul_div_up(supply, p_plus, usdy_price)?;
    require!(reserve >= owed, VaultError::UnderCollateralized);
    Ok(())
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct InitializeArgs {
    pub price_authority: Pubkey,
    pub initial_usdy_price_wad: u128,
    pub initial_observed_at: i64,
    pub max_price_age_seconds: i64,
    pub confio_yield_share_bps: u16,
    pub max_accrual_jump_bps: u16,
}

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,
    #[account(
        constraint = program.programdata_address()? == Some(program_data.key())
            @ VaultError::InvalidProgramData
    )]
    pub program: Program<'info, program::CusdPlus>,
    #[account(
        constraint = is_initializer_authority(
            program_data.upgrade_authority_address,
            authority.key()
        ) @ VaultError::UnauthorizedInitializer
    )]
    pub program_data: Account<'info, ProgramData>,
    #[account(init, payer = authority, space = Config::SPACE, seeds = [CONFIG_SEED], bump)]
    pub config: Account<'info, Config>,
    /// CHECK: PDA is only used as an SPL authority.
    #[account(seeds = [AUTHORITY_SEED], bump)]
    pub vault_authority: UncheckedAccount<'info>,
    #[account(mint::token_program = usdy_token_program)]
    pub usdy_mint: InterfaceAccount<'info, Mint>,
    #[account(mint::token_program = cusd_token_program)]
    pub cusd_mint: InterfaceAccount<'info, Mint>,
    #[account(token::mint = usdy_mint, token::authority = vault_authority, token::token_program = usdy_token_program)]
    pub reserve: InterfaceAccount<'info, TokenAccount>,
    #[account(token::mint = usdy_mint, token::authority = authority, token::token_program = usdy_token_program)]
    pub treasury_usdy: InterfaceAccount<'info, TokenAccount>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub usdy_token_program: Interface<'info, TokenInterface>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub cusd_token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(sponsor_key: Pubkey)]
pub struct SetSponsor<'info> {
    #[account(mut, address = config.authority)]
    pub authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.config_bump)]
    pub config: Account<'info, Config>,
    #[account(init_if_needed, payer = authority, space = Sponsor::SPACE, seeds = [SPONSOR_SEED, sponsor_key.as_ref()], bump)]
    pub sponsor_record: Account<'info, Sponsor>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct DepositAndMint<'info> {
    #[account(mut)]
    pub depositor: Signer<'info>,
    pub sponsor: Signer<'info>,
    #[account(seeds = [SPONSOR_SEED, sponsor.key().as_ref()], bump = sponsor_record.bump, constraint = sponsor_record.sponsor == sponsor.key())]
    pub sponsor_record: Account<'info, Sponsor>,
    #[account(seeds = [CONFIG_SEED], bump = config.config_bump, has_one = usdy_mint, has_one = cusd_mint, has_one = reserve)]
    pub config: Account<'info, Config>,
    /// CHECK: PDA is only used as an SPL authority.
    #[account(seeds = [AUTHORITY_SEED], bump = config.authority_bump)]
    pub vault_authority: UncheckedAccount<'info>,
    pub usdy_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub cusd_mint: InterfaceAccount<'info, Mint>,
    #[account(mut, token::mint = usdy_mint, token::authority = depositor, token::token_program = usdy_token_program)]
    pub depositor_usdy: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = cusd_mint, token::authority = depositor, token::token_program = cusd_token_program)]
    pub depositor_cusd: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = usdy_mint, token::authority = vault_authority, token::token_program = usdy_token_program)]
    pub reserve: InterfaceAccount<'info, TokenAccount>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub usdy_token_program: Interface<'info, TokenInterface>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub cusd_token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct RedeemToUsdy<'info> {
    #[account(mut)]
    pub holder: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.config_bump, has_one = usdy_mint, has_one = cusd_mint, has_one = reserve)]
    pub config: Account<'info, Config>,
    /// CHECK: PDA is only used as an SPL authority.
    #[account(seeds = [AUTHORITY_SEED], bump = config.authority_bump)]
    pub vault_authority: UncheckedAccount<'info>,
    pub usdy_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub cusd_mint: InterfaceAccount<'info, Mint>,
    #[account(mut, token::mint = cusd_mint, token::authority = holder, token::token_program = cusd_token_program)]
    pub holder_cusd: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = usdy_mint, token::authority = holder, token::token_program = usdy_token_program)]
    pub holder_usdy: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = usdy_mint, token::authority = vault_authority, token::token_program = usdy_token_program)]
    pub reserve: InterfaceAccount<'info, TokenAccount>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub usdy_token_program: Interface<'info, TokenInterface>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub cusd_token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct UpdatePrice<'info> {
    #[account(address = config.price_authority)]
    pub price_authority: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.config_bump)]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
pub struct ResolveOracleGuard<'info> {
    #[account(address = config.authority)]
    pub authority: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.config_bump)]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
pub struct CollectFees<'info> {
    #[account(address = config.authority)]
    pub authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.config_bump, has_one = usdy_mint, has_one = cusd_mint, has_one = reserve)]
    pub config: Account<'info, Config>,
    /// CHECK: PDA is only used as an SPL authority.
    #[account(seeds = [AUTHORITY_SEED], bump = config.authority_bump)]
    pub vault_authority: UncheckedAccount<'info>,
    pub usdy_mint: InterfaceAccount<'info, Mint>,
    pub cusd_mint: InterfaceAccount<'info, Mint>,
    #[account(mut, token::mint = usdy_mint, token::authority = vault_authority, token::token_program = usdy_token_program)]
    pub reserve: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, address = config.treasury_usdy_account, token::mint = usdy_mint, token::token_program = usdy_token_program)]
    pub treasury_usdy: InterfaceAccount<'info, TokenAccount>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub usdy_token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct AdminOnly<'info> {
    #[account(address = config.authority)]
    pub authority: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.config_bump)]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
pub struct AcceptAuthority<'info> {
    #[account(address = config.pending_authority)]
    pub pending_authority: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.config_bump, has_one = usdy_mint)]
    pub config: Account<'info, Config>,
    pub usdy_mint: InterfaceAccount<'info, Mint>,
    #[account(token::mint = usdy_mint, token::authority = pending_authority, token::token_program = usdy_token_program)]
    pub new_treasury_usdy: InterfaceAccount<'info, TokenAccount>,
    #[account(address = anchor_spl::token::ID @ VaultError::UnsupportedTokenProgram)]
    pub usdy_token_program: Interface<'info, TokenInterface>,
}

#[account]
pub struct Config {
    pub version: u8,
    pub authority: Pubkey,
    pub pending_authority: Pubkey,
    pub price_authority: Pubkey,
    pub usdy_mint: Pubkey,
    pub cusd_mint: Pubkey,
    pub reserve: Pubkey,
    pub treasury_usdy_account: Pubkey,
    pub future_settlement_program: Pubkey,
    pub p_plus_wad: u128,
    pub last_usdy_price_wad: u128,
    pub guarded_usdy_price_wad: u128,
    pub last_price_timestamp: i64,
    pub max_price_age_seconds: i64,
    pub confio_yield_share_bps: u16,
    pub max_accrual_jump_bps: u16,
    pub paused: bool,
    pub oracle_guard_tripped: bool,
    pub config_bump: u8,
    pub authority_bump: u8,
    pub reserved: [u8; 128],
}

impl Config {
    pub const SPACE: usize = 8 + 512;
}

#[account]
pub struct Sponsor {
    pub sponsor: Pubkey,
    pub allowed: bool,
    pub bump: u8,
}
impl Sponsor {
    pub const SPACE: usize = 8 + 32 + 1 + 1;
}

#[event]
pub struct Minted {
    pub recipient: Pubkey,
    pub shares: u64,
    pub usdy_in: u64,
    pub p_plus_wad: u128,
}
#[event]
pub struct Redeemed {
    pub holder: Pubkey,
    pub shares: u64,
    pub usdy_out: u64,
    pub p_plus_wad: u128,
}
#[event]
pub struct Accrued {
    pub usdy_price_wad: u128,
    pub p_plus_wad: u128,
}
#[event]
pub struct OracleJumpGuard {
    pub last_price_wad: u128,
    pub observed_price_wad: u128,
}
#[event]
pub struct OracleGrowthAccepted {
    pub old_price_wad: u128,
    pub guarded_price_wad: u128,
    pub resolved_price_wad: u128,
    pub evidence_hash: [u8; 32],
}
#[event]
pub struct OracleFaultRebaselined {
    pub old_price_wad: u128,
    pub guarded_price_wad: u128,
    pub resolved_price_wad: u128,
    pub evidence_hash: [u8; 32],
}
#[event]
pub struct FeesCollected {
    pub usdy_amount: u64,
    pub surplus_before: u64,
}
#[event]
pub struct SponsorSet {
    pub sponsor: Pubkey,
    pub allowed: bool,
}
#[event]
pub struct PauseSet {
    pub paused: bool,
}
#[event]
pub struct FutureSettlementProgramSet {
    pub program: Pubkey,
}
#[event]
pub struct PriceAuthoritySet {
    pub price_authority: Pubkey,
}

#[error_code]
pub enum VaultError {
    #[msg("vault is paused")]
    Paused,
    #[msg("oracle guard is tripped")]
    OracleGuardTripped,
    #[msg("oracle guard is not tripped")]
    OracleGuardNotTripped,
    #[msg("price is stale")]
    StalePrice,
    #[msg("price observation is older than the current baseline")]
    OldPrice,
    #[msg("price observation is too far in the future")]
    FuturePrice,
    #[msg("invalid price")]
    InvalidPrice,
    #[msg("invalid price age")]
    InvalidPriceAge,
    #[msg("invalid jump limit")]
    InvalidJumpLimit,
    #[msg("yield share exceeds 30%")]
    YieldShareTooHigh,
    #[msg("USDY and cUSD+ mint decimals must match")]
    DecimalMismatch,
    #[msg("cUSD+ mint authority is not the vault PDA")]
    InvalidMintAuthority,
    #[msg("cUSD+ mint must not have a freeze authority")]
    InvalidFreezeAuthority,
    #[msg("cUSD+ mint must have zero initial supply")]
    NonzeroInitialSupply,
    #[msg("USDY and cUSD+ must be distinct mints")]
    SameMint,
    #[msg("v1 supports the legacy SPL Token program only")]
    UnsupportedTokenProgram,
    #[msg("mint is not sponsored")]
    NotSponsored,
    #[msg("zero amount")]
    ZeroAmount,
    #[msg("amount rounds to zero")]
    Dust,
    #[msg("minimum output not met")]
    SlippageExceeded,
    #[msg("vault would be undercollateralized")]
    UnderCollateralized,
    #[msg("fee collection exceeds surplus")]
    ExceedsSurplus,
    #[msg("missing evidence hash")]
    MissingEvidence,
    #[msg("resolved price is outside verified range")]
    OutsideVerifiedRange,
    #[msg("resolved price has no positive growth")]
    NoPositiveGrowth,
    #[msg("arithmetic overflow")]
    ArithmeticOverflow,
    #[msg("zero address")]
    ZeroAddress,
    #[msg("initializer is not the current program upgrade authority")]
    UnauthorizedInitializer,
    #[msg("program data does not belong to this program")]
    InvalidProgramData,
}

fn is_initializer_authority(upgrade_authority: Option<Pubkey>, signer: Pubkey) -> bool {
    upgrade_authority == Some(signer)
}

#[cfg(test)]
mod initialization_tests {
    use super::*;

    #[test]
    fn current_upgrade_authority_can_initialize() {
        let authority = Pubkey::new_unique();
        assert!(is_initializer_authority(Some(authority), authority));
    }

    #[test]
    fn unrelated_signer_cannot_initialize() {
        assert!(!is_initializer_authority(
            Some(Pubkey::new_unique()),
            Pubkey::new_unique()
        ));
    }

    #[test]
    fn immutable_program_cannot_initialize() {
        assert!(!is_initializer_authority(None, Pubkey::new_unique()));
    }

    #[test]
    fn prices_are_positive_and_fit_the_documented_math_width() {
        assert!(validate_price(1).is_ok());
        assert!(validate_price(u64::MAX as u128).is_ok());
        assert!(validate_price(0).is_err());
        assert!(validate_price(u64::MAX as u128 + 1).is_err());
        assert!(validate_price(u128::MAX).is_err());
    }

    #[test]
    fn initial_observation_must_be_fresh_and_not_far_future_dated() {
        let now = 10_000;
        assert!(validate_observation_window(now, 9_700, 300).is_ok());
        assert!(validate_observation_window(now, 9_699, 300).is_err());
        assert!(validate_observation_window(now, 10_060, 300).is_ok());
        assert!(validate_observation_window(now, 10_061, 300).is_err());
    }
}
