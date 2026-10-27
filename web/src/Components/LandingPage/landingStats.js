import { gql } from '@apollo/client';

// Live traction numbers. "Movido" (fundFlowStats) is the same snapshot the
// admin dashboard shows (ramps.metrics.public_fund_flow_snapshot): every
// deposit and withdrawal of Confío dollars; presale raised. Server caches
// 10 min. Callers render NOTHING when live data is absent
// (DESIGN.md: real numbers or nothing — no client-side fallbacks).
export const LANDING_STATS = gql`
  query LandingStats {
    landingStats {
      presaleRaisedUsd
      registeredUsers
    }
  }
`;

// Money moved through Confío — the app's "Movido" stat, same server snapshot:
// fiat deposits and withdrawals plus direct USDC transfers with on-chain
// proof, each counted once, cumulative since September 2025. Its own query
// so a server without it fails only this stat, never presale/users.
export const FUND_FLOW_STATS = gql`
  query FundFlowStats {
    fundFlowStats {
      totalUsd
      operationCount
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

// Reserves backing every Confío dollar — the app's Ahorros tile, summed
// the same way (legacy cUSD/USDC + cUSD/USDT + cUSD+/USDY). Its own query.
export const RESERVE_STATS = gql`
  query ReserveStats {
    statsSummary {
      totalValueLocked
      protectedSavings
      cusdBscReserve
      usdyReserve
      statsSource
    }
  }
`;

// One unknown part makes the total unknown, never a smaller number. The
// legacy reserve is live only when read from the Algorand app; any other
// source (database_fallback during an outage) is an estimate, not collateral.
export const reserveTotal = (summary) => {
  if (!summary || summary.statsSource !== 'algorand') return null;
  const legacy = summary.totalValueLocked ?? summary.protectedSavings;
  const parts = [legacy, summary.cusdBscReserve, summary.usdyReserve];
  return parts.every((v) => v != null && Number.isFinite(Number(v)))
    ? parts.reduce((sum, v) => sum + Number(v), 0)
    : null;
};

// All-time volume traded in stocks, gold, Bitcoin and futures — the app's
// Invertido tile. Null below the privacy floor. Its own query.
export const INVEST_TRADED_USD = gql`
  query InvestTradedUsd {
    investTradedUsd
  }
`;

// Confío's own fees, server-quoted (DESIGN.md: no hardcoded fees in copy).
// Its own query, like FUND_FLOW_STATS, so a server without it fails alone.
export const PUBLIC_FEES = gql`
  query PublicFees {
    publicFees {
      conversionFeeBps
      payFeeBps
    }
  }
`;

// Basis points from the server, or null when absent/invalid (render nothing).
export const toBps = (raw) => (Number.isInteger(raw) && raw >= 0 && raw <= 10000 ? raw : null);

// 90 -> "0,9%" (es) / "0.9%" (en, ko); 75 -> "0,75%"; 100 -> "1%".
export const fmtBpsPct = (bps, decimal = '.') =>
  `${String(Number((bps / 100).toFixed(2))).replace('.', decimal)}%`;

// Exact cents for the fee examples (US$100 at 90 bps -> "US$0,90").
export const fmtCents = (usd, decimal = '.') => `US$${usd.toFixed(2).replace('.', decimal)}`;
