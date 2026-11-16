import {
  TOP_UP_DECLINE_REASONS,
  requestTopUpDecline,
  resetTopUpDeclineForTests,
  shuffledDeclineReasons,
  subscribeTopUpDecline,
} from '../guideTopUpDecline';

describe('guideTopUpDecline', () => {
  beforeEach(() => resetTopUpDeclineForTests());

  it('shuffles every answer but keeps "other" last', () => {
    let seed = 0.9;
    const random = () => { seed = (seed * 7.13) % 1; return seed; };
    const firsts = new Set<string>();
    for (let i = 0; i < 20; i += 1) {
      const order = shuffledDeclineReasons(random).map(([id]) => id);
      expect([...order].sort()).toEqual(TOP_UP_DECLINE_REASONS.map(([id]) => id).sort());
      expect(order[order.length - 1]).toBe('other');
      firsts.add(order[0]);
    }
    expect(firsts.size).toBeGreaterThan(1);  // the order really changes
  });

  it('uses only the keys the server accepts', () => {
    // assistant/guide.py TOP_UP_DECLINE_REASONS, minus 'skipped' (the close)
    expect(TOP_UP_DECLINE_REASONS.map(([id]) => id)).toEqual(
      ['no_money', 'trust', 'no_use', 'fees', 'pay_method', 'looking', 'loan', 'other']);
  });

  it('asks only when a host is mounted, and stops after it unmounts', () => {
    expect(requestTopUpDecline()).toBe(false);
    const host = jest.fn();
    const unsubscribe = subscribeTopUpDecline(host);
    expect(requestTopUpDecline()).toBe(true);
    unsubscribe();
    expect(requestTopUpDecline()).toBe(false);
    expect(host).toHaveBeenCalledTimes(1);
  });
});
