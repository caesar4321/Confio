import { exactSurplusNote } from '../paymentIntentNotes';

describe('exactSurplusNote', () => {
  it('says where the spare of an exact payment goes', () => {
    expect(exactSurplusNote({ amountExact: true, family: 'local_transfer' })).toMatch(/queda en tu cuenta/);
    expect(exactSurplusNote({ amountExact: true, family: 'ramp_order', methodId: 've_pagomovil_send' })).toMatch(/no se devuelve/);
  });
  it('says nothing where there is no spare to explain', () => {
    expect(exactSurplusNote({ amountExact: false, family: 'local_transfer' })).toBe('');
    expect(exactSurplusNote({ amountExact: true, family: 'local_charge' })).toBe('');
    expect(exactSurplusNote({ amountExact: true, family: 'ramp_order', methodId: 'bo_qr' })).toBe('');
  });
});
