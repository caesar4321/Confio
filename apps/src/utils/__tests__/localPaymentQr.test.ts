import {fixedQrAmountHint, localPaymentQrRoute, pixChargeHint} from '../localPaymentQr';

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

describe('fixedQrAmountHint', () => {
  const breb = (extra: string) => `0002010102122629` + '0014CO.COM.RBM.LLA0407@tienda' + `5303170${extra}5802CO5906TIENDA63040000`;
  it('marks Bre-B and Argentine peso QRs that name their own amount', () => {
    expect(fixedQrAmountHint(breb('540525000'))).toBe(true);
    expect(fixedQrAmountHint('0002015303032540550.005802AR63040000')).toBe(true);
  });
  it('leaves open QRs and other countries to the typed amount', () => {
    expect(fixedQrAmountHint(breb(''))).toBe(false);
    expect(fixedQrAmountHint('0002015303032' + '5802AR63040000')).toBe(false);
    expect(fixedQrAmountHint('0002015303986540550.005802BR63040000')).toBe(false);
    expect(fixedQrAmountHint('not a qr')).toBe(false);
  });
});

describe('pixChargeHint', () => {
  // Infinia sandbox codes: a dynamic charge (field 25) and a static code with an amount (field 54).
  const dynamic = '00020101021226800014br.gov.bcb.pix2558pix.example.com/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783'
    + '5204000053039865802BR5915INFINIA SANDBOX6009SAO PAULO62070503***63044C26';
  const staticAmount = '00020126450014br.gov.bcb.pix0123anasilva@infiniaweb.com5204000053039865406150.005802BR'
    + '5909ANA SILVA6009SAO PAULO62200516INFINIASANDBOX016304BB9A';
  const open = '00020126580014br.gov.bcb.pix01369b1c3f6e-2a47-4d1b-8c5e-7f0a2d3b4c5d5204000053039865802BR'
    + '5914LUCAS OLIVEIRA6014RIO DE JANEIRO62070503***63047682';
  it('marks codes that name their own amount', () => {
    expect(pixChargeHint(dynamic)).toBe(true);
    expect(pixChargeHint(staticAmount)).toBe(true);
  });
  it('leaves open codes and other countries to the typed amount', () => {
    expect(pixChargeHint(open)).toBe(false);
    expect(pixChargeHint('0002015802AR5406100.0063040000')).toBe(false);
    expect(pixChargeHint('not a qr')).toBe(false);
  });
});
