import { returnsPath } from '../returnsChart';

test('maps time to x and the cumulative percent to y, inside the padding', () => {
  const path = returnsPath(
    [
      { at: '2026-10-15T00:00:00Z', pct: '0' },
      { at: '2026-10-16T00:00:00Z', pct: '10' },
      { at: '2026-10-17T00:00:00Z', pct: '-10' },
    ],
    208,
    108,
    4,
  );
  expect(path).toBe('M4.0 54.0 L104.0 4.0 L204.0 104.0');
});

test('a flat line sits in the middle', () => {
  expect(returnsPath([{ at: '2026-10-15T00:00:00Z', pct: '0' }, { at: '2026-10-16T00:00:00Z', pct: '0' }], 108, 108, 4))
    .toBe('M4.0 54.0 L104.0 54.0');
});

test('nothing to draw without two readable points or a width', () => {
  expect(returnsPath([{ at: '2026-10-15T00:00:00Z', pct: '1' }], 100, 100)).toBeNull();
  expect(returnsPath([{ at: 'x', pct: '1' }, { at: '2026-10-15T00:00:00Z', pct: 'y' }], 100, 100)).toBeNull();
  expect(returnsPath([{ at: '2026-10-15T00:00:00Z', pct: '1' }, { at: '2026-10-16T00:00:00Z', pct: '2' }], 0, 100)).toBeNull();
});
