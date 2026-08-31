import {USD_UNIT} from './rampFormat';

export type WithdrawalSourcePresentation = {
  inputLabel: string;
  unitLabel: string;
};

export type BscWithdrawalAvailability = {
  spendableUsd: number;
  normalizationPending: boolean;
  normalizationRetryable: boolean;
};

/**
 * The BSC off-ramp spends cUSD/cUSD+, never transient raw USDT. Raw USDT is
 * still shown in the unified dollar balance while the foreground conversion
 * runs, but exposing it as withdrawable would route around the cUSD perimeter
 * and produce the server-side "Disponible: 0" failure.
 */
export const getBscWithdrawalAvailability = ({
  enabled,
  cusdPlusUsd,
  cusdUsd,
  rawUsdtUsd,
  normalizationRunning,
}: {
  enabled: boolean;
  cusdPlusUsd: number;
  cusdUsd: number;
  rawUsdtUsd: number;
  normalizationRunning: boolean;
}): BscWithdrawalAvailability => {
  // The relay intentionally leaves $1.000000 and smaller alone: after
  // on-chain rounding it could fall below Ondo's exact $1 redemption floor.
  const normalizationPending = enabled && (
    normalizationRunning || rawUsdtUsd >= 1.000001
  );
  return {
    spendableUsd: Math.max(0, cusdPlusUsd) + Math.max(0, cusdUsd),
    normalizationPending,
    normalizationRetryable: normalizationPending && !normalizationRunning,
  };
};

/** Copy and amount unit for the asset this off-ramp actually spends. */
export const getWithdrawalSourcePresentation = (
  isSavingsRail: boolean,
  savingsEnabled: boolean,
): WithdrawalSourcePresentation => {
  if (!isSavingsRail) {
    return {
      inputLabel: 'Monto a retirar en cUSD',
      unitLabel: 'cUSD',
    };
  }

  return {
    inputLabel: `Monto a retirar desde ${savingsEnabled ? 'Confío Dollar+' : 'Confío Dollar'}`,
    // The balance is a dollar value, not a cUSD+ share count. Eligible users
    // see the + product name above; geo-ineligible users hold cUSD under the
    // plain Confío Dollar name, while both enter amounts as dollars.
    unitLabel: USD_UNIT,
  };
};
