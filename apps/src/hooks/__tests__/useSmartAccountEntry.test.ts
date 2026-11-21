jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ addListener: () => () => {} }) }));
jest.mock('../../services/smartAccount', () => ({
  fetchSmartAccountEntry: jest.fn(),
  fetchSmartAccountOfferGate: jest.fn(),
  fetchBeneficiaryDesignations: jest.fn(),
  // The real predicate: an expired account is not a subscriber.
  isSmartAccountOpen: (s: string) => jest.requireActual('../../services/smartAccount').isSmartAccountOpen(s),
}));
const mockOffline = jest.fn();
jest.mock('../../services/smartAccountDirect', () => ({ loadOfflineDesignations: () => mockOffline() }));
import { distinctOpenDesignations, pickDesignation, smartEntryTarget } from '../useSmartAccountEntry';
import { designation } from '../../components/smartAccount/testing/fixtures';

const claim = (state: string) => ({
  state, initiatedAt: '2026-01-01T00:00:00Z', executableAt: '2026-07-01T00:00:00Z', cancelledAt: null, executedAt: null,
});

describe('where the Cuenta inteligente wallet row goes', () => {
  it('a subscriber opens the account', () => {
    expect(smartEntryTarget(true, true, null)).toEqual({ screen: 'SmartAccountHome' });
  });

  it('someone who may subscribe opens the sign-up', () => {
    expect(smartEntryTarget(false, true, designation())).toEqual({ screen: 'SmartAccountOffer', params: { door: 'billeteras' } });
  });

  it('an accepted beneficiary who could also subscribe still opens the claim', () => {
    expect(smartEntryTarget(false, true, designation({ state: 'active' })))
      .toEqual({ screen: 'BeneficiaryClaim', params: { designationId: 'd1' } });
    expect(smartEntryTarget(false, true, designation({ state: 'active', claim: claim('executable') })))
      .toEqual({ screen: 'BeneficiaryClaimStatus', params: { designationId: 'd1' } });
  });

  it('a named person who cannot subscribe opens their invitation or claim', () => {
    expect(smartEntryTarget(false, false, designation())).toEqual({ screen: 'BeneficiaryInvite', params: { designationId: 'd1' } });
    expect(smartEntryTarget(false, false, designation({ state: 'active' }))).toEqual({ screen: 'BeneficiaryClaim', params: { designationId: 'd1' } });
    expect(smartEntryTarget(false, false, designation({ state: 'active', claim: claim('pending') })))
      .toEqual({ screen: 'BeneficiaryClaimStatus', params: { designationId: 'd1' } });
  });

  it('with the server list unreadable, a remembered designation still opens the claim with its address', () => {
    expect(smartEntryTarget(false, false, null, { designationId: 'd9', account: '0xabc' }))
      .toEqual({ screen: 'BeneficiaryClaim', params: { designationId: 'd9', account: '0xabc' } });
    // A server answer always wins over the device record.
    expect(smartEntryTarget(false, false, designation(), { designationId: 'd9', account: '0xabc' }))
      .toEqual({ screen: 'BeneficiaryInvite', params: { designationId: 'd1' } });
  });

  it('two or more open designations open the list of all of them', () => {
    const LIST = { screen: 'BeneficiaryDesignations' };
    expect(smartEntryTarget(false, false, designation(), null, 2)).toEqual(LIST);
    expect(smartEntryTarget(false, true, designation({ state: 'active' }), null, 3)).toEqual(LIST);
    // Only pending invitations and a possible sign-up: the offer, as with one.
    expect(smartEntryTarget(false, true, designation(), null, 2)).toEqual({ screen: 'SmartAccountOffer', params: { door: 'billeteras' } });
    // A subscriber still opens the own account.
    expect(smartEntryTarget(true, false, designation(), null, 2)).toEqual({ screen: 'SmartAccountHome' });
  });

  it('everyone else keeps the probe pitch', () => {
    expect(smartEntryTarget(false, false, null)).toBeNull();
  });
});

describe('useSmartAccountEntry with the server down', () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const React = require('react');
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const renderer = require('react-test-renderer');
  const api = require('../../services/smartAccount');
  const flushAll = async () => { for (let i = 0; i < 5; i++) { await renderer.act(async () => { await Promise.resolve(); }); } };

  it('reads the device record only when the designations read fails, and routes to the claim', async () => {
    const { useSmartAccountEntry } = require('../useSmartAccountEntry');
    api.fetchSmartAccountEntry.mockResolvedValue({ ok: false });
    api.fetchSmartAccountOfferGate.mockResolvedValue({ ok: false });
    api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: false });
    mockOffline.mockResolvedValue([{ account: '0xabc', designationId: 'd7', ownerName: 'Luis', savedAt: 1 }]);
    let state: any;
    const Probe = () => { state = useSmartAccountEntry(true); return null; };
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(state.offlineDesignation).toMatchObject({ designationId: 'd7' });
    expect(state.target).toEqual({ screen: 'BeneficiaryClaim', params: { designationId: 'd7', account: '0xabc' } });
  });

  it('ignores the device record when the server answers', async () => {
    const { useSmartAccountEntry } = require('../useSmartAccountEntry');
    mockOffline.mockClear();
    api.fetchSmartAccountEntry.mockResolvedValue({ ok: true, data: null });
    api.fetchSmartAccountOfferGate.mockResolvedValue({ ok: true, data: null });
    api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: true, data: [] });
    let state: any;
    const Probe = () => { state = useSmartAccountEntry(true); return null; };
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(mockOffline).not.toHaveBeenCalled();
    expect(state.target).toBeNull();
  });

  it('an expired (cancelled and returned) account is not a subscriber: the row opens the offer', async () => {
    const { useSmartAccountEntry } = require('../useSmartAccountEntry');
    api.fetchSmartAccountEntry.mockResolvedValue({ ok: true, data: { status: 'expired', totalUsd: '0.00' } });
    api.fetchSmartAccountOfferGate.mockResolvedValue({ ok: true, data: { available: true, canSubscribe: true } });
    api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: true, data: [] });
    let state: any;
    const Probe = () => { state = useSmartAccountEntry(true); return null; };
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(state.subscriber).toBe(false);
    expect(state.totalUsd).toBeNull();
    expect(state.target).toEqual({ screen: 'SmartAccountOffer', params: { door: 'billeteras' } });

    // A scheduled cancellation is still the account.
    api.fetchSmartAccountEntry.mockResolvedValue({ ok: true, data: { status: 'cancel_pending', totalUsd: '10.00' } });
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(state.subscriber).toBe(true);
    expect(state.target).toEqual({ screen: 'SmartAccountHome' });
  });
});

describe('which designation the row speaks for', () => {
  it('prefers an accepted one with a claim running or ready over a pending invitation', () => {
    const invite = designation({ designationId: 'inv' });
    const running = designation({ designationId: 'run', state: 'active', claim: claim('pending') });
    const startable = designation({ designationId: 'start', state: 'active', canClaim: true });
    const idle = designation({ designationId: 'idle', state: 'active' });
    expect(pickDesignation([invite, running])?.designationId).toBe('run');
    expect(pickDesignation([invite, idle, startable])?.designationId).toBe('start');
    expect(pickDesignation([invite, idle])?.designationId).toBe('inv');
    expect(pickDesignation([idle])?.designationId).toBe('idle');
    expect(pickDesignation([designation({ state: 'declined' }), designation({ state: 'lapsed' })])).toBeNull();
  });

  it('the hook routes several designations to the list and one straight to its screen', async () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const React = require('react');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const renderer = require('react-test-renderer');
    const api = require('../../services/smartAccount');
    const { useSmartAccountEntry } = require('../useSmartAccountEntry');
    const flushAll = async () => { for (let i = 0; i < 5; i++) { await renderer.act(async () => { await Promise.resolve(); }); } };
    api.fetchSmartAccountEntry.mockResolvedValue({ ok: true, data: null });
    api.fetchSmartAccountOfferGate.mockResolvedValue({ ok: true, data: null });
    api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: true, data: [
      designation({ designationId: 'inv', ownerHandle: 'ana', ownerName: 'Ana P.' }),
      designation({ designationId: 'run', state: 'active', claim: claim('executable') }),
      designation({ designationId: 'gone', state: 'declined' }),
    ] });
    let state: any;
    const Probe = () => { state = useSmartAccountEntry(true); return null; };
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(state.designation.designationId).toBe('run');
    expect(state.target).toEqual({ screen: 'BeneficiaryDesignations' });

    api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: true, data: [
      designation({ designationId: 'run', state: 'active', claim: claim('executable') }),
      designation({ designationId: 'gone', state: 'lapsed' }),
    ] });
    await renderer.act(async () => { renderer.create(React.createElement(Probe)); });
    await flushAll();
    expect(state.target).toEqual({ screen: 'BeneficiaryClaimStatus', params: { designationId: 'run' } });
  });
});

describe('one row per account', () => {
  it('folds a window-change invitation into the active designation of the same owner', () => {
    const active = designation({ designationId: 'a1', state: 'active' });
    const change = designation({ designationId: 'p1', state: 'pending_acceptance' });
    expect(distinctOpenDesignations([active, change]).map((d) => d.designationId)).toEqual(['a1']);
  });

  it('keeps a pending invitation from a different owner', () => {
    const active = designation({ designationId: 'a1', state: 'active' });
    const other = designation({ designationId: 'p2', state: 'pending_acceptance', ownerHandle: 'ana', ownerName: 'Ana P.' });
    expect(distinctOpenDesignations([active, other]).map((d) => d.designationId)).toEqual(['a1', 'p2']);
  });
});
