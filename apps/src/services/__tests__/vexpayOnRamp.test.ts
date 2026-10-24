import { isoDaysAgo, isOrderRegression, parseDayMonthYear, vexpayProgressCopy } from '../vexpayOnRamp';

describe('vexpayProgressCopy', () => {
  it('never shows a failure for money that is under review', () => {
    const copy = vexpayProgressCopy({ success: true, status: 'PROCESSING', statusDetail: 'needs_review:onward_held:x' });
    expect(copy.title).toBe('Estamos revisando tu recarga');
    expect(copy.body).toContain('no hagas otro pago');
  });

  it('explains the release hold', () => {
    expect(vexpayProgressCopy({ success: true, status: 'PROCESSING', statusDetail: 'onward_waiting_release' }).body)
      .toContain('unas horas');
  });

  it('distinguishes an expired unpaid order from a failed payment', () => {
    expect(vexpayProgressCopy({ success: true, status: 'FAILED', statusDetail: 'expired_unpaid' }).title)
      .toBe('La recarga expiró');
    expect(vexpayProgressCopy({ success: true, status: 'FAILED', statusDetail: 'payment_failed:51' }).title)
      .toBe('La recarga no se completó');
  });

  it('a sent charge is never shown as waiting for payment', () => {
    expect(vexpayProgressCopy({ success: true, status: 'PROCESSING', statusDetail: 'bank_confirming' }).title)
      .toBe('Confirmando tu pago');
    expect(vexpayProgressCopy({ success: true, status: 'PROCESSING', statusDetail: 'c2p_execute_ambiguous' }).body)
      .toContain('No hagas otro pago');
  });

  it('shows a user cancellation as such', () => {
    expect(vexpayProgressCopy({ success: true, status: 'FAILED', statusDetail: 'cancelled_by_user' }).title)
      .toBe('Recarga cancelada');
  });

  it('completes only once the dollars are credited', () => {
    expect(vexpayProgressCopy({ success: true, status: 'COMPLETED', statusDetail: 'delivered' }).title)
      .toBe('Pago enviado a tu cuenta');
    expect(vexpayProgressCopy({ success: true, status: 'COMPLETED', statusDetail: 'delivered', deliveredUsdt: '19.5' }).title)
      .toBe('Recarga completada');
  });
});

describe('isOrderRegression', () => {
  const base = { success: true, orderId: 'o1' };
  it('rejects a stale PENDING after PROCESSING', () => {
    expect(isOrderRegression({ ...base, status: 'PROCESSING' }, { ...base, status: 'PENDING', canConfirm: true })).toBe(true);
  });
  it('accepts the server returning an unmatched verification to the form', () => {
    expect(isOrderRegression({ ...base, status: 'PROCESSING' },
      { ...base, status: 'PENDING', canConfirm: true, statusDetail: 'verify_movement_not_found' })).toBe(false);
  });
  it('lets a released claim or a finished preparation reopen the form', () => {
    expect(isOrderRegression({ ...base, status: 'PENDING', canConfirm: false }, { ...base, status: 'PENDING', canConfirm: true })).toBe(false);
  });
  it('accepts forward moves and other orders', () => {
    expect(isOrderRegression({ ...base, status: 'PENDING' }, { ...base, status: 'COMPLETED' })).toBe(false);
    expect(isOrderRegression({ ...base, status: 'COMPLETED' }, { success: true, orderId: 'o2', status: 'PENDING' })).toBe(false);
  });
});

describe('payment dates', () => {
  it('formats days ago in local time', () => {
    expect(isoDaysAgo(1, new Date(2026, 0, 1, 10))).toBe('2025-12-31');
  });
  it('parses DD/MM/AAAA', () => {
    expect(parseDayMonthYear('3/9/2026')).toBe('2026-09-03');
    expect(parseDayMonthYear('2026-09-03')).toBeNull();
  });
});
