import {localPaymentQrRoute} from '../localPaymentQr';

it.each([['BR','br_qr'],['AR','ar_qr'],['CO','co_qr'],['BO','bo_qr'],['PE','pe_qr']])('routes %s as a hint requiring server approval', (country,methodId) => {
  expect(localPaymentQrRoute(`0002015802${country}63040000`)).toEqual({country,methodId});
});
it.each(['confio://pay/123', 'https://confio.lat/pay/123', '0002015802XX63040000',
  '0002015802BR5802AR63040000', '0002015899BR', '000201xx02BR', '000201'+'a'.repeat(4096)])('ignores other or malformed codes', raw => {
  expect(localPaymentQrRoute(raw)).toBeNull();
});
it('recognizes the documented Bolivia encrypted envelope as a routing hint', () => {
  expect(localPaymentQrRoute('K6AEx9BgdJHPb3CfWLKYU9XhoSIRJvRX9Hw|1c8618ba4382fb49')).toEqual({country:'BO',methodId:'bo_qr'});
  expect(localPaymentQrRoute('https://confio.lat/pay/123|1c8618ba4382fb49')).toBeNull();
  expect(localPaymentQrRoute('a'.repeat(33000)+'|1c8618ba4382fb49')).toBeNull();
});
