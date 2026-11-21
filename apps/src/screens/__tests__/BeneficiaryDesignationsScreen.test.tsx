import { nav, resetMocks } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import { designation, failedRead, flush, ok, tap, text } from '../../components/smartAccount/testing/fixtures';
import { BeneficiaryDesignationsScreen, designationStatus } from '../BeneficiaryDesignationsScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async () => {
  await act(async () => { tree = renderer.create(<BeneficiaryDesignationsScreen />); });
  await flush();
};
const claim = (state: string, executableAt = '2099-01-01T00:00:00Z') => ({
  state, initiatedAt: '2026-01-01T00:00:00Z', executableAt, cancelledAt: null, executedAt: null,
});

beforeEach(() => {
  resetMocks();
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([
    designation({ designationId: 'inv', ownerName: 'Ana' }),
    designation({ designationId: 'acc', ownerName: 'Luis R.', state: 'active', canClaim: true }),
    designation({ designationId: 'run', ownerName: 'Marta', state: 'active', claim: claim('executable') }),
    designation({ designationId: 'old', ownerName: 'Pedro', state: 'declined' }),
  ]));
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('lists every open designation, never a declined or lapsed one', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('Cuenta de Ana');
  expect(out).toContain('Cuenta de Luis R.');
  expect(out).toContain('Cuenta de Marta');
  expect(out).not.toContain('Cuenta de Pedro');
  expect(out).toContain('Responde la invitación.');
  expect(out).toContain('Puedes pedir la cuenta.');
  expect(out).toContain('Ya puedes recibir la cuenta.');
});

it('each row opens its own invitation, claim or claim status', async () => {
  await mount();
  await tap(tree, 'designation-inv');
  expect(nav.navigate).toHaveBeenLastCalledWith('BeneficiaryInvite', { designationId: 'inv' });
  await tap(tree, 'designation-acc');
  expect(nav.navigate).toHaveBeenLastCalledWith('BeneficiaryClaim', { designationId: 'acc' });
  await tap(tree, 'designation-run');
  expect(nav.navigate).toHaveBeenLastCalledWith('BeneficiaryClaimStatus', { designationId: 'run' });
});

it('offers a retry when the list cannot be loaded', async () => {
  api.fetchBeneficiaryDesignations.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
});

it('says how long a running claim has left', () => {
  const now = Date.parse('2026-06-01T00:00:00Z');
  expect(designationStatus(designation({ state: 'active', claim: claim('pending', '2026-06-11T00:00:00Z') }), now))
    .toBe('Pediste la cuenta. Faltan 10 días.');
});
