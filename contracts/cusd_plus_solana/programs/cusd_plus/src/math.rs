use anchor_lang::prelude::*;

pub const WAD: u128 = 1_000_000_000_000_000_000;
pub const BPS: u128 = 10_000;

/// floor(a*b/denominator). The program constrains token amounts to u64 and
/// prices to u64-sized WAD values, so their product is safely inside u128.
pub fn mul_div_down(a: u64, b: u128, denominator: u128) -> Result<u64> {
    require!(denominator != 0, MathError::DivisionByZero);
    let value = (a as u128)
        .checked_mul(b)
        .ok_or(MathError::Overflow)?
        .checked_div(denominator)
        .ok_or(MathError::DivisionByZero)?;
    u64::try_from(value).map_err(|_| error!(MathError::Overflow))
}

/// ceil(a*b/denominator), used for obligations so rounding favors backing.
pub fn mul_div_up(a: u64, b: u128, denominator: u128) -> Result<u64> {
    require!(denominator != 0, MathError::DivisionByZero);
    let numerator = (a as u128).checked_mul(b).ok_or(MathError::Overflow)?;
    let value = numerator
        .checked_add(denominator - 1)
        .ok_or(MathError::Overflow)?
        .checked_div(denominator)
        .ok_or(MathError::DivisionByZero)?;
    u64::try_from(value).map_err(|_| error!(MathError::Overflow))
}

pub fn apply_growth(
    p_plus: u128,
    last_price: u128,
    new_price: u128,
    confio_share_bps: u16,
) -> Result<u128> {
    require!(last_price > 0, MathError::DivisionByZero);
    require!(new_price >= last_price, MathError::PriceDecreased);
    let growth = new_price
        .checked_sub(last_price)
        .ok_or(MathError::PriceDecreased)?
        .checked_mul(WAD)
        .ok_or(MathError::Overflow)?
        .checked_div(last_price)
        .ok_or(MathError::DivisionByZero)?;
    let kept = growth
        .checked_mul(BPS - confio_share_bps as u128)
        .ok_or(MathError::Overflow)?
        .checked_div(BPS)
        .ok_or(MathError::DivisionByZero)?;
    let next = p_plus
        .checked_mul(WAD.checked_add(kept).ok_or(MathError::Overflow)?)
        .ok_or(MathError::Overflow)?
        .checked_div(WAD)
        .ok_or_else(|| error!(MathError::DivisionByZero))?;
    require!(next <= u64::MAX as u128, MathError::Overflow);
    Ok(next)
}

#[error_code]
pub enum MathError {
    #[msg("arithmetic overflow")]
    Overflow,
    #[msg("division by zero")]
    DivisionByZero,
    #[msg("price decreased")]
    PriceDecreased,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn applies_holder_share_of_growth() {
        assert_eq!(
            apply_growth(WAD, WAD, 1_010_000_000_000_000_000, 1_500).unwrap(),
            1_008_500_000_000_000_000
        );
    }

    #[test]
    fn round_trip_and_obligation_rounding_favor_backing() {
        let price = 1_143_210_000_000_000_000;
        let p_plus = 1_100_000_000_000_000_000;
        let usdy = 1_000_001;
        let shares = mul_div_down(usdy, price, p_plus).unwrap();
        assert!(mul_div_down(shares, p_plus, price).unwrap() <= usdy);
        assert!(mul_div_up(shares, p_plus, price).unwrap() <= usdy);
    }

    #[test]
    fn rejects_invalid_math() {
        assert!(apply_growth(WAD, WAD, WAD - 1, 1_500).is_err());
        assert!(apply_growth(u64::MAX as u128, WAD, WAD * 2, 0).is_err());
        assert!(mul_div_down(1, WAD, 0).is_err());
    }
}
