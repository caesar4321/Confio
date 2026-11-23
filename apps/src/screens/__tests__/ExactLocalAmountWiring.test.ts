const {readFileSync} = require('fs');
const {resolve} = require('path');
declare const __dirname: string;
export {};

// The screens' exact-amount wiring, read from their source (as the other
// screen-boundary tests here do): what is signed is what was reviewed.
const screen = (name: string) => readFileSync(resolve(__dirname, `../${name}.tsx`), 'utf8');

describe('exact local amounts on Pagar', () => {
  const source = screen('LocalSendScreen');
  it('binds the review to the exact amount and sends it with the journey', () => {
    expect(source).toContain('const sentExact = exactLocal || (brebCharge ? pixCharge!.amount : \'\');');
    expect(source).toContain('exactLocal: sentExact };');
    expect(source).toContain('reviewStillMatches(reviewedFor, { amount: normalizedAmount, destinationId: destination.id, exactLocal: sentExact })');
    expect(source).toContain('...(reviewedFor.exactLocal ? { exactLocalAmount: reviewedFor.exactLocal } : {})');
  });
  it('can continue only with the dollars priced for the exact amount', () => {
    expect(source).toMatch(/!localMode \|\| chargeExpected \|\| \(Boolean\(destination\) && Boolean\(exactSend\) && amount === exactSend!\.totalUsd/);
    expect(source).toContain('setExactRetry((n) => n + 1);');
  });
});

describe('exact bolívares on Pago Móvil', () => {
  const source = screen('VePagoMovilSendScreen');
  it('asks for the exact quote and sends the bolívares with the order', () => {
    expect(source).toContain('VE_SEND_EXACT_QUOTE');
    expect(source).toContain('mutation: vesMode ? CREATE_VE_EXACT_SEND : CREATE_VE_SEND');
    expect(source).toContain("...(vesMode ? { vesAmount: toNumber(vesAmount).toFixed(2) } : {})");
    expect(source).toContain('&& (!vesMode || Number(quote.estimatedVes) === toNumber(vesAmount));');
  });
  it('says an exact order lands exactly, from its own query', () => {
    expect(source).toContain("orderExactVes ? 'Llegan exactamente' : 'Llegan aprox.'");
    expect(source).toContain('query: VE_SEND_EXACT');
  });
  it('prices again when the server says the price moved', () => {
    expect(source).toContain('setQuoteRetry(n => n + 1)');
    expect(source).toContain('[amount, vesAmount, vesMode, client, order, quoteRetry]');
  });
});
