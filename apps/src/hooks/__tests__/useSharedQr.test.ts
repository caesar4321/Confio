
import { parseSharedQrUrl } from '../useSharedQr';

const PIX = '00020101021226800014br.gov.bcb.pix2558pix.example.com/qr/v2/cob/4d8f'
  + '5204000053039865802BR5915INFINIA SANDBOX6009SAO PAULO62070503***63044C26';

describe('parseSharedQrUrl', () => {
  it('reads the QR the share extension hands over', () => {
    expect(parseSharedQrUrl(`confio://shared-qr?p=${encodeURIComponent(PIX)}`)).toBe(PIX);
    expect(parseSharedQrUrl(`Confio://shared-qr/?x=1&p=${encodeURIComponent(PIX)}`)).toBe(PIX);
  });

  it('ignores every other link and malformed or oversized payloads', () => {
    for (const url of [null, '', 'confio://pay/123', 'https://confio.lat/shared-qr?p=abc',
      'confio://shared-qr?q=abc', 'confio://shared-qr?p=', 'confio://shared-qr?p=%E0%A4%A',
      `confio://shared-qr?p=${'a'.repeat(4097)}`]) {
      expect(parseSharedQrUrl(url)).toBeNull();
    }
  });
});
