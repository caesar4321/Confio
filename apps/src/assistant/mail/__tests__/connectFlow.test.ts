jest.mock('react-native', () => ({ Alert: { alert: jest.fn() } }));
const mockStore: { current: any } = { current: false };
jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'device' },
  getGenericPassword: jest.fn(async () => mockStore.current),
  setGenericPassword: jest.fn(async (username: string, password: string) => {
    mockStore.current = { username, password };
    return true;
  }),
  resetGenericPassword: jest.fn(async () => {
    mockStore.current = false;
    return true;
  }),
}));
jest.mock('@apollo/client', () => ({ gql: () => ({}) }));

import { finishMailConnect } from '../connectFlow';
import { receiveMailConnectLink } from '../connectLink';
import { closeMailSession, mailSession } from '../session';
import { saveVerifier } from '../verifier';

const mutate = jest.fn();
const client: any = { mutate };

beforeEach(async () => {
  mutate.mockReset();
  closeMailSession('7');
  await saveVerifier('7', 'verifier', 'real');
});

it('a planted link cannot use up the attempt', async () => {
  receiveMailConnectLink('confio://gmail-connect?code=x&state=planted');
  await finishMailConnect(client, '7');
  expect(mutate).not.toHaveBeenCalled();
  mutate.mockResolvedValue({ data: { completeAssistantMailConnect: { success: true } } });
  receiveMailConnectLink('confio://gmail-connect?code=c&state=real');
  await finishMailConnect(client, '7');
  expect(mutate.mock.calls[0][0].variables).toEqual({ code: 'c', state: 'real', verifier: 'verifier' });
});

it('the result waits in the session when the lock removed the sheet', async () => {
  mutate.mockResolvedValue({ data: { completeAssistantMailConnect: { success: false, error: 'Falta el permiso' } } });
  mailSession('7').open = true;
  receiveMailConnectLink('confio://gmail-connect?code=c&state=real');
  await finishMailConnect(client, '7');
  expect(mailSession('7').notice).toBe('Falta el permiso');
  expect(mailSession('7').open).toBe(true);
});
