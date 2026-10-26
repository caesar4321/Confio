import { qrImageUri, receiveCopy, sendCopy } from '../boliviaQr';

describe('QR Bolivia helpers', () => {
  it('turns provider QR images into image URIs', () => {
    expect(qrImageUri('iVBOR')).toBe('data:image/png;base64,iVBOR');
    expect(qrImageUri('data:image/png;base64,iVBOR')).toBe('data:image/png;base64,iVBOR');
    expect(qrImageUri('')).toBe('');
  });

  it('describes each receive phase without naming a provider', () => {
    for (const phase of ['qr_ready', 'paid', 'delivering', 'completed', 'expired', 'review', 'failed']) {
      const copy = receiveCopy({ success: true, phase });
      expect(copy.title.length).toBeGreaterThan(0);
      expect(`${copy.title} ${copy.body}`).not.toMatch(/stereum|mesa de pagos/i);
    }
  });

  it('never tells a funded payment it failed', () => {
    expect(sendCopy({ success: true, status: 'PROCESSING', phase: 'payout_review' }).title)
      .toBe('Estamos revisando tu pago');
    expect(sendCopy({ success: true, status: 'COMPLETED', phase: 'paid' }).title).toBe('Pago realizado');
  });
});
