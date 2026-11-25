import { requestActivityShare, resetActivityShareForTests, setActivityShareListener } from '../communityShare';

describe('requestActivityShare', () => {
  beforeEach(() => resetActivityShareForTests());

  it('opens by itself once per reference, and again on a Compartir tap', () => {
    const seen: string[] = [];
    setActivityShareListener(({ reference }) => { seen.push(reference); return true; });
    expect(requestActivityShare({ group: 'stock', reference: '0xabc' })).toBe(true);
    // The sheet opening by itself never repeats...
    expect(requestActivityShare({ group: 'stock', reference: '0xabc' })).toBe(false);
    // ...but the button is never dead (founder, 2026-11-25: "clicking Compartir, nothing happens").
    expect(requestActivityShare({ group: 'stock', reference: '0xabc', again: true })).toBe(true);
    expect(seen).toEqual(['0xabc', '0xabc']);
  });

  it('still needs a reference and a mounted sheet', () => {
    expect(requestActivityShare({ group: 'stock', reference: '0xabc', again: true })).toBe(false);
    setActivityShareListener(() => true);
    expect(requestActivityShare({ group: 'stock', reference: '  ', again: true })).toBe(false);
  });
});
