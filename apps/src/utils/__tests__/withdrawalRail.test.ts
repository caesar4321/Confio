import {print} from 'graphql';

import {
  CREATE_RAMP_ORDER,
  CREATE_RAMP_ORDER_SAVINGS,
  selectCreateRampOrderMutation,
} from '../../apollo/mutations';
import {
  getBscWithdrawalAvailability,
  getWithdrawalSourcePresentation,
} from '../withdrawalRail';

describe('withdrawal rail selection', () => {
  it('uses the destination-aware mutation for a savings withdrawal', () => {
    const document = selectCreateRampOrderMutation(true);

    expect(document).toBe(CREATE_RAMP_ORDER_SAVINGS);
    expect(print(document)).toContain('$destination: String!');
    expect(print(document)).toContain('destination: $destination');
  });

  it('keeps the legacy mutation isolated from the savings-only argument', () => {
    const document = selectCreateRampOrderMutation(false);

    expect(document).toBe(CREATE_RAMP_ORDER);
    expect(print(document)).not.toContain('destination: $destination');
  });
});

describe('withdrawal source presentation', () => {
  it('names eligible savings as Confío Dollar+ without calling it cUSD', () => {
    expect(getWithdrawalSourcePresentation(true, true)).toEqual({
      inputLabel: 'Monto a retirar desde Confío Dollar+',
      unitLabel: 'US$',
    });
  });

  it('names an ineligible raw-USDT balance as Confío Dollar', () => {
    expect(getWithdrawalSourcePresentation(true, false)).toEqual({
      inputLabel: 'Monto a retirar desde Confío Dollar',
      unitLabel: 'US$',
    });
  });

  it('preserves the legacy cUSD presentation', () => {
    expect(getWithdrawalSourcePresentation(false, true)).toEqual({
      inputLabel: 'Monto a retirar en cUSD',
      unitLabel: 'cUSD',
    });
  });
});

describe('BSC withdrawal availability', () => {
  it('does not expose raw USDT as directly withdrawable after the cUSD perimeter launches', () => {
    expect(getBscWithdrawalAvailability({
      enabled: true,
      cusdPlusUsd: 0,
      cusdUsd: 0,
      rawUsdtUsd: 182.41,
      normalizationRunning: false,
    })).toEqual({
      spendableUsd: 0,
      normalizationPending: true,
      normalizationRetryable: true,
    });
  });

  it('routes an Ondo-ineligible holder through universal cUSD-BSC', () => {
    expect(getBscWithdrawalAvailability({
      enabled: true,
      cusdPlusUsd: 0,
      cusdUsd: 180.77,
      rawUsdtUsd: 0,
      normalizationRunning: false,
    })).toEqual({
      spendableUsd: 180.77,
      normalizationPending: false,
      normalizationRetryable: false,
    });
  });

  it('does not wait forever on the intentional one-dollar USDT remainder', () => {
    expect(getBscWithdrawalAvailability({
      enabled: true,
      cusdPlusUsd: 12,
      cusdUsd: 3,
      rawUsdtUsd: 1,
      normalizationRunning: false,
    })).toEqual({
      spendableUsd: 15,
      normalizationPending: false,
      normalizationRetryable: false,
    });
  });

  it('does not block the legacy Algorand rail for unrelated BSC USDT', () => {
    expect(getBscWithdrawalAvailability({
      enabled: false,
      cusdPlusUsd: 0,
      cusdUsd: 0,
      rawUsdtUsd: 182.41,
      normalizationRunning: true,
    }).normalizationPending).toBe(false);
  });

  it('offers retry only after pending normalization is no longer running', () => {
    expect(getBscWithdrawalAvailability({
      enabled: true,
      cusdPlusUsd: 0,
      cusdUsd: 0,
      rawUsdtUsd: 182.41,
      normalizationRunning: true,
    }).normalizationRetryable).toBe(false);
  });
});
