/**
 * A delegate pays payroll from their PERSONAL account, and the server only
 * runs the send_funds permission check in the BUSINESS branch — so the
 * screen has to switch context before it moves money. These pin WHERE to.
 *
 * The bug this replaces: `ensureBusinessContext` was `async () => true`, so
 * the payout mutation ran under a personal JWT and came back
 * `business_context_required` — a raw code with no Spanish for it.
 */
import { payrollPayAccountFor, isPayrollContextReady } from '../payrollPayContext';

const item = (businessId: string) => ({
  internalId: 'item42',
  run: { business: { id: businessId, name: 'Bodega' } },
});

const PERSONAL = { id: 'personal_0', type: 'personal' };
const BODEGA = { id: 'business_77_0', type: 'business', business: { id: '77' } };
const OTHER = { id: 'business_88_0', type: 'business', business: { id: '88' } };

describe('which account pays a payroll item', () => {
  it('finds the business account that owns the run', () => {
    expect(payrollPayAccountFor(item('77'), [PERSONAL, BODEGA, OTHER])).toBe(BODEGA);
  });

  it('never settles for "some business account"', () => {
    // An employee can be a delegate at more than one business. Paying 77's
    // payroll out of 88's context spends a different company's money.
    expect(payrollPayAccountFor(item('77'), [PERSONAL, OTHER])).toBeNull();
  });

  it('returns null when the delegate holds no business account at all', () => {
    // Reads reach further than writes: the server serves pending items to a
    // delegate who may hold no business account. The screen must say so
    // rather than fail later at the signature.
    expect(payrollPayAccountFor(item('77'), [PERSONAL])).toBeNull();
  });

  it('tolerates numeric ids from GraphQL', () => {
    const numeric = { run: { business: { id: 77 } } };
    expect(payrollPayAccountFor(numeric, [BODEGA])).toBe(BODEGA);
  });

  it('returns null for an item with no business', () => {
    expect(payrollPayAccountFor({ run: {} }, [BODEGA])).toBeNull();
    expect(payrollPayAccountFor(null, [BODEGA])).toBeNull();
  });
});

describe('whether the active context can already pay', () => {
  it('is NOT ready in the delegate’s personal account', () => {
    // The exact state that produced business_context_required.
    expect(isPayrollContextReady(item('77'), PERSONAL)).toBe(false);
  });

  it('is ready in the matching business account', () => {
    expect(isPayrollContextReady(item('77'), BODEGA)).toBe(true);
  });

  it('is NOT ready in a DIFFERENT business account', () => {
    expect(isPayrollContextReady(item('77'), OTHER)).toBe(false);
  });

  it('is not ready without an active account', () => {
    expect(isPayrollContextReady(item('77'), null)).toBe(false);
  });
});
