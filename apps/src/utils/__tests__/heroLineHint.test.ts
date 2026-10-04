/** The cold-launch hint must not stay stale when a Keychain write fails. */
const mockSet = jest.fn();
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(() => Promise.resolve({ password: JSON.stringify({ a: true }) })),
  setGenericPassword: (...args: any[]) => mockSet(...args),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'afu' },
}));

import { hadHeroLine, heroLineHintReady, setHadHeroLine } from '../heroLineHint';

const settle = () => new Promise(r => setTimeout(r, 0));

describe('heroLineHint', () => {
  it('loads the stored hint and retries a failed clear on the next set', async () => {
    await heroLineHintReady;
    expect(hadHeroLine('a')).toBe(true);

    mockSet.mockRejectedValueOnce(new Error('keychain busy'));
    setHadHeroLine('a', false);
    await settle();
    expect(mockSet).toHaveBeenCalledTimes(1);

    mockSet.mockResolvedValueOnce(true);
    setHadHeroLine('a', false); // same answer, still dirty on disk -> retried
    await settle();
    expect(mockSet).toHaveBeenCalledTimes(2);
    expect(JSON.parse(mockSet.mock.calls[1][1])).toEqual({ a: false });

    setHadHeroLine('a', false); // persisted now -> no write
    await settle();
    expect(mockSet).toHaveBeenCalledTimes(2);
  });
});
