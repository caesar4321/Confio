import { sponsorBscBatch, installBscServerTransport, BscSubmitOutcomeUnknownError } from '../bscServerRpc';
import { FACE_STEP_UP_MESSAGE, registerFaceCheckPresenter } from '../faceStepUp';
import { setBscTransport } from '../evmWallet';
import { apolloClient } from '../../apollo/client';

jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: jest.fn() } }));
jest.mock('../evmWallet', () => ({ setBscTransport: jest.fn() }));

const variables = { calls: [], nonce: '7', deadline: '9999999999', intentSignature: 'signed-intent' };
const capture = jest.fn();
let transport: { submit: (raw: string) => Promise<string> };

beforeAll(() => {
  installBscServerTransport();
  transport = jest.mocked(setBscTransport).mock.calls[0][0] as typeof transport;
});
beforeEach(() => {
  jest.mocked(apolloClient.mutate).mockReset();
  capture.mockReset().mockResolvedValue(true);
  registerFaceCheckPresenter(capture);
});
afterEach(() => registerFaceCheckPresenter(null));

test('sponsorship retries the identical signed intent after Face', async () => {
  jest.mocked(apolloClient.mutate)
    .mockResolvedValueOnce({ data: { sponsorBscBatch: { success: false, error: FACE_STEP_UP_MESSAGE } } } as any)
    .mockResolvedValueOnce({ data: { sponsorBscBatch: { success: true, txHash: 'tx' } } } as any);
  await expect(sponsorBscBatch(variables)).resolves.toMatchObject({ success: true });
  expect(capture).toHaveBeenCalledWith('withdrawal', undefined);
  const calls = jest.mocked(apolloClient.mutate).mock.calls;
  expect(calls[0][0].variables).toBe(variables);
  expect(calls[1][0].variables).toBe(variables);
});

test('cancelling Face is definitive and never broadcasts a retry', async () => {
  capture.mockResolvedValueOnce(false);
  jest.mocked(apolloClient.mutate).mockResolvedValueOnce({
    data: { sponsorBscBatch: { success: false, error: FACE_STEP_UP_MESSAGE } },
  } as any);
  await expect(sponsorBscBatch(variables)).rejects.toMatchObject({ outcome: 'cancelled' });
  expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
});

test('ambiguous transport failures do not open Face or retry', async () => {
  jest.mocked(apolloClient.mutate).mockRejectedValueOnce(new Error('connection lost'));
  await expect(sponsorBscBatch(variables)).rejects.toBeInstanceOf(BscSubmitOutcomeUnknownError);
  expect(capture).not.toHaveBeenCalled();
  expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
});

test('legacy relay retries only the identical signed transaction', async () => {
  jest.mocked(apolloClient.mutate)
    .mockResolvedValueOnce({ data: { submitBscTransaction: { success: false, error: FACE_STEP_UP_MESSAGE } } } as any)
    .mockResolvedValueOnce({ data: { submitBscTransaction: { success: true, txHash: 'tx' } } } as any);
  await expect(transport.submit('signed-raw')).resolves.toBe('tx');
  expect(capture).toHaveBeenCalledTimes(1);
  expect(jest.mocked(apolloClient.mutate).mock.calls.map(args => args[0].variables))
    .toEqual([{ rawTx: 'signed-raw' }, { rawTx: 'signed-raw' }]);
});
