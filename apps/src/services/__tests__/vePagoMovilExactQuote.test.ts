import { exactQuoteError } from '../vePagoMovilSend';

describe('exactQuoteError', () => {
  it('says a server without bolívar mode only takes dollars', () => {
    for (const message of [
      'Cannot query field "vePagomovilSendExactQuote" on type "Query".',
      'Unknown argument "vesAmount" on field "Mutation.createVePagomovilSend".',
    ]) {
      expect(exactQuoteError(new Error(message))).toBe('Por ahora solo puedes enviar un monto en dólares.');
    }
  });
  it('treats anything else as worth another try', () => {
    expect(exactQuoteError(new Error('Network request failed'))).toBe('No pudimos cotizar este monto. Intenta de nuevo.');
    expect(exactQuoteError(undefined)).toBe('No pudimos cotizar este monto. Intenta de nuevo.');
  });
});
