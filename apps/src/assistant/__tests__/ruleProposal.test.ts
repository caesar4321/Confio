const mockNavigate = jest.fn();
const mockQuery = jest.fn();
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...args: unknown[]) => mockNavigate(...args) },
}));
jest.mock('../../apollo/client', () => ({ apolloClient: { query: (...a: unknown[]) => mockQuery(...a) } }));

import { Alert } from 'react-native';
import { openRuleProposal, proposalParams, stepToParams } from '../ruleProposal';
import { GET_ASSISTANT_RULE_PROPOSAL, GET_ASSISTANT_RULE_PROPOSAL_LEGACY } from '../api';

const buy = {
  action: 'create', kind: 'buy', ruleId: null, amountUsd: '70.00', frequency: 'monthly',
  firstRunAt: '2026-12-01T10:00:00+00:00', assetKey: 'stock:SPYon', assetName: 'SPY', sentence: 'Comprar SPY.',
};

const mockAlert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
beforeEach(() => { mockNavigate.mockClear(); mockQuery.mockReset(); mockAlert.mockClear(); });

describe('rule proposal -> rule screen params (data, never authority)', () => {
  it('maps a create step to a prefilled form', () => {
    expect(stepToParams(buy as any)).toEqual({
      kind: 'buy',
      prefill: {
        amountUsd: '70.00', frequency: 'monthly', firstRunAt: '2026-12-01T10:00:00+00:00',
        payeeHandle: undefined, payeeName: undefined, payoutMethodId: undefined, assetKey: 'stock:SPYon', assetName: 'SPY',
      },
      proposal: 'Comprar SPY.',
    });
  });

  it('a cancel step opens the stop confirmation of that rule', () => {
    expect(stepToParams({ action: 'cancel', kind: 'send', ruleId: 'r1', sentence: 'Detener.' } as any))
      .toEqual({ ruleId: 'r1', stop: true, proposal: 'Detener.' });
  });

  it('drops malformed values and unusable steps', () => {
    expect(stepToParams({ ...buy, kind: 'sell' } as any)).toBeNull();
    expect(stepToParams({ ...buy, action: 'update', ruleId: null } as any)).toBeNull();
    expect(stepToParams({ ...buy, amountUsd: '1e9', frequency: 'hourly' } as any)?.prefill)
      .toMatchObject({ amountUsd: undefined, frequency: undefined });
  });

  it('chains several steps, signed one after another', () => {
    const out = proposalParams([buy, { ...buy, assetKey: 'crypto:BTCB', amountUsd: '30.00' }] as any);
    expect(out?.prefill?.assetKey).toBe('stock:SPYon');
    expect(out?.next).toHaveLength(1);
    expect(out?.next?.[0].prefill?.assetKey).toBe('crypto:BTCB');
  });
});

describe('openRuleProposal', () => {
  it('opens the first step from the server', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRuleProposal: { expired: false, steps: [buy] } } });
    await openRuleProposal('42');
    expect(mockQuery.mock.calls[0][0].variables).toEqual({ messageId: '42' });
    expect(mockNavigate).toHaveBeenCalledWith('Main', expect.objectContaining({ screen: 'SmartAccountRuleEdit' }));
  });

  it('an expired proposal or an older server opens the rules list', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRuleProposal: { expired: true, steps: [buy] } } });
    await openRuleProposal('42');
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'SmartAccountRules' });
    mockQuery.mockRejectedValue(new Error('Cannot query field "assistantRuleProposal"'));
    await openRuleProposal('42');
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'SmartAccountRules' });
  });
});

describe('proposal progress (signed steps are skipped)', () => {
  it('tags every step, the chained ones too, with the message and its stepIndex', () => {
    const out = proposalParams([{ ...buy, stepIndex: 1 }, { ...buy, assetKey: 'crypto:BTCB', stepIndex: 2 }] as any, '42');
    expect(out).toMatchObject({ proposalMessageId: '42', proposalStep: 1 });
    expect(out?.next?.[0]).toMatchObject({ proposalMessageId: '42', proposalStep: 2 });
    expect(stepToParams({ action: 'cancel', kind: 'send', ruleId: 'r1', sentence: 'Detener.', stepIndex: 0 } as any, '42'))
      .toEqual({ ruleId: 'r1', stop: true, proposal: 'Detener.', proposalMessageId: '42', proposalStep: 0 });
  });

  it('never tags a step without a stepIndex (an older server) or without a message', () => {
    expect(stepToParams(buy as any, '42')).not.toHaveProperty('proposalStep');
    expect(stepToParams({ ...buy, stepIndex: 0 } as any)).not.toHaveProperty('proposalMessageId');
    expect(stepToParams({ ...buy, stepIndex: -1 } as any, '42')).not.toHaveProperty('proposalStep');
  });

  it('asks for the progress fields and opens the first open step tagged', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRuleProposal: {
      expired: false, done: false, message: null, steps: [{ ...buy, stepIndex: 1 }] } } });
    await openRuleProposal('42');
    expect(mockQuery).toHaveBeenCalledTimes(1);
    expect(mockQuery.mock.calls[0][0].query).toBe(GET_ASSISTANT_RULE_PROPOSAL);
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountRuleEdit',
      params: expect.objectContaining({ kind: 'buy', proposalMessageId: '42', proposalStep: 1 }) });
    expect(mockAlert).not.toHaveBeenCalled();
  });

  it('a plan already signed says so and opens the rules list, never an empty form', async () => {
    const message = 'Ya firmaste este plan. Puedes verlo en tus reglas.';
    mockQuery.mockResolvedValue({ data: { assistantRuleProposal: { expired: false, done: true, message, steps: [] } } });
    await openRuleProposal('42');
    expect(mockAlert).toHaveBeenCalledWith(expect.any(String), message);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'SmartAccountRules' });
    expect(mockNavigate).not.toHaveBeenCalledWith('Main', expect.objectContaining({ screen: 'SmartAccountRuleEdit' }));
  });

  it('a plan the server could not check (no steps, a message) says so too', async () => {
    const message = 'No pudimos revisar este plan. Ábrelo de nuevo en un momento.';
    mockQuery.mockResolvedValue({ data: { assistantRuleProposal: { expired: false, done: false, message, steps: [] } } });
    await openRuleProposal('42');
    expect(mockAlert).toHaveBeenCalledWith(expect.any(String), message);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'SmartAccountRules' });
  });

  it('an older server without the progress fields: asks the old query, opens the step untagged', async () => {
    mockQuery
      .mockRejectedValueOnce(Object.assign(new Error('Cannot query field "done" on type "AssistantRuleProposalType".'),
        { graphQLErrors: [] }))
      .mockResolvedValueOnce({ data: { assistantRuleProposal: { expired: false, steps: [buy] } } });
    await openRuleProposal('42');
    expect(mockQuery).toHaveBeenCalledTimes(2);
    expect(mockQuery.mock.calls[1][0].query).toBe(GET_ASSISTANT_RULE_PROPOSAL_LEGACY);
    const params = mockNavigate.mock.calls[0][1].params;
    expect(params).toMatchObject({ kind: 'buy' });
    expect(params).not.toHaveProperty('proposalStep');
    expect(mockAlert).not.toHaveBeenCalled();
  });

  it('a network failure is not an older server: no second query, the rules list', async () => {
    mockQuery.mockRejectedValue(new Error('Network request failed'));
    await openRuleProposal('42');
    expect(mockQuery).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'SmartAccountRules' });
  });
});
