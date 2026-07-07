import { fmtUsd, LANDING_STATS } from './landingStats';

// fmtUsd is the single money formatter for landing stats: "US$" prefix
// (a bare "$" is ambiguous across LATAM pesos), en-US grouping, and
// FLOORING to the requested number of decimals (default 0) — a money
// site must never advertise more than was actually deposited/raised.
describe('fmtUsd', () => {
  it('prefixes with US$ and groups thousands en-US style', () => {
    expect(fmtUsd(1234567)).toBe('US$1,234,567');
  });

  it('floors to whole dollars by default (never rounds up money)', () => {
    expect(fmtUsd(125430.75)).toBe('US$125,430');
    expect(fmtUsd(88200.4)).toBe('US$88,200');
  });

  it('formats zero', () => {
    expect(fmtUsd(0)).toBe('US$0');
  });

  it('honors the decimals argument, padding with trailing zeros', () => {
    expect(fmtUsd(3597.7, 2)).toBe('US$3,597.70');
    expect(fmtUsd(1234.567, 2)).toBe('US$1,234.56'); // floored at 2dp, not rounded up
  });

  it('coerces numeric strings (GraphQL decimals arrive as strings)', () => {
    expect(fmtUsd('52642.99')).toBe('US$52,642'); // floored
    expect(fmtUsd('52642.99', 2)).toBe('US$52,642.99');
  });

  it('never falls back to a bare $ prefix', () => {
    expect(fmtUsd(5)).toMatch(/^US\$/);
  });
});

describe('LANDING_STATS query', () => {
  it('requests both traction fields from landingStats', () => {
    const selections = LANDING_STATS.definitions[0].selectionSet.selections[0]
      .selectionSet.selections.map((s) => s.name.value);
    expect(selections).toEqual(
      expect.arrayContaining(['depositedVolumeUsd', 'presaleRaisedUsd'])
    );
  });
});
