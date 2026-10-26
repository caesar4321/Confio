// The app binds its signatures to the Relay order it fetched itself: Relay's
// recorded quotes (the same ones the server tests bind) pass, and any order
// that pays someone else, or carries other terms, is refused.
import { bindDepositQuote, bindReturnQuote } from '../relayQuotes';

const quotes = require('./fixtures/relayQuotes.json');
const ME = '0x1111111111111111111111111111111111111111';
const OTHER = '0x' + '99'.repeat(20);
const copy = (v: unknown) => JSON.parse(JSON.stringify(v));

describe('deposit (BSC → HyperCore)', () => {
  // The recorded order's own deadline: the clock is set to when it was quoted.
  beforeEach(() => { jest.spyOn(Date, 'now').mockReturnValue(1792971607000); });
  afterEach(() => { jest.restoreAllMocks(); });
  it('refuses an order past its own signed deadline', () => {
    (Date.now as jest.Mock).mockReturnValue(quotes.out.protocol.v2.orderData.output.deadline * 1000);
    expect(() => bindDepositQuote(copy(quotes.out), ME, 20n * 10n ** 18n)).toThrow(/expired/);
  });
  it('binds the one deposit call the order allows', () => {
    const bound = bindDepositQuote(copy(quotes.out), ME, 20n * 10n ** 18n);
    expect(bound.depository).toBe('0x4cd00e387622c35bddb9b4c962c136462338bc31');
    expect(bound.depositData.startsWith('0xe8017952')).toBe(true);
    expect(bound.depositData.endsWith(bound.orderId.slice(2))).toBe(true);
    const relays = quotes.out.steps.find((s: any) => s.id === 'deposit').items[0].data.data.toLowerCase();
    expect(bound.depositData).toBe(relays); // byte for byte Relay's own call
  });
  it.each([
    ['a payout to someone else', (q: any) => { q.protocol.v2.orderData.output.payments[0].recipient = OTHER; }],
    ['a recipient other than the member', (q: any) => { q.details.recipient = OTHER; }],
    ['a refund to someone else', (q: any) => { q.protocol.v2.orderData.inputs[0].refunds[0].recipient = OTHER; }],
    ['another depository', (q: any) => { q.protocol.v2.paymentDetails.depository = OTHER; }],
    ['extra calls on the output', (q: any) => { q.protocol.v2.orderData.output.calls = [{ to: OTHER }]; }],
  ])('refuses %s', (_label, mutate) => {
    const q = copy(quotes.out);
    mutate(q);
    expect(() => bindDepositQuote(q, ME, 20n * 10n ** 18n)).toThrow();
  });
  it('refuses another amount than asked', () => {
    expect(() => bindDepositQuote(copy(quotes.out), ME, 21n * 10n ** 18n)).toThrow();
  });
});

describe('return (HyperCore → BSC)', () => {
  // The recorded quote's nonce is a timestamp from when it was recorded.
  const quotedAt = quotes.back.steps[0].items[0].data.sign.value.nonce;
  beforeEach(() => { jest.spyOn(Date, 'now').mockReturnValue(quotedAt); });
  afterEach(() => { jest.restoreAllMocks(); });
  it('refuses a nonce far from now (it could never be retired)', () => {
    (Date.now as jest.Mock).mockReturnValue(quotedAt - 365 * 24 * 3600 * 1000);
    expect(() => bindReturnQuote(copy(quotes.back), ME, 20n * 10n ** 8n)).toThrow();
  });
  it('binds the nonce mapping and the withdrawal', () => {
    const bound = bindReturnQuote(copy(quotes.back), ME, 20n * 10n ** 8n);
    expect(bound.destination).toBe('0x66cf0aace1b4e562593bec10ec7868fba9932224');
    expect(Number.isSafeInteger(bound.nonce)).toBe(true);
  });
  it.each([
    ['a withdrawal to someone else', (q: any) => { q.steps[1].items[0].data.action.parameters.destination = OTHER; }],
    ['a mapping for another depositor', (q: any) => { q.steps[0].items[0].data.sign.value.depositor = OTHER; }],
    ['another nonce on the transfer', (q: any) => { q.steps[1].items[0].data.action.parameters.nonce = 1; }],
    ['a payout to someone else', (q: any) => { q.protocol.v2.orderData.output.payments[0].recipient = OTHER; }],
  ])('refuses %s', (_label, mutate) => {
    const q = copy(quotes.back);
    mutate(q);
    expect(() => bindReturnQuote(q, ME, 20n * 10n ** 8n)).toThrow();
  });
});

describe('the order itself', () => {
  beforeEach(() => { jest.spyOn(Date, 'now').mockReturnValue(1792971607000); });
  afterEach(() => { jest.restoreAllMocks(); });
  const { relayOrderId } = jest.requireActual('../relayQuotes') as typeof import('../relayQuotes');
  it('the order id is the EIP-712 hash of its terms (Relay\'s own derivation)', () => {
    expect(relayOrderId(quotes.out.protocol.v2.orderData)).toBe(quotes.out.protocol.v2.orderId);
    expect(relayOrderId(quotes.back.protocol.v2.orderData)).toBe(quotes.back.protocol.v2.orderId);
  });
  it('a self-made order hashed correctly but not signed by Relay\'s solver is refused', () => {
    const q = copy(quotes.out);
    q.protocol.v2.orderData.output.payments[0].expectedAmount = '1000000000000000000000';
    q.protocol.v2.orderId = relayOrderId(q.protocol.v2.orderData);
    expect(() => bindDepositQuote(q, ME, 20n * 10n ** 18n)).toThrow(/not signed|amount|output/);
  });
});
