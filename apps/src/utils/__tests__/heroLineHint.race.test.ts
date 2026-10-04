/** An answer recorded before the stored hints finish loading is newer and wins. */
let mockRelease!: (v: any) => void;
const mockSet = jest.fn((..._args: any[]) => Promise.resolve(true));
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(() => new Promise(r => { mockRelease = r; })),
  setGenericPassword: (...args: any[]) => mockSet(...args),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'afu' },
}));

import { hadHeroLine, heroLineHintReady, setHadHeroLine } from '../heroLineHint';

it('merges a pre-load answer over stored hints and only writes after loading', async () => {
  setHadHeroLine('a', true); // network answer lands first
  expect(mockSet).not.toHaveBeenCalled(); // never overwrite stored hints blind
  mockRelease({ password: JSON.stringify({ a: false, b: true }) });
  await heroLineHintReady;
  await new Promise(r => setTimeout(r, 0));
  expect(hadHeroLine('a')).toBe(true);
  expect(hadHeroLine('b')).toBe(true);
  expect(JSON.parse(mockSet.mock.calls[0][1])).toEqual({ a: true, b: true });
});

it('an explicit false recorded before loading beats a stored true', async () => {
  // module already loaded above: simulate via a fresh module instance
  jest.resetModules();
  let release!: (v: any) => void;
  jest.doMock('react-native-keychain', () => ({
    getGenericPassword: () => new Promise(r => { release = r; }),
    setGenericPassword: () => Promise.resolve(true),
    ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'afu' },
  }));
  const m = require('../heroLineHint');
  m.setHadHeroLine('c', false);
  release({ password: JSON.stringify({ c: true }) });
  await m.heroLineHintReady;
  expect(m.hadHeroLine('c')).toBe(false);
});

