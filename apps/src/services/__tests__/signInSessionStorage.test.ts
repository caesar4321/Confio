jest.mock('react-native-keychain', () => ({
  setGenericPassword: jest.fn(), getGenericPassword: jest.fn(),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
}));
jest.mock('../../apollo/client', () => ({ AUTH_KEYCHAIN_SERVICE: 'auth', AUTH_KEYCHAIN_USERNAME: 'tokens' }));
import * as Keychain from 'react-native-keychain';
import { persistSignInSession } from '../signInSessionStorage';

beforeEach(() => {
  jest.resetAllMocks();
  (Keychain.setGenericPassword as jest.Mock).mockResolvedValue(true);
  (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({ password: JSON.stringify({ accessToken: 'new', refreshToken: 'refresh' }) });
});

it('verifies the exact fresh credentials before finishing sign-in', async () => {
  await expect(persistSignInSession('new', 'refresh')).resolves.toBeUndefined();
  expect(Keychain.getGenericPassword).toHaveBeenCalledWith({ service: 'auth' });
});
it('fails sign-in on a false Keychain write', async () => {
  (Keychain.setGenericPassword as jest.Mock).mockResolvedValueOnce(false);
  await expect(persistSignInSession('new', 'refresh')).rejects.toThrow('Failed to store');
});
it('fails sign-in on a rejected Keychain write', async () => {
  (Keychain.setGenericPassword as jest.Mock).mockRejectedValueOnce(new Error('locked'));
  await expect(persistSignInSession('new', 'refresh')).rejects.toThrow('locked');
});
it.each([false, { password: '{}' }, { password: 'broken' }, { password: JSON.stringify({ accessToken: 'old', refreshToken: 'refresh' }) }])(
  'fails sign-in when the readback is absent, malformed or stale (%j)', async value => {
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValueOnce(value);
    await expect(persistSignInSession('new', 'refresh')).rejects.toThrow('Failed to verify');
  },
);

it('rejects the nonempty empty-token JSON left by pre-reconciliation invalidation', async () => {
  (Keychain.getGenericPassword as jest.Mock).mockResolvedValueOnce({
    password: JSON.stringify({ accessToken: '', refreshToken: '' }),
  });
  await expect(persistSignInSession('new', 'refresh')).rejects.toThrow('Failed to verify sign-in session');
});
