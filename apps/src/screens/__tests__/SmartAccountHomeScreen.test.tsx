import { nav, profileMenu, resetMocks, returnToPersonal, setBalanceHidden, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  account, beneficiary, designation, failedRead, flush, hasTappable, offer, ok, rule, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { OPENING_TIMING, SmartAccountHomeScreen, billingBanner } from '../SmartAccountHomeScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (asTab = false) => {
  await act(async () => { tree = renderer.create(<SmartAccountHomeScreen asTab={asTab} />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccount.mockResolvedValue(ok(account()));
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('shows the total, the one dollar by its name, and holdings in dollars', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('Total en tu cuenta');
  expect(out).toContain('US$1,234.56');
  expect(out).toContain('Confío Dollar+');
  expect(out).toContain('US$1,000.00');
  expect(out).toContain('Apple');
  expect(out).toContain('US$234.56');
  expect(out).toContain('Plan anual · pagado hasta el');
  expect(out).not.toMatch(/[+-]\d+(\.\d+)?%/); // calm: no deltas
  expect(out).not.toContain('cUSD+ ·');
});

it('hides the hero total when the balance is hidden on Inicio', async () => {
  setBalanceHidden(true);
  await mount();
  const out = text(tree);
  expect(out).not.toContain('US$1,234.56');
  expect(out).toContain('••••••');
});

it('lists the accounts this phone remembers when the designations read fails', async () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const direct = require('../../services/smartAccountDirect');
  direct.loadOfflineDesignations.mockResolvedValueOnce([
    { account: '0x' + 'bb'.repeat(20), designationId: 'd5', ownerName: 'Luis R.', savedAt: 1 },
  ]);
  api.fetchBeneficiaryDesignations.mockResolvedValue({ ok: false });
  await mount();
  expect(text(tree)).toContain('Sin conexión con Confío');
  await tap(tree, 'home-offline-designation-d5');
  expect(nav.navigate).toHaveBeenCalledWith('BeneficiaryClaim', { designationId: 'd5', account: '0x' + 'bb'.repeat(20) });
});

it('summarises the rules and the next run', async () => {
  api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule(), rule({ id: 'r2', active: false, nextRunAt: null })] })));
  await mount();
  expect(text(tree)).toContain('1 regla activa');
  expect(text(tree)).toContain('Próxima: Enviar US$50.00 a Ana P.');
  await tap(tree, 'home-rules');
  expect(nav.navigate).toHaveBeenCalledWith('SmartAccountRules');
});

it('shows each beneficiary state', async () => {
  await mount();
  expect(text(tree)).toContain('Elige a tu beneficiario');
  await tap(tree, 'home-beneficiary');
  expect(nav.navigate).toHaveBeenCalledWith('BeneficiarySetup');

  api.fetchSmartAccount.mockResolvedValue(ok(account({ pendingBeneficiary: beneficiary({ state: 'pending_acceptance' }) })));
  await act(async () => tree.unmount());
  await mount();
  expect(text(tree)).toContain('Esperando que acepte');

  api.fetchSmartAccount.mockResolvedValue(ok(account({ beneficiary: beneficiary() })));
  await act(async () => tree.unmount());
  await mount();
  expect(text(tree)).toContain('Activo · plazo de 180 días');
});

it('hides the beneficiary card until the feature is on', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ beneficiaryEnabled: false })));
  await mount();
  expect(hasTappable(tree, 'home-beneficiary')).toBe(false);
});

it('shows a payment banner that opens the plan', async () => {
  const base = account();
  api.fetchSmartAccount.mockResolvedValue(ok(account({
    billing: { ...base.billing!, status: 'notice', shortfallUsd: '49.99', saleAllowedAt: '2026-12-05T00:00:00Z' },
  })));
  await mount();
  expect(text(tree)).toContain('Faltan US$49.99 para tu plan');
  await tap(tree, 'billing-banner');
  expect(nav.navigate).toHaveBeenCalledWith('SmartAccountBilling');
});

it('has no banner when the plan is current, and a neutral one when cancelling', () => {
  expect(billingBanner(account())).toBeNull();
  const base = account();
  const banner = billingBanner(account({
    status: 'cancel_pending',
    billing: { ...base.billing!, cancelRequested: true, returnsAt: '2026-12-20T12:00:00Z' },
  }));
  expect(banner).toMatchObject({ tone: 'neutral', target: 'SmartAccountCancel' });
});

describe('an expired account', () => {
  const expired = (totalUsd: string) => account({
    status: 'expired', totalUsd, dollarsUsd: totalUsd,
    billing: { ...account().billing!, status: 'payment_due', paidUntil: '2026-10-01T00:00:00Z' },
  });

  it('says assets are being returned only while something is left', () => {
    expect(billingBanner(expired('12.00'))).toMatchObject({
      title: 'Tu plan terminó', body: 'Estamos devolviendo todo a tu billetera.', target: 'SmartAccountBilling',
    });
    const done = billingBanner(expired('0.00'));
    expect(done).toMatchObject({
      title: 'Tu plan terminó', body: 'Todo ya volvió a tu billetera personal.',
      target: 'SmartAccountOffer', actionLabel: 'Volver a suscribirte',
    });
    expect(billingBanner({ ...expired('0'), totalUsd: null })?.target).toBe('SmartAccountOffer');
  });

  it('is still shown (not redirected), and offers subscribing again once everything is back', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(expired('0.00')));
    await mount();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(text(tree)).toContain('Todo ya volvió a tu billetera personal.');
    expect(text(tree)).not.toContain('Estamos devolviendo');
    expect(text(tree)).toContain('Volver a suscribirte');
    await tap(tree, 'billing-banner');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountOffer', { door: 'billeteras' });
  });
});

it('a due plan the dollars already cover: the charge is being processed, nothing to add or sell', async () => {
  const base = account();
  ['payment_due', 'notice', 'sale_allowed'].forEach((status) => {
    const banner = billingBanner(account({
      billing: { ...base.billing!, status, shortfallUsd: null, saleAllowedAt: '2026-12-05T00:00:00Z' },
    }));
    expect(banner?.title).toBe('Estamos cobrando tu plan.');
    expect(banner?.body).not.toMatch(/agrega|vende/i);
  });
  api.fetchSmartAccount.mockResolvedValue(ok(account({
    billing: { ...base.billing!, status: 'sale_allowed', shortfallUsd: null, saleAllowedAt: '2026-12-05T00:00:00Z' },
  })));
  await mount();
  expect(text(tree)).toContain('Estamos cobrando tu plan.');
  expect(text(tree)).not.toContain('Si no agregas dólares');
  expect(text(tree)).not.toContain('Tu plan está por cobrarse');
});

it('moves in and out from the hero', async () => {
  await mount();
  await tap(tree, 'Agregar dinero desde mi billetera');
  expect(nav.navigate).toHaveBeenCalledWith('SmartAccountMove', { direction: 'in' });
  await tap(tree, 'Mover a mi billetera');
  expect(nav.navigate).toHaveBeenCalledWith('SmartAccountMove', { direction: 'out' });
});

it('shows a retry, not an empty account, when the read fails', async () => {
  api.fetchSmartAccount.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
  expect(text(tree)).not.toContain('US$0.00');
  expect(nav.replace).not.toHaveBeenCalled();
});

it('opens the offer for someone without an account', async () => {
  api.fetchSmartAccount.mockResolvedValue(ok(account({ status: 'none', billing: null, assets: [] })));
  await mount();
  expect(nav.replace).toHaveBeenCalledWith('SmartAccountOffer', { door: 'billeteras' });
});

describe('a subscribe just signed (the account row comes after reconciliation)', () => {
  const none = () => ok(account({ status: 'none', billing: null, assets: [] }));
  const saved = { ...OPENING_TIMING };
  const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
  beforeEach(() => { OPENING_TIMING.pollMs = 20; OPENING_TIMING.waitMs = 120; });
  afterEach(() => { Object.assign(OPENING_TIMING, saved); });

  it('waits with "Abriendo tu cuenta…", re-reads, and never re-offers the sign-up', async () => {
    OPENING_TIMING.waitMs = 10_000;
    setRouteParams({ justSubscribed: true });
    api.fetchSmartAccount.mockResolvedValue(none());
    await mount();
    expect(text(tree)).toContain('Abriendo tu cuenta…');
    expect(nav.replace).not.toHaveBeenCalled();
    const calls = api.fetchSmartAccount.mock.calls.length;
    await wait(50);
    await flush();
    expect(api.fetchSmartAccount.mock.calls.length).toBeGreaterThan(calls);
    api.fetchSmartAccount.mockResolvedValue(ok(account()));
    await wait(50);
    await flush();
    expect(text(tree)).toContain('Total en tu cuenta');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('stops after the bounded wait with a manual retry', async () => {
    setRouteParams({ justSubscribed: true });
    api.fetchSmartAccount.mockResolvedValue(none());
    await mount();
    await wait(200);
    await flush();
    expect(text(tree)).toContain('Está tardando más de lo normal');
    const calls = api.fetchSmartAccount.mock.calls.length;
    await wait(60);
    expect(api.fetchSmartAccount.mock.calls.length).toBe(calls); // stopped polling
    await tap(tree, 'smart-opening-retry');
    await flush();
    expect(api.fetchSmartAccount.mock.calls.length).toBe(calls + 1);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("the server's 'opening' status waits the same way, even without the route flag", async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ status: 'opening', billing: null, assets: [] })));
    await mount();
    expect(text(tree)).toContain('Abriendo tu cuenta…');
    expect(nav.replace).not.toHaveBeenCalled();
  });
});

it('as the Home tab: the avatar opens the switcher and a closed account leads back to the wallet', async () => {
  await mount(true);
  await tap(tree, 'Perfil y cuentas');
  expect(profileMenu.openProfileMenu).toHaveBeenCalled();
  await tap(tree, 'Ir a mi billetera personal');
  expect(returnToPersonal).toHaveBeenCalledTimes(1);

  api.fetchSmartAccount.mockResolvedValue(ok(account({ status: 'none', billing: null, assets: [] })));
  await act(async () => tree.unmount());
  await mount(true);
  expect(text(tree)).toContain('Esta cuenta ya no está abierta');
  expect(nav.replace).not.toHaveBeenCalled();
});

it('shows an invitation to be a beneficiary', async () => {
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([designation()]));
  await mount();
  expect(text(tree)).toContain('Luis R. te eligió como beneficiario');
});

it('describes the assistant as the account service', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('El asistente de tu cuenta');
  // Confío IA+ = the assistant operates the account; the owner confirms.
  expect(out).toContain('Pídele por chat crear o cambiar tus reglas. Tú confirmas cada cambio.');
  expect(out).not.toMatch(/\bIA\b/);
  expect(out).not.toMatch(/ilimitad|más uso|modelo/i);
});

describe('the dollar row names the viewer\'s dollar', () => {
  const cusd = { key: 'cusd', kind: 'dollar', symbol: 'cUSD', name: 'cUSD', address: '0x3', units: '0', decimals: 18, valueUsd: '0.00', canPayFee: true };
  const cusdPlus = account().assets[0];
  const dollarRow = () => tree.root.findAll((n) => n.props.testID === 'home-dollar')[0];

  it('uses the server\'s dollar, not the first dollar row listed', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({
      assets: [cusd, { ...cusdPlus, units: '0', valueUsd: '0.00' }] as any,
    })));
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ dollar: 'cusd_plus' })));
    await mount();
    expect(api.fetchSmartAccountOffer).toHaveBeenCalled();
    expect(dollarRow().props.title).toBe('Confío Dollar+');
  });

  it('without the server\'s answer, names the only dollar holding a balance', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ assets: [cusd, cusdPlus] as any })));
    await mount();
    expect(dollarRow().props.title).toBe('Confío Dollar+');
  });
});
