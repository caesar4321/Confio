import {bscscanTokenHoldingsUrl} from '../bscscan';

describe('bscscanTokenHoldingsUrl', () => {
  it('opens the BSC-only token holdings page', () => {
    expect(
      bscscanTokenHoldingsUrl(
        '0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
      ),
    ).toBe(
      'https://bscscan.com/tokenholdings?a=0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
    );
  });

  it('trims a valid address and rejects invalid input', () => {
    expect(
      bscscanTokenHoldingsUrl(
        ' 0x3C29417eb4314155e63d4C7D4507852b87763Ed1 ',
      ),
    ).toBe(
      'https://bscscan.com/tokenholdings?a=0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
    );
    expect(bscscanTokenHoldingsUrl(null)).toBeNull();
    expect(bscscanTokenHoldingsUrl('not-an-address')).toBeNull();
  });
});
