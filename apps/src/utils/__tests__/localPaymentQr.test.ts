import {localPaymentQrRoute} from '../localPaymentQr';

it.each([['BR','br_qr'],['AR','ar_qr'],['PE','pe_qr']])('routes %s as a hint requiring server approval', (country,methodId) => {
  expect(localPaymentQrRoute(`0002015802${country}63040000`)).toEqual({country,methodId});
});
it.each(['confio://pay/123', 'https://confio.lat/pay/123', '0002015802CO63040000',
  '0002015802BR5802AR63040000', '0002015899BR', '000201xx02BR', '000201'+'a'.repeat(4096)])('ignores other or malformed codes', raw => {
  expect(localPaymentQrRoute(raw)).toBeNull();
});
