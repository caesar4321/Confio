import {USD_UNIT} from './rampFormat';

export type WithdrawalSourcePresentation = {
  inputLabel: string;
  unitLabel: string;
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
    // see the + product name above; geo-ineligible users hold raw USDT under
    // the plain Confío Dollar name, while both enter amounts as dollars.
    unitLabel: USD_UNIT,
  };
};
