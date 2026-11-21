import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import { logOfferStep } from '../../services/paidOffers';
import {
  account, designation, failedRead, flush, hasTappable, offer, ok, tap, tappable, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountOfferScreen, offerPitch, orderPlans } from '../SmartAccountOfferScreen';
import { DEX_TRADING_UI_ENABLED } from '../../config/features';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async () => {
  await act(async () => { tree = renderer.create(<SmartAccountOfferScreen />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  setRouteParams({ door: 'billeteras' });
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchSmartAccountEntry.mockResolvedValue(ok(null));
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([]));
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('shows the server benefits in the server order and both server prices', async () => {
  await mount();
  const out = text(tree);
  expect(out.indexOf('Pagos y transferencias automáticos')).toBeLessThan(out.indexOf('Inversión automática'));
  expect(out).toContain('US$149.99');
  expect(out).toContain('US$14.99');
  expect(out).toContain('Equivale a US$12.50 al mes');
  expect(out).not.toContain('Próximamente');
  expect(logOfferStep).toHaveBeenCalledWith('smart_account', 'detail_opened', 'billeteras', '');
});

it('puts the annual plan first and preselects the server default', async () => {
  expect(orderPlans(offer().plans).map((p) => p.key)).toEqual(['annual', 'monthly']);
  await mount();
  expect(tappable(tree, 'plan-annual').props.accessibilityState).toEqual({ selected: true });
  expect(tappable(tree, 'plan-monthly').props.accessibilityState).toEqual({ selected: false });
});

it('preselects monthly when the server says so', async () => {
  const base = offer();
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({
    plans: base.plans.map((p) => ({ ...p, isDefault: p.key === 'monthly' })),
  })));
  await mount();
  expect(tappable(tree, 'plan-monthly').props.accessibilityState).toEqual({ selected: true });
});

it('shows the six disclosures and does not continue without the acceptance', async () => {
  await mount();
  ['Uno.', 'Dos.', 'Tres.', 'Cuatro.', 'Cinco.', 'Seis.'].forEach((d) => expect(text(tree)).toContain(d));
  await tap(tree, 'offer-continue');
  expect(nav.navigate).not.toHaveBeenCalled();
  expect(text(tree)).toContain('Marca la casilla para continuar.');
  await tap(tree, 'accept-disclosures');
  await tap(tree, 'plan-monthly');
  await tap(tree, 'offer-continue');
  expect(nav.navigate).toHaveBeenCalledWith('SmartAccountFund', { plan: 'monthly' });
});

it('a viewer who cannot subscribe still sees the whole pitch, and why, next to a disabled Continuar', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedReason: 'Verifica tu identidad primero.' })));
  await mount();
  const out = text(tree);
  expect(out).toContain('Verifica tu identidad primero.');
  expect(out).toContain('US$149.99');
  expect(out).toContain('US$14.99');
  ['Uno.', 'Dos.', 'Tres.', 'Cuatro.', 'Cinco.', 'Seis.'].forEach((d) => expect(out).toContain(d));
  expect(out).not.toContain('Próximamente');
  expect(hasTappable(tree, 'accept-disclosures')).toBe(false);
  expect(tree.root.findAll((n) => n.props.testID === 'offer-continue' && n.props.accessibilityState?.disabled === true).length)
    .toBeGreaterThan(0);
  await act(async () => { tappable(tree, 'offer-continue').props.onPress(); });
  expect(nav.navigate).not.toHaveBeenCalled();
});

it('the server flag off: the real pitch with its prices, and the server reason', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({
    available: true, canSubscribe: false,
    blockedReason: 'Todavía no puedes abrir tu Cuenta inteligente.',
  })));
  await mount();
  const out = text(tree);
  expect(out).toContain('Elige tu plan');
  expect(out).toContain('Antes de firmar');
  expect(out).toContain('Todavía no puedes abrir tu Cuenta inteligente.');
  expect(out).not.toContain('Te avisaremos');
});

it('without a reason from the server it says so plainly, never a waitlist', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ available: false, canSubscribe: false, blockedReason: null })));
  await mount();
  expect(text(tree)).toContain('Todavía no puedes abrir tu Cuenta inteligente.');
  expect(text(tree)).toContain('US$149.99');
  expect(text(tree)).not.toContain('Próximamente');
});

it('offers a retry when the offer cannot be loaded', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  await tap(tree, 'Reintentar');
  await flush();
  expect(text(tree)).toContain('Elige tu plan');
});

it('sends someone who already has the account to it', async () => {
  api.fetchSmartAccountEntry.mockResolvedValue(ok({ status: account().status, contractAddress: '0xaa', totalUsd: '1' }));
  await mount();
  expect(nav.replace).toHaveBeenCalledWith('SmartAccountHome');
});

it('an account still opening is never offered a second subscribe', async () => {
  api.fetchSmartAccountEntry.mockResolvedValue(ok({ status: 'opening', contractAddress: null, totalUsd: null }));
  await mount();
  expect(nav.replace).toHaveBeenCalledWith('SmartAccountHome');
});

it('shows a pending beneficiary invitation', async () => {
  api.fetchBeneficiaryDesignations.mockResolvedValue(ok([designation()]));
  await mount();
  expect(text(tree)).toContain('Luis R. te eligió como beneficiario');
});

describe('the pitch promises only what this app can do', () => {
  const beneficiaryFirst = () => offer({
    headline: 'beneficiary_first',
    benefits: [
      { key: 'beneficiary', title: 'Beneficiario', body: 'Una persona recibe tu cuenta si dejas de usarla.' },
      { key: 'payments', title: 'Pagos y transferencias automáticos', body: 'A quien tú elijas, con tu frecuencia.' },
      { key: 'investing', title: 'Inversión automática', body: 'Compra acciones, bitcoin y oro de forma periódica.' },
      { key: 'assistant', title: 'El asistente de tu cuenta', body: 'Analiza tus movimientos.' },
    ],
  });

  it('keeps the server headline and benefits when everything is on', () => {
    const pitch = offerPitch(beneficiaryFirst(), true);
    expect(pitch.headline).toBe('Tu dinero sigue tus reglas y llega a quien tú elijas.');
    expect(pitch.benefits.map((b) => b.key)).toEqual(['beneficiary', 'payments', 'investing', 'assistant']);
    expect(pitch.benefits[2].body).toContain('bitcoin y oro');
  });

  it('without the beneficiary feature: no beneficiary benefit and the automation headline', () => {
    const pitch = offerPitch({ ...beneficiaryFirst(), beneficiaryEnabled: false }, true);
    expect(pitch.headline).toBe('Tu dinero se mueve según tus reglas.');
    expect(pitch.benefits.map((b) => b.key)).toEqual(['payments', 'investing', 'assistant']);
  });

  it('without crypto buys (server flag off, or a build without them): investing is stocks only', () => {
    const stocksOnly = 'Compra acciones automáticamente, cada día, semana, quincena o mes.';
    expect(offerPitch({ ...beneficiaryFirst(), investingCryptoEnabled: false }, true).benefits[2].body).toBe(stocksOnly);
    expect(offerPitch(beneficiaryFirst(), false).benefits[2].body).toBe(stocksOnly);
  });

  it('renders it: the beneficiary is not pitched when off, and the investing line follows the build', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok({ ...beneficiaryFirst(), beneficiaryEnabled: false }));
    await mount();
    const out = text(tree);
    expect(out).toContain('Tu dinero se mueve según tus reglas.');
    expect(out).not.toContain('Tu dinero sigue tus reglas y llega a quien tú elijas.');
    expect(out).not.toContain('Una persona recibe tu cuenta si dejas de usarla.');
    if (DEX_TRADING_UI_ENABLED) {
      expect(out).toContain('bitcoin y oro');
    } else {
      expect(out).not.toContain('bitcoin');
      expect(out).toContain('Compra acciones automáticamente');
    }
  });

  it('renders the stocks-only line when the server has crypto buys off', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok({ ...beneficiaryFirst(), investingCryptoEnabled: false }));
    await mount();
    expect(text(tree)).not.toContain('bitcoin');
    expect(text(tree)).toContain('Compra acciones automáticamente, cada día, semana, quincena o mes.');
  });
});

it('an expired account may subscribe again: plans shown, no redirect', async () => {
  api.fetchSmartAccountEntry.mockResolvedValue(ok({ status: 'expired', contractAddress: '0xaa', totalUsd: '0.00' }));
  await mount();
  expect(nav.replace).not.toHaveBeenCalled();
  expect(hasTappable(tree, 'plan-annual')).toBe(true);
  expect(hasTappable(tree, 'offer-continue')).toBe(true);
});
