import { getReceiveRails, getSendRails } from '../../config/localRails';

// RouteSheet keys each row by `id ?? title`. Titles alone are NOT unique —
// six rails are called "Cuenta bancaria" — and duplicate React keys make the
// list reuse the wrong row's state. They were accidentally unique only while
// every title had a flag emoji glued to its front; splitting the flag into its
// own cell (to fix Android alignment) removed that accident.
describe('rail rows carry keys that are actually unique', () => {
  it('has duplicate titles, which is exactly why ids are required', () => {
    const titles = getSendRails(null).map(r => r.title);
    expect(new Set(titles).size).toBeLessThan(titles.length);
  });

  it('keys every row uniquely within each sheet', () => {
    for (const rails of [getSendRails(null), getReceiveRails(null)]) {
      const keys = rails.map(r => r.id ?? r.title);
      expect(new Set(keys).size).toBe(rails.length);
    }
  });
});
