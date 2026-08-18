import { getFriendlyRampError } from '../rampErrors';

describe('getFriendlyRampError', () => {
  it('does not expose Koywe credential errors to the user', () => {
    expect(getFriendlyRampError('Check your credentials')).toBe(
      'El proveedor no pudo autorizar la operación en este momento. No se creó ninguna orden; inténtalo nuevamente en unos minutos.',
    );
  });
});
