import { gql } from '@apollo/client';

// Live traction numbers — same definitions the admin dashboard uses
// (Koywe grey-box on-chain deposited volume; presale raised). Server
// caches 10 min. Callers render NOTHING when live data is absent
// (DESIGN.md: real numbers or nothing — no client-side fallbacks).
export const LANDING_STATS = gql`
  query LandingStats {
    landingStats {
      depositedVolumeUsd
      presaleRaisedUsd
    }
  }
`;

// "US$" not "$": MXN, ARS, CLP, COP all write their own peso as "$",
// so a bare "$" is ambiguous for the LATAM audience (DESIGN.md).
// Amounts FLOOR, never round up — a trust-first money site must not
// advertise more than was actually deposited/raised.
export const fmtAmount = (n, decimals = 0, prefix = 'US$') => {
  const factor = 10 ** decimals;
  const floored = Math.floor(Number(n) * factor) / factor;
  return prefix + floored.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

export const fmtUsd = (n, decimals = 0) => fmtAmount(n, decimals);

// Guard for traction stats: only finite, positive numbers render.
// null/undefined/NaN/Infinity/0 all mean "don't show the stat" —
// a ticking "US$0" or "US$NaN" is worse than no stat at all.
export const toStatValue = (raw) => {
  const n = Math.floor(Number(raw));
  return Number.isFinite(n) && n > 0 ? n : null;
};
