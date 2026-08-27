import {print} from 'graphql';

import {
  CREATE_RAMP_ORDER,
  CREATE_RAMP_ORDER_SAVINGS,
  selectCreateRampOrderMutation,
} from '../../apollo/mutations';
import {getWithdrawalSourcePresentation} from '../withdrawalRail';

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
