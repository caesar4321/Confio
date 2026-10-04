jest.mock('../credentialStorage', () => ({credentialStorage:{retrieveSecretStrict:jest.fn(), storeSecret:jest.fn(), deleteSecret:jest.fn()}}));
import {credentialStorage} from '../credentialStorage';
import {validBobAmount, qrRequestId, readPendingQr, savePendingQr} from '../stereumQr';
it.each(['0','-1','1.001','NaN','1e2','69000.01',''])('rejects invalid BOB amount %s', value => expect(validBobAmount(value)).toBe(false));
it.each(['1','1,50','69000.00'])('accepts BOB amount %s', value => expect(validBobAmount(value)).toBe(true));
it('generates canonical UUIDs and journals under the selected account', async () => {
  const id = qrRequestId();
  expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  await savePendingQr('a',id);
  expect(credentialStorage.storeSecret).toHaveBeenCalledWith('confio.stereum.qr.pending.a',new TextEncoder().encode(id));
  (credentialStorage.retrieveSecretStrict as jest.Mock).mockResolvedValue(new TextEncoder().encode(id));
  expect(await readPendingQr('a')).toBe(id);
});
it('does not mistake unreadable recovery storage for absence', async () => {
  (credentialStorage.retrieveSecretStrict as jest.Mock).mockRejectedValue(new Error('unreadable'));
  await expect(readPendingQr('a')).rejects.toThrow('unreadable');
});
