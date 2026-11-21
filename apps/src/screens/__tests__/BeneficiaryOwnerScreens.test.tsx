import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import { Pressable } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  account, beneficiary, flush, hasTappable, offer, ok, prepared, refused, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { BeneficiarySetupScreen, residualRiskLines } from '../BeneficiarySetupScreen';
import { BeneficiaryStatusScreen } from '../BeneficiaryStatusScreen';
import { HELP_BENEFICIARY, HELP_DESIGNATED } from '../../components/smartAccount/help';

it('the help never says any operation cancels a claim', () => {
  const owner = HELP_BENEFICIARY.paragraphs.join(' ');
  expect(owner).not.toMatch(/cualquier operación/i);
  expect(owner).toContain('Cualquier acción que firmes en tu Cuenta inteligente cancela el pedido');
  expect(owner).toContain('Las operaciones de una cuenta de negocio no lo cancelan');
  expect(HELP_DESIGNATED.paragraphs.join(' ')).not.toMatch(/cualquier operación/i);
});

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (el: React.ReactElement) => {
  await act(async () => { tree = renderer.create(el); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccount.mockResolvedValue(ok(account()));
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.prepareBeneficiaryDesignation.mockResolvedValue(prepared());
  api.prepareBeneficiaryDesignationWithdrawal.mockResolvedValue(prepared());
  api.prepareBeneficiaryRemoval.mockResolvedValue(prepared());
  api.prepareClaimCancel.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

describe('setup', () => {
  it('preselects the server default window and offers the server options', async () => {
    await mount(<BeneficiarySetupScreen />);
    const chips = tree.root.findAllByType(Pressable).filter((n) => n.props.accessibilityRole === 'radio');
    expect(chips.map((c) => [c.props.accessibilityLabel, c.props.accessibilityState.selected])).toEqual([
      ['90 días', false], ['180 días', true], ['365 días', false],
    ]);
  });

  it('writes the residual risk with the chosen name and days', async () => {
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-person');
    await tap(tree, 'pick-ana');
    await tap(tree, '365 días');
    expect(text(tree)).toContain(residualRiskLines('Ana P.', 365)[0]);
    const lines = residualRiskLines('Ana P.', 365);
    expect(lines[0]).toContain('tienes 365 días para cancelarlo');
    // Only a signature in the Cuenta inteligente, or from the personal
    // account, cancels a claim; a business account's operations do not.
    expect(lines[1]).toContain('Cualquier acción que firmes en tu Cuenta inteligente lo cancela');
    expect(lines[1]).toContain('cuenta personal');
    expect(lines[1]).toContain('cuenta de negocio no lo cancelan');
    expect(lines.join(' ')).not.toMatch(/cualquier operación/i);
    expect(lines[3]).toContain('pierdes la cuenta');
  });

  it('does not prepare anything without a person and the explicit acceptance', async () => {
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-review');
    expect(text(tree)).toContain('Elige a una persona.');
    await tap(tree, 'beneficiary-person');
    await tap(tree, 'pick-ana');
    await tap(tree, 'beneficiary-review');
    expect(text(tree)).toContain('Marca la casilla para continuar.');
    expect(api.prepareBeneficiaryDesignation).not.toHaveBeenCalled();
    await tap(tree, 'beneficiary-accept');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(api.prepareBeneficiaryDesignation).toHaveBeenCalledWith('ana', 180, true);
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    expect(nav.replace).toHaveBeenCalledWith('BeneficiaryStatus');
  });

  it('shows the eligibility reason plainly when the server refuses the person', async () => {
    api.prepareBeneficiaryDesignation.mockResolvedValue(refused('Esa persona todavía no verificó su identidad.', 'beneficiary_not_verified'));
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-person');
    await tap(tree, 'pick-ana');
    await tap(tree, 'beneficiary-accept');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(text(tree)).toContain('Esa persona todavía no verificó su identidad.');
    expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
  });

  it('asks for the acceptance again when the window changes', async () => {
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-person');
    await tap(tree, 'pick-ana');
    await tap(tree, 'beneficiary-accept');
    await tap(tree, '365 días');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(text(tree)).toContain('Marca la casilla para continuar.');
    expect(api.prepareBeneficiaryDesignation).not.toHaveBeenCalled();
    await tap(tree, 'beneficiary-accept');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(api.prepareBeneficiaryDesignation).toHaveBeenCalledWith('ana', 365, true);
  });

  it('asks for the acceptance again when the person changes', async () => {
    setRouteParams({ handle: 'luis', name: 'Luis R.' });
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-accept');
    await tap(tree, 'beneficiary-person');
    await tap(tree, 'pick-ana');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(text(tree)).toContain('Marca la casilla para continuar.');
    expect(api.prepareBeneficiaryDesignation).not.toHaveBeenCalled();
  });

  it('is not offered while the feature is off', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ beneficiaryEnabled: false })));
    await mount(<BeneficiarySetupScreen />);
    expect(text(tree)).toContain('Todavía no está disponible');
    expect(hasTappable(tree, 'beneficiary-review')).toBe(false);
  });

  it('opens prefilled when changing the window', async () => {
    setRouteParams({ handle: 'ana', name: 'Ana P.', windowDays: 90 });
    await mount(<BeneficiarySetupScreen />);
    await tap(tree, 'beneficiary-accept');
    await tap(tree, 'beneficiary-review');
    await flush();
    expect(api.prepareBeneficiaryDesignation).toHaveBeenCalledWith('ana', 90, true);
  });
});

describe('status', () => {
  it('invites to choose someone when nobody is named', async () => {
    await mount(<BeneficiaryStatusScreen />);
    expect(text(tree)).toContain('Aún no elegiste a nadie');
    await tap(tree, 'Elegir beneficiario');
    expect(nav.navigate).toHaveBeenCalledWith('BeneficiarySetup');
  });

  it('shows a pending invitation and withdraws it', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({
      pendingBeneficiary: beneficiary({ state: 'pending_acceptance', acceptedAt: null, expiresAt: '2026-12-10T12:00:00Z' }),
    })));
    await mount(<BeneficiaryStatusScreen />);
    const out = text(tree);
    expect(out).toContain('Todavía no acepta');
    expect(out).toContain('Vence el');
    expect(out).toContain('Hasta que acepte, tu cuenta no tiene beneficiario.');
    await tap(tree, 'status-withdraw');
    await flush();
    expect(api.prepareBeneficiaryDesignationWithdrawal).toHaveBeenCalledTimes(1);
  });

  it('shows an active beneficiary with both dates and the three actions', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary() })));
    await mount(<BeneficiaryStatusScreen />);
    const out = text(tree);
    expect(out).toContain('Lo nombraste el');
    expect(out).toContain('Aceptó el');
    expect(out).toContain('180 días');
    await tap(tree, 'status-change');
    expect(nav.navigate).toHaveBeenCalledWith('BeneficiarySetup', { handle: 'ana', name: 'Ana P.', windowDays: 180 });
    await tap(tree, 'status-remove');
    await flush();
    expect(api.prepareBeneficiaryRemoval).toHaveBeenCalledTimes(1);
    expect(text(tree)).toContain('Quitar a tu beneficiario');
  });

  it('shows a pending claim with its date and cancels it', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({
      beneficiary: beneficiary({ claim: {
        state: 'pending', initiatedAt: '2026-11-18T12:00:00Z', executableAt: '2027-05-17T12:00:00Z', cancelledAt: null, executedAt: null,
      } }),
    })));
    await mount(<BeneficiaryStatusScreen />);
    expect(text(tree)).toContain('Ana P. pidió recibir tu cuenta');
    // What cancels it, as the server words it: a signature in the Cuenta
    // inteligente or from the personal account, not a business account's.
    expect(text(tree)).toContain('cualquier acción que firmes en tu Cuenta inteligente o una operación desde tu cuenta personal');
    expect(text(tree)).toContain('las de una cuenta de negocio no');
    await tap(tree, 'status-cancel-claim');
    await flush();
    expect(api.prepareClaimCancel).toHaveBeenCalledTimes(1);
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('Pedido cancelado');
  });

  it('explains a designation that is no longer valid', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary({ state: 'stale_address' }) })));
    await mount(<BeneficiaryStatusScreen />);
    expect(text(tree)).toContain('Su billetera cambió.');
  });
});
