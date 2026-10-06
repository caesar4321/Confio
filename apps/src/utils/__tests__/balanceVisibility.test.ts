const mockGet = jest.fn();
jest.mock('react-native-keychain', () => ({ getInternetCredentials: (...a: any[]) => mockGet(...a) }));

import { isBalanceHidden, loadSavedBalanceVisibility } from '../balanceVisibility';

const saved = (password: string, username = 'balance_visibility') => mockGet.mockResolvedValue({ username, password });

it('reads Home\'s saved choice with Home\'s rule (visible only when saved "true")', async () => {
  saved('true');
  expect(await loadSavedBalanceVisibility()).toBe(true);
  expect(await isBalanceHidden()).toBe(false);
  saved('false');
  expect(await loadSavedBalanceVisibility()).toBe(false);
  expect(await isBalanceHidden()).toBe(true);
});

it('no saved choice or an unreadable keychain reads as visible', async () => {
  mockGet.mockResolvedValue(false);
  expect(await loadSavedBalanceVisibility()).toBeNull();
  expect(await isBalanceHidden()).toBe(false);
  saved('false', 'other_key');
  expect(await loadSavedBalanceVisibility()).toBeNull();
  mockGet.mockRejectedValue(new Error('locked'));
  await expect(loadSavedBalanceVisibility()).rejects.toThrow('locked');
  expect(await isBalanceHidden()).toBe(false);
});
