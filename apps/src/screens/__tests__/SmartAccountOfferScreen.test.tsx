import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import { logOfferStep } from '../../services/paidOffers';
import {
  account, designation, failedRead, flush, hasTappable, offer, ok, tap, tappable, text,
} from '../../components/smartAccount/testing/fixtures';
import { HERENCIA_CARD, HERENCIA_STEPS, HERO_COPY, SmartAccountOfferScreen, offerPitch, orderPlans } from '../SmartAccountOfferScreen';
import { annualSavings, defaultPlanKey, planSummary, savingsBadge } from '../../components/smartAccount/PlanPicker';
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
  expect(out).toContain('US$12.50 al mes');
  expect(out).toContain('Ahorras US$29.89');
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

  it('automation is always the hero and Herencia always has its card, whatever the server sends', () => {
    [beneficiaryFirst(), { ...beneficiaryFirst(), headline: 'automation_first' },
      { ...beneficiaryFirst(), beneficiaryEnabled: false }].forEach((o) => {
      const pitch = offerPitch(o, true);
      expect(pitch.inheritance).toBe(true);
      expect(pitch.headline).toBe('Confío lo hace por ti, cuando toca.');
      // The beneficiary line moves into the Herencia card; the rest keeps the server order.
      expect(pitch.benefits.map((b) => b.key)).toEqual(['payments', 'investing', 'assistant']);
    });
    expect(offerPitch(beneficiaryFirst(), true).benefits[1].body).toContain('bitcoin y oro');
  });

  it('never adds a benefit the server did not send', () => {
    const pitch = offerPitch(beneficiaryFirst(), true);
    expect(pitch.benefits.map((b) => b.title)).not.toContain('Siempre a tu nombre');
  });

  it('without crypto buys (server flag off, or a build without them): investing is stocks only', () => {
    const stocksOnly = 'Compra acciones automáticamente, cada día, semana, quincena o mes.';
    expect(offerPitch({ ...beneficiaryFirst(), investingCryptoEnabled: false }, true).benefits[1].body).toBe(stocksOnly);
    expect(offerPitch(beneficiaryFirst(), false).benefits[1].body).toBe(stocksOnly);
  });

  it('renders automation first, then the benefits, then the Herencia card with its steps, then the plans', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(beneficiaryFirst()));
    await mount();
    const out = text(tree);
    expect(out).toContain(HERO_COPY.automation.headline);
    expect(out).toContain(HERO_COPY.automation.supporting);
    expect(out).toContain(HERENCIA_CARD.eyebrow);
    expect(out).toContain(HERENCIA_CARD.title);
    HERENCIA_STEPS.forEach((s) => expect(out).toContain(s.title));
    const hero = out.indexOf(HERO_COPY.automation.headline);
    const benefits = out.indexOf('Pagos y transferencias automáticos');
    const herencia = out.indexOf(HERENCIA_CARD.title);
    const plans = out.indexOf('Elige tu plan');
    expect(hero).toBeLessThan(benefits);
    expect(benefits).toBeLessThan(herencia);
    if (plans >= 0) expect(herencia).toBeLessThan(plans);
    expect(tree.root.findAll((n) => n.props.testID === 'herencia-art').length).toBeGreaterThan(0);
  });

  it('keeps the Herencia card even when the server flag is off, and the investing line follows the build', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok({ ...beneficiaryFirst(), beneficiaryEnabled: false }));
    await mount();
    const out = text(tree);
    expect(out).toContain(HERO_COPY.automation.headline);
    expect(out).toContain(HERENCIA_CARD.title);
    expect(out).not.toContain('Siempre a tu nombre');
    expect(tree.root.findAll((n) => n.props.testID === 'herencia-steps').length).toBeGreaterThan(0);
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

describe('Elige tu plan', () => {
  const plans = offer().plans;
  const priced = (annual: string, monthly: string) => plans.map((p) => ({
    ...p, priceUsd: p.key === 'annual' ? annual : monthly,
  }));

  it('preselects annual when the server names no default', async () => {
    const none = plans.map((p) => ({ ...p, isDefault: false }));
    expect(defaultPlanKey(none)).toBe('annual');
    expect(defaultPlanKey(orderPlans(none))).toBe('annual');
    expect(defaultPlanKey([])).toBeNull();
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ plans: none })));
    await mount();
    expect(tappable(tree, 'plan-annual').props.accessibilityState).toEqual({ selected: true });
  });

  it('computes the saving from the server prices against twelve months', () => {
    expect(annualSavings(plans)).toEqual({ usd: '29.89', freeMonths: 1 });
    expect(savingsBadge(plans)).toBe('Ahorras US$29.89');
  });

  it('says "meses gratis" only when the numbers give two whole months or more', () => {
    expect(savingsBadge(priced('100.00', '10.00'))).toBe('2 meses gratis');
    expect(savingsBadge(priced('100.01', '10.00'))).toBe('Ahorras US$19.99');
  });

  it('shows no saving when there is none or a price is missing', () => {
    expect(annualSavings(priced('179.88', '14.99'))).toBeNull();
    expect(annualSavings(priced('200.00', '14.99'))).toBeNull();
    expect(savingsBadge(plans.filter((p) => p.key === 'annual'))).toBeNull();
    expect(savingsBadge(priced('149.99', ''))).toBeNull();
  });

  it('summarises the selected plan in the action bar and follows the choice', async () => {
    expect(planSummary(plans.find((p) => p.key === 'annual'))).toBe('US$149.99 por año · US$12.50 al mes');
    expect(planSummary(plans.find((p) => p.key === 'monthly'))).toBe('US$14.99 por mes');
    await mount();
    expect(text(tree)).toContain('US$149.99 por año · US$12.50 al mes');
    await tap(tree, 'plan-monthly');
    expect(text(tree)).toContain('US$14.99 por mes');
    expect(text(tree)).not.toContain('US$149.99 por año · US$12.50 al mes');
  });

  it('labels the main action plainly', async () => {
    await mount();
    expect(text(tree)).toContain('Abrir mi Cuenta inteligente');
  });
});

describe('not verified yet (review 2026-11-28: 20 of 41 openers)', () => {
  it('the main button opens Verificación instead of a dead Continuar', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({
      canSubscribe: false, blockedCode: 'identity', blockedReason: 'Verifica tu identidad para abrir tu Cuenta inteligente.',
    })));
    await mount();
    expect(hasTappable(tree, 'offer-continue')).toBe(false);
    await tap(tree, 'offer-verify');
    expect(nav.navigate).toHaveBeenCalledWith('Verification');
  });

  it('any other block keeps the disabled Continuar', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedCode: 'build', blockedReason: 'Actualiza.' })));
    await mount();
    expect(hasTappable(tree, 'offer-verify')).toBe(false);
  });

  it('reads the offer again when the person comes back to the screen', async () => {
    const listeners: Array<() => void> = [];
    (nav.addListener as jest.Mock).mockImplementation((_event: string, fn: () => void) => { listeners.push(fn); return () => {}; });
    await mount();
    const calls = api.fetchSmartAccountOffer.mock.calls.length;
    await act(async () => { listeners.forEach((fn) => fn()); });  // first focus: the mount itself
    expect(api.fetchSmartAccountOffer.mock.calls.length).toBe(calls);
    await act(async () => { listeners.forEach((fn) => fn()); });
    await flush();
    expect(api.fetchSmartAccountOffer.mock.calls.length).toBe(calls + 1);
  });
});

describe('"¿Qué te hizo esperar?" after leaving', () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const exit = require('../../services/smartAccountExit');
  let asks: Array<{ reasons: Array<[string, string]>; plan: string | null }>;
  const START = 1_800_000_000_000;
  let now = START;
  const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  const leave = async () => {
    await act(async () => tree.unmount());
    tree = null as unknown as renderer.ReactTestRenderer;
    await settle();
  };
  beforeEach(() => {
    now = START;
    jest.spyOn(Date, 'now').mockImplementation(() => now);
    let stored = 0;
    exit.resetSmartAccountExitForTests({ read: async () => stored, write: async (v: number) => { stored = v; } });
    asks = [];
    exit.subscribeSmartAccountExitQuestion((ask: never) => asks.push(ask));
  });
  afterEach(() => jest.restoreAllMocks());

  it('asks after a real look, with the verify answer for someone told to verify', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedCode: 'identity', blockedReason: 'x' })));
    await mount();
    now += 5000;
    await leave();
    expect(asks).toHaveLength(1);
    expect(asks[0].reasons.map(([id]) => id)).toContain('verify');
    expect(asks[0].plan).toBeNull();
  });

  it('a quick back tap asks nothing', async () => {
    await mount();
    now += 1000;
    await leave();
    expect(asks).toHaveLength(0);
  });

  it('continuing asks nothing', async () => {
    await mount();
    now += 5000;
    await tap(tree, 'accept-disclosures');
    await tap(tree, 'offer-continue');
    await leave();
    expect(asks).toHaveLength(0);
  });

  it('going to verify asks nothing', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedCode: 'identity', blockedReason: 'x' })));
    await mount();
    now += 5000;
    await tap(tree, 'offer-verify');
    await leave();
    expect(asks).toHaveLength(0);
  });

  it('someone the screen blocked for another reason is not asked', async () => {
    for (const blockedCode of ['identity_review', 'minor', 'chain_unavailable']) {
      api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedCode, blockedReason: 'x' })));
      await mount();
      now += 5000;
      await leave();
    }
    expect(asks).toHaveLength(0);
  });

  it('documents in review get no verify button', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ canSubscribe: false, blockedCode: 'identity_review', blockedReason: 'En revisión.' })));
    await mount();
    expect(hasTappable(tree, 'offer-verify')).toBe(false);
    expect(text(tree)).toContain('En revisión.');
  });

  it('someone who could subscribe is asked with the plan they had picked', async () => {
    await mount();
    now += 5000;
    await leave();
    expect(asks[0].plan).toBe('annual');
    expect(asks[0].reasons.map(([id]) => id)).not.toContain('verify');
  });
});
