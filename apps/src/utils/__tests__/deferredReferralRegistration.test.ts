import {
  consumeDeferredReferral,
  formatDeferredReferralError,
} from '../deferredReferralRegistration';

const referral = {
  type: 'referral' as const,
  payload: 'WILBERHL',
  timestamp: 123,
  metadata: { clickId: 'click-1', channel: 'whatsapp' },
};

const setup = (mutationResult: any, currentLink: any = referral) => {
  const dependencies = {
    init: jest.fn().mockResolvedValue(undefined),
    getDeferredLink: jest.fn().mockResolvedValue(currentLink),
    clearDeferredLink: jest.fn().mockResolvedValue(true),
    setReferrer: jest.fn().mockResolvedValue(mutationResult),
    alert: jest.fn(),
  };
  return dependencies;
};

describe('consumeDeferredReferral', () => {
  it('waits for attribution, registers it, and compare-clears the consumed link', async () => {
    const dependencies = setup({ data: { setReferrer: { success: true } } });

    await expect(consumeDeferredReferral(dependencies)).resolves.toBe('success');

    expect(dependencies.init.mock.invocationCallOrder[0]).toBeLessThan(
      dependencies.getDeferredLink.mock.invocationCallOrder[0],
    );
    expect(dependencies.setReferrer).toHaveBeenCalledWith({
      referrerIdentifier: 'WILBERHL',
      attributionData: JSON.stringify({
        clickId: 'click-1',
        channel: 'whatsapp',
        referral_code: 'WILBERHL',
        attach_method: 'deferred_link',
      }),
    });
    expect(dependencies.clearDeferredLink).toHaveBeenCalledWith(referral);
    expect(dependencies.alert).not.toHaveBeenCalled();
  });

  it('does nothing for a missing or non-referral deferred link', async () => {
    const missing = setup({}, null);
    const achievement = setup({}, { ...referral, type: 'achievement' });

    await expect(consumeDeferredReferral(missing)).resolves.toBe('none');
    await expect(consumeDeferredReferral(achievement)).resolves.toBe('none');
    expect(missing.setReferrer).not.toHaveBeenCalled();
    expect(achievement.setReferrer).not.toHaveBeenCalled();
  });

  it('retains rate-limited GraphQL referrals so Home can retry', async () => {
    const dependencies = setup({ errors: [{ message: 'Rate limit: wait 2 minutes' }] });

    await expect(consumeDeferredReferral(dependencies)).resolves.toBe('retry');

    expect(dependencies.clearDeferredLink).not.toHaveBeenCalled();
    expect(dependencies.alert).toHaveBeenCalledWith(
      'Aviso',
      'Has intentado demasiadas veces. Por favor espera 2 minutos antes de intentar nuevamente.',
    );
  });

  it.each([
    ['Invalid referral code', true],
    ['Suspicious referral activity', false],
  ])('discards permanent GraphQL failure: %s', async (message, showsAlert) => {
    const dependencies = setup({ errors: [{ message }] });

    await expect(consumeDeferredReferral(dependencies)).resolves.toBe('discarded');

    expect(dependencies.clearDeferredLink).toHaveBeenCalledWith(referral);
    expect(dependencies.alert).toHaveBeenCalledTimes(showsAlert ? 1 : 0);
  });

  it('keeps unknown GraphQL failures for retry', async () => {
    const dependencies = setup({ errors: [{ message: 'Temporary upstream failure' }] });

    await expect(consumeDeferredReferral(dependencies)).resolves.toBe('retry');
    expect(dependencies.clearDeferredLink).not.toHaveBeenCalled();
    expect(dependencies.alert).toHaveBeenCalledWith('Aviso', 'Temporary upstream failure');
  });

  it.each([
    ['connection unavailable', 'retry', false],
    ['Business accounts cannot be referred', 'discarded', true],
    ['Ya registraste un referidor', 'discarded', true],
  ])('classifies mutation payload failure: %s', async (error, outcome, clears) => {
    const dependencies = setup({ data: { setReferrer: { success: false, error } } });

    await expect(consumeDeferredReferral(dependencies)).resolves.toBe(outcome);

    expect(dependencies.clearDeferredLink).toHaveBeenCalledTimes(clears ? 1 : 0);
    expect(dependencies.alert).toHaveBeenCalledTimes(/Ya registraste/.test(error) ? 0 : 1);
  });

  it('propagates bootstrap and mutation transport failures to Home error handling', async () => {
    const bootstrapFailure = setup({});
    bootstrapFailure.init.mockRejectedValue(new Error('keychain unavailable'));
    await expect(consumeDeferredReferral(bootstrapFailure)).rejects.toThrow('keychain unavailable');

    const mutationFailure = setup({});
    mutationFailure.setReferrer.mockRejectedValue(new Error('network unavailable'));
    await expect(consumeDeferredReferral(mutationFailure)).rejects.toThrow('network unavailable');
  });

  it('formats a singular rate-limit interval', () => {
    expect(formatDeferredReferralError('Rate limit: wait 1 minute')).toContain('1 minuto antes');
  });
});
