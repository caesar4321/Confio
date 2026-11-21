import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import Clipboard from '@react-native-clipboard/clipboard';
import * as service from '../../services/smartAccount';
import {
  designation, failedRead, flush, hasTappable, ok, prepared, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { BeneficiaryInviteScreen } from '../BeneficiaryInviteScreen';
import { BeneficiaryClaimScreen } from '../BeneficiaryClaimScreen';
import { BeneficiaryClaimStatusScreen, claimProgress } from '../BeneficiaryClaimStatusScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (el: React.ReactElement) => {
  await act(async () => { tree = renderer.create(el); });
  await flush();
};
const ADDRESS = '0x00000000000000000000000000000000000000aa';
const accepted = (over = {}) => designation({
  state: 'active', acceptedAt: '2026-11-12T12:00:00Z', expiresAt: null, contractAddress: ADDRESS,
  chainName: 'BNB Smart Chain', canClaim: true, ...over,
});
const claim = (over = {}) => ({
  state: 'pending', initiatedAt: '2026-01-01T00:00:00Z', executableAt: '2099-01-01T00:00:00Z',
  cancelledAt: null, executedAt: null, ...over,
});

beforeEach(() => {
  resetMocks();
  setRouteParams({ designationId: 'd1' });
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([designation()]));
  api.prepareBeneficiaryAcceptance.mockResolvedValue(prepared());
  api.prepareBeneficiaryClaim.mockResolvedValue(prepared());
  api.prepareBeneficiaryClaimExecute.mockResolvedValue(prepared());
  api.declineBeneficiaryDesignation.mockResolvedValue({ success: true, errorCode: null, errorMessage: null });
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

describe('invitation', () => {
  it('says who named them, what it means and the window', async () => {
    await mount(<BeneficiaryInviteScreen />);
    const out = text(tree);
    expect(out).toContain('Luis R. te eligió como beneficiario de su Cuenta inteligente');
    expect(out).toContain('Aceptar no mueve dinero ni te cuesta nada.');
    expect(out).toContain('180 días');
    expect(out).not.toContain(ADDRESS);
  });

  it('accepts with a signature, then shows the address and chain to keep', async () => {
    await mount(<BeneficiaryInviteScreen />);
    await tap(tree, 'invite-accept');
    await flush();
    expect(api.prepareBeneficiaryAcceptance).toHaveBeenCalledWith('d1');
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted()]));
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    await flush();
    const out = text(tree);
    expect(out).toContain('Guarda estos datos');
    expect(out).toContain(ADDRESS);
    expect(out).toContain('BNB Smart Chain');
    await tap(tree, 'invite-copy');
    expect(Clipboard.setString).toHaveBeenCalledWith(ADDRESS);
  });

  it('hides the accept footer after an executed acceptance while the server still says pending', async () => {
    await mount(<BeneficiaryInviteScreen />);
    await tap(tree, 'invite-accept');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    await flush();
    expect(hasTappable(tree, 'invite-accept')).toBe(false);
    expect(text(tree)).toContain('Estamos confirmando tu firma.');
  });

  it('declines without a signature, after one confirmation', async () => {
    await mount(<BeneficiaryInviteScreen />);
    await tap(tree, 'invite-decline');
    expect(api.declineBeneficiaryDesignation).not.toHaveBeenCalled();
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([designation({ state: 'declined' })]));
    await tap(tree, 'invite-decline-confirm');
    await flush();
    expect(api.declineBeneficiaryDesignation).toHaveBeenCalledWith('d1');
    expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
    expect(text(tree)).toContain('No aceptaste esta invitación');
  });

  it('keeps the invitation open when declining fails', async () => {
    api.declineBeneficiaryDesignation.mockResolvedValue({ success: false, errorCode: 'network', errorMessage: 'No pudimos guardar tu respuesta. Inténtalo de nuevo.' });
    await mount(<BeneficiaryInviteScreen />);
    await tap(tree, 'invite-decline');
    await tap(tree, 'invite-decline-confirm');
    await flush();
    expect(text(tree)).toContain('No pudimos guardar tu respuesta');
    expect(hasTappable(tree, 'invite-accept')).toBe(true);
  });

  it.each([
    ['designation_acceptance_in_progress', 'Ya empezaste a aceptar esta designación'],
    ['designation_already_accepted', 'Ya aceptaste esta designación'],
  ])('a decline refused with %s shows its own sentence, not "try again"', async (code, copy) => {
    api.declineBeneficiaryDesignation.mockResolvedValue({ success: false, errorCode: code, errorMessage: 'No pudimos guardar tu respuesta. Inténtalo de nuevo.' });
    await mount(<BeneficiaryInviteScreen />);
    await tap(tree, 'invite-decline');
    await tap(tree, 'invite-decline-confirm');
    await flush();
    expect(text(tree)).toContain(copy);
    expect(text(tree)).not.toContain('Inténtalo de nuevo');
  });

  it('handles a withdrawn invitation and a failed read', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
    await mount(<BeneficiaryInviteScreen />);
    expect(text(tree)).toContain('Esta invitación ya no está');
    await act(async () => tree.unmount());
    api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
    await mount(<BeneficiaryInviteScreen />);
    expect(text(tree)).toContain('No pudimos cargar esto');
  });
});

describe('claim', () => {
  it('explains the claim and starts it with a signature', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted()]));
    await mount(<BeneficiaryClaimScreen />);
    expect(text(tree)).toContain('Le avisamos a Luis R. de inmediato');
    await tap(tree, 'claim-start');
    await flush();
    expect(api.prepareBeneficiaryClaim).toHaveBeenCalledWith('d1');
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    expect(nav.replace).toHaveBeenCalledWith('BeneficiaryClaimStatus', { designationId: 'd1' });
  });

  it('shows when a new claim is possible during a cooldown', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({ canClaim: false, cooldownUntil: '2026-12-20T12:00:00Z' })]));
    await mount(<BeneficiaryClaimScreen />);
    expect(text(tree)).toContain('Podrás pedirla de nuevo desde el');
    expect(hasTappable(tree, 'claim-start')).toBe(false);
  });

  it('goes to the status when a claim is already running', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({ claim: claim() })]));
    await mount(<BeneficiaryClaimScreen />);
    expect(nav.replace).toHaveBeenCalledWith('BeneficiaryClaimStatus', { designationId: 'd1' });
  });
});

describe('claim status', () => {
  it('counts down to the fixed date and cannot execute early', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({ claim: claim() })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    const out = text(tree);
    expect(out).toMatch(/Faltan \d+ días/);
    expect(out).toContain('Podrás recibirla el');
    expect(out).toContain('La fecha es fija.');
    expect(hasTappable(tree, 'claim-execute')).toBe(false);
  });

  it('executes when the date arrived and opens the account', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({
      canExecute: true, claim: claim({ state: 'executable', executableAt: '2026-06-01T00:00:00Z' }),
    })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    expect(text(tree)).toContain('Ya puedes recibirla');
    await tap(tree, 'claim-execute');
    await flush();
    expect(api.prepareBeneficiaryClaimExecute).toHaveBeenCalledWith('d1');
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    expect(nav.replace).toHaveBeenCalledWith('InheritedAccount', { contractAddress: ADDRESS });
  });

  it('an executed claim opens the received account by its address', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({
      canClaim: false, claim: claim({ state: 'executed', executedAt: '2026-11-19T12:00:00Z' }),
    })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    await tap(tree, 'Ver la cuenta');
    expect(nav.navigate).toHaveBeenCalledWith('InheritedAccount', { contractAddress: ADDRESS });
  });

  it('says the owner cancelled and when a new claim is possible', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({
      canClaim: false, cooldownUntil: '2026-12-20T12:00:00Z',
      claim: claim({ state: 'cancelled', cancelledAt: '2026-11-19T12:00:00Z' }),
    })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    expect(text(tree)).toContain('Luis R. canceló el pedido');
    expect(text(tree)).toContain('Podrás pedirla de nuevo desde el');
  });

  it('after the owner cancels (no claim listed), says so with the date a new one is possible', async () => {
    // The server lists only pending claims: a cancelled one leaves the
    // designation with its cooldown and no claim.
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({
      canClaim: false, cooldownUntil: '2099-12-20T12:00:00Z', claim: null,
    })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    const out = text(tree);
    expect(out).toContain('Luis R. canceló el pedido.');
    expect(out).toMatch(/Puedes pedirlo de nuevo desde el .*2099/);
    expect(out).not.toContain('No hay un pedido en curso');
  });

  it('a past cooldown without a claim is just "no claim in progress"', async () => {
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([accepted({
      cooldownUntil: '2020-01-01T00:00:00Z', claim: null,
    })]));
    await mount(<BeneficiaryClaimStatusScreen />);
    expect(text(tree)).toContain('No hay un pedido en curso');
    expect(text(tree)).not.toContain('canceló el pedido');
  });

  it('executed directly: the designation is gone, the inherited list holds its address -> Ver la cuenta', async () => {
    const direct = require('../../services/smartAccountDirect');
    direct.loadDirectEntry.mockResolvedValue({ account: ADDRESS, designationId: 'd1', savedAt: 1 });
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
    api.fetchInheritedAccounts.mockResolvedValue(ok([{
      inheritedAccountId: 'i1', contractAddress: ADDRESS.toUpperCase().replace('0X', '0x'), fromName: 'Luis R.',
      inheritedAt: '2026-11-19T12:00:00Z', totalUsd: '1', assets: [], canMoveToSmartAccount: false,
    }]));
    await mount(<BeneficiaryClaimStatusScreen />);
    await flush();
    expect(direct.loadDirectEntry).toHaveBeenCalledWith({ designationId: 'd1' });
    expect(text(tree)).toContain('La cuenta ya es tuya');
    await tap(tree, 'claim-view-account');
    expect(nav.navigate).toHaveBeenCalledWith('InheritedAccount', { contractAddress: ADDRESS });
  });

  it('executed directly: the device record says inherited, even before the server lists it', async () => {
    const direct = require('../../services/smartAccountDirect');
    direct.loadDirectEntry.mockResolvedValue({ account: ADDRESS, designationId: 'd1', inheritedAccountId: 'i1', savedAt: 1 });
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
    api.fetchInheritedAccounts.mockResolvedValue(ok([]));
    await mount(<BeneficiaryClaimStatusScreen />);
    await flush();
    await tap(tree, 'claim-view-account');
    expect(nav.navigate).toHaveBeenCalledWith('InheritedAccount', { contractAddress: ADDRESS });
  });

  it('a designation gone with no record of a received account stays "no claim in progress"', async () => {
    const direct = require('../../services/smartAccountDirect');
    direct.loadDirectEntry.mockResolvedValue({ account: ADDRESS, designationId: 'd1', savedAt: 1 });
    api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
    api.fetchInheritedAccounts.mockResolvedValue(ok([]));
    await mount(<BeneficiaryClaimStatusScreen />);
    await flush();
    expect(text(tree)).toContain('No hay un pedido en curso');
    expect(hasTappable(tree, 'claim-view-account')).toBe(false);
  });

  it('measures the elapsed part of the window', () => {
    const start = '2026-01-01T00:00:00Z';
    const end = '2026-01-11T00:00:00Z';
    expect(claimProgress(start, end, Date.parse('2026-01-06T00:00:00Z'))).toBeCloseTo(0.5);
    expect(claimProgress(start, end, Date.parse('2025-12-01T00:00:00Z'))).toBe(0);
    expect(claimProgress(start, end, Date.parse('2027-01-01T00:00:00Z'))).toBe(1);
    expect(claimProgress('x', end)).toBe(0);
  });
});
