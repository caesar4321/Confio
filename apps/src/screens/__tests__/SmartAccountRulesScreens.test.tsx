import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import { Platform } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  account, failedRead, flush, hasTappable, offer, ok, prepared, rule, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountRulesScreen, payoutKindSubtitle, ruleNote, ruleSubtitle } from '../SmartAccountRulesScreen';
import {
  SmartAccountRuleEditScreen, cryptoBlockedMessage, cryptoBuyAllowed, payoutEmptyCopy, pendingStepBody,
} from '../SmartAccountRuleEditScreen';
import { pagoMovilFieldErrors } from '../../components/smartAccount/PagoMovilDestinationForm';
import { DEX_TRADING_UI_ENABLED } from '../../config/features';
import { HELP_WATCHES } from '../../components/smartAccount/help';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (el: React.ReactElement) => {
  await act(async () => { tree = renderer.create(el); });
  await flush();
};
const type = async (testID: string, value: string) => {
  const input = tree.root.findAll((n) => n.props.testID === testID && typeof n.props.onChangeText === 'function')[0];
  await act(async () => { input.props.onChangeText(value); });
};

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule()] })));
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchSmartAccountPayoutMethods.mockResolvedValue(ok([
    { payoutMethodId: 'pm1', rail: 'co_breb', label: 'Bre-B · Ana P.', holderName: 'Ana Pérez', available: true },
    { payoutMethodId: 'pm2', rail: 'mx_clabe', label: 'CLABE · Luis', holderName: 'Luis R.', available: true },
  ]));
  api.fetchSmartAccountBuyableAssets.mockResolvedValue(ok({ items: [], hasNextPage: false, endCursor: null }));
  api.prepareSmartAccountSendRule.mockResolvedValue(prepared());
  api.prepareSmartAccountPayoutRule.mockResolvedValue(prepared());
  api.prepareSmartAccountCancelRule.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

describe('rules list', () => {
  it('shows what each rule does, how often, when next, and opens it', async () => {
    await mount(<SmartAccountRulesScreen />);
    const out = text(tree);
    expect(out).toContain('Enviar US$50.00 a Ana P.');
    expect(out).toContain('Semanal · próxima:');
    await tap(tree, 'rule-r1');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountRuleEdit', { ruleId: 'r1' });
  });

  it('says why the last run did not happen, and marks a stopped rule', () => {
    expect(ruleNote(rule({ lastRunStatus: 'skipped', lastRunMessage: 'No había saldo.' }))).toBe('No había saldo.');
    expect(ruleNote(rule({ lastRunStatus: 'ok' }))).toBeUndefined();
    expect(ruleNote(rule({ lastRunStatus: 'skipped', lastRunMessage: 'authorization_mismatch' })))
      .toBe('Esta regla se detuvo porque cambió. Créala de nuevo para confirmar con tu rostro.');
    expect(ruleNote({ ...rule({ lastRunStatus: 'skipped', lastRunMessage: null }), lastRunReason: 'review_amount_cap' }))
      .toMatch(/supera el límite de tu cuenta/);
    expect(ruleNote(rule({ lastRunStatus: 'skipped', lastRunMessage: 'some_new_code' }))).toBe('La última vez no se ejecutó.');
    expect(ruleSubtitle(rule({ active: false }))).toBe('Semanal · detenida');
  });

  it('has an empty state and offers only the kinds the server lists', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account()));
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ payoutRails: [] })));
    await mount(<SmartAccountRulesScreen />);
    expect(text(tree)).toContain('Aún no tienes reglas');
    await tap(tree, 'rules-new');
    expect(hasTappable(tree, 'new-send')).toBe(true);
    expect(hasTappable(tree, 'new-buy')).toBe(true);
    expect(hasTappable(tree, 'new-payout')).toBe(false);
  });

  it('names the live bank rail and starts a bank rule', async () => {
    await mount(<SmartAccountRulesScreen />);
    await tap(tree, 'rules-new');
    expect(text(tree)).toContain('Bre-B');
    expect(text(tree)).not.toContain('CLABE');
    await tap(tree, 'new-payout');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountRuleEdit', { kind: 'payout' });
  });

  it('names a rail switched on by the server with the server name, never its key', async () => {
    const { clearRailLabels } = require('../../components/smartAccount/format');
    clearRailLabels();
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ payoutRails: ['ar_cvu', 'pe_cci'] })));
    api.fetchSmartAccountPayoutRailOptions.mockResolvedValue(ok([
      { key: 'ar_cvu', label: 'CVU o CBU', hint: 'Mercado Pago, Ualá, Naranja X y bancos' },
    ]));
    await mount(<SmartAccountRulesScreen />);
    await tap(tree, 'rules-new');
    const out = text(tree);
    expect(out).toContain('A una cuenta que ya guardaste: CVU o CBU, bancaria.');
    expect(out).not.toContain('ar_cvu');
    expect(out).not.toContain('pe_cci');
    clearRailLabels();
  });

  it('says the rules are paused when the plan is not current', async () => {
    const base = account();
    api.fetchSmartAccount.mockResolvedValue(ok(account({ billing: { ...base.billing!, status: 'payment_due' } })));
    await mount(<SmartAccountRulesScreen />);
    expect(text(tree)).toContain('Tus reglas están en pausa');
  });

  it('offers a retry when the rules cannot be loaded', async () => {
    api.fetchSmartAccount.mockResolvedValue(failedRead);
    await mount(<SmartAccountRulesScreen />);
    expect(text(tree)).toContain('No pudimos cargar esto');
    expect(hasTappable(tree, 'rules-new')).toBe(false);
  });
});

describe('rule edit', () => {
  it('creates a send rule from a person, an amount and a frequency', async () => {
    setRouteParams({ kind: 'send' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    expect(api.prepareSmartAccountSendRule).not.toHaveBeenCalled();
    expect(text(tree)).toContain('Elige un destino.');
    await tap(tree, 'rule-destination');
    await tap(tree, 'pick-ana');
    await type('rule-amount', '25');
    await tap(tree, 'Quincenal');
    expect(text(tree)).toContain('Tu cuenta envía US$25.00 a Ana P. cada dos semanas.');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountSendRule).toHaveBeenCalledWith({
      ruleId: null, payeeHandle: 'ana', amountUsd: '25.00', frequency: 'biweekly', firstRunAt: null,
    });
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('Regla creada');
  });

  it('a bank rule lists only saved accounts on a live rail and states the fixed dollar amount', async () => {
    setRouteParams({ kind: 'payout' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('El monto en dólares es fijo. Lo que llega en moneda local depende del tipo de cambio de ese día.');
    await tap(tree, 'rule-destination');
    expect(text(tree)).toContain('Bre-B · Ana P.');
    expect(text(tree)).not.toContain('CLABE · Luis');
  });

  it('says so when no bank account is saved for a live rail', async () => {
    setRouteParams({ kind: 'payout' });
    api.fetchSmartAccountPayoutMethods.mockResolvedValue(ok([]));
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('Aún no guardaste una cuenta bancaria');
    expect(hasTappable(tree, 'rule-review')).toBe(false);
  });

  it('keeps fetching when crypto is filtered out and a page shows nothing', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ investingCryptoEnabled: false })));
    api.fetchSmartAccountBuyableAssets
      .mockResolvedValueOnce(ok({ items: [{ assetKey: 'crypto:BTC', kind: 'crypto', symbol: 'BTC', name: 'Bitcoin' }], hasNextPage: true, endCursor: 'c1' }))
      .mockResolvedValueOnce(ok({ items: [{ assetKey: 'stock:AAPLon', kind: 'stock', symbol: 'AAPLon', name: 'Apple' }], hasNextPage: false, endCursor: null }));
    setRouteParams({ kind: 'buy' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-destination');
    // The picker's first load waits on a timer; give it real time, bounded.
    for (let i = 0; i < 50 && !text(tree).includes('Apple'); i++) {
      await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
    }
    expect(api.fetchSmartAccountBuyableAssets).toHaveBeenLastCalledWith(expect.objectContaining({ after: 'c1' }));
    expect(text(tree)).toContain('Apple');
    expect(text(tree)).not.toContain('Sin resultados');
    expect(text(tree)).not.toContain('Bitcoin');
  });

  it('an existing bank rule can still be stopped with no usable bank account', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule({
      kind: 'payout', payeeName: null, payeeHandle: null, payoutMethodId: 'pm9', payoutLabel: 'Bre-B · Ana', payoutRail: 'co_breb',
    })] })));
    api.fetchSmartAccountPayoutMethods.mockResolvedValue(ok([]));
    setRouteParams({ ruleId: 'r1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).not.toContain('Aún no guardaste una cuenta bancaria');
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
  });

  it('opens an existing rule filled in and can stop it', async () => {
    setRouteParams({ ruleId: 'r1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('Tu cuenta envía US$50.00 a Ana P. cada semana.');
    expect(text(tree)).toContain('Próxima ejecución:');
    await tap(tree, 'rule-stop');
    await flush();
    expect(api.prepareSmartAccountCancelRule).toHaveBeenCalledWith('r1');
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('Regla detenida');
  });

  it('keeps the rule id when changing an existing rule', async () => {
    setRouteParams({ ruleId: 'r1' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'Mensual');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountSendRule).toHaveBeenCalledWith({
      ruleId: 'r1', payeeHandle: 'ana', amountUsd: '50.00', frequency: 'monthly', firstRunAt: null,
    });
  });

  it('offers bitcoin and gold only where the build and the server both do', () => {
    expect(cryptoBuyAllowed(false)).toBe(false);
    expect(cryptoBuyAllowed(undefined)).toBe(false);
    expect(cryptoBuyAllowed(true)).toBe(DEX_TRADING_UI_ENABLED);
    expect(DEX_TRADING_UI_ENABLED).toBe(Platform.OS !== 'ios');
  });
});

describe('a Confío IA+ proposal (decision 34)', () => {
  it('opens prefilled, stays editable, and signs through the normal flow with the chosen first run', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    setRouteParams({
      kind: 'buy',
      prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '10.00', frequency: 'monthly',
        firstRunAt: '2026-12-01T10:00:00+00:00' },
      proposal: 'Nueva regla: invierte US$10.00 en SPY cada mes, el día 1.',
    });
    await mount(<SmartAccountRuleEditScreen />);
    const out = text(tree);
    expect(out).toContain('Propuesta de Confío IA+');
    expect(out).toContain('nada cambia hasta que firmes');
    expect(out).toContain('Tu cuenta invierte US$10.00 en SPY cada mes.');
    expect(out).toContain('Primera ejecución:');
    await type('rule-amount', '12');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountBuyRule).toHaveBeenCalledWith({
      ruleId: null, assetKey: 'stock:SPYon', amountUsd: '12.00', frequency: 'monthly',
      firstRunAt: '2026-12-01T10:00:00+00:00',
    });
    expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();  // nothing signed before the owner confirms
  });

  it('sends the proposal step (message + stepIndex) with the prepare, and hands the next step its own', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    const second = { kind: 'buy' as const, prefill: { assetKey: 'stock:QQQon', amountUsd: '30.00', frequency: 'monthly' as const },
      proposalMessageId: '42', proposalStep: 3 };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', proposalMessageId: '42', proposalStep: 1, next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountBuyRule).toHaveBeenCalledWith({
      ruleId: null, assetKey: 'stock:SPYon', amountUsd: '70.00', frequency: 'monthly', firstRunAt: null,
      proposalMessageId: '42', proposalStep: 1,
    });
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    expect(nav.replace).toHaveBeenCalledWith('SmartAccountRuleEdit', second);
  });

  it('a stop proposal step tags its cancel; a send step its send', async () => {
    setRouteParams({ ruleId: 'r1', stop: true, proposal: 'Detener la regla.', proposalMessageId: '42', proposalStep: 0 });
    await mount(<SmartAccountRuleEditScreen />);
    await flush();
    expect(api.prepareSmartAccountCancelRule).toHaveBeenCalledWith('r1', { proposalMessageId: '42', proposalStep: 0 });
    await act(async () => tree.unmount());
    setRouteParams({ ruleId: 'r1', prefill: { amountUsd: '60.00' }, proposal: 'Subir.', proposalMessageId: '42', proposalStep: 2 });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountSendRule).toHaveBeenCalledWith(expect.objectContaining({
      ruleId: 'r1', amountUsd: '60.00', proposalMessageId: '42', proposalStep: 2 }));
  });

  it('drops the start day when the owner switches to daily', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '10.00',
      frequency: 'weekly', firstRunAt: '2026-12-01T10:00:00+00:00' } });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'Diario');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountBuyRule).toHaveBeenCalledWith(expect.objectContaining({ firstRunAt: null }));
  });

  it('a stop proposal opens the stop confirmation of that rule', async () => {
    setRouteParams({ ruleId: 'r1', stop: true, proposal: 'Detener la regla.' });
    await mount(<SmartAccountRuleEditScreen />);
    await flush();
    expect(api.prepareSmartAccountCancelRule).toHaveBeenCalledWith('r1');
    expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
  });

  it('a dismissed stop proposal offers only "Detener esta regla", never an update', async () => {
    setRouteParams({ ruleId: 'r1', stop: true, proposal: 'Detener la regla.' });
    await mount(<SmartAccountRuleEditScreen />);
    await flush();
    const sheet = tree.root.findAll((n) => typeof n.props.onDone === 'function' && n.props.flow)[0];
    await act(async () => { sheet.props.flow.reset(); });
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
    expect(api.prepareSmartAccountSendRule).not.toHaveBeenCalled();
  });

  it('a new proposal on the open screen gets a fresh form (values and stop confirmation)', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule(), rule({ id: 'r2' })] })));
    setRouteParams({ ruleId: 'r1', stop: true, proposal: 'Detener la regla.' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(api.prepareSmartAccountCancelRule).toHaveBeenLastCalledWith('r1');
    // B: a buy proposal replaces A's params on the same screen.
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Comprar SPY.' });
    await act(async () => { tree.update(<SmartAccountRuleEditScreen />); });
    await flush();
    expect(text(tree)).toContain('Tu cuenta invierte US$70.00 en SPY cada mes.');
    // C: a stop proposal for another rule opens its own stop confirmation.
    setRouteParams({ ruleId: 'r2', stop: true, proposal: 'Detener la otra regla.' });
    await act(async () => { tree.update(<SmartAccountRuleEditScreen />); });
    await flush();
    expect(api.prepareSmartAccountCancelRule).toHaveBeenLastCalledWith('r2');
    // D: a send proposal never keeps the amount typed for an earlier one.
    setRouteParams({ kind: 'send', prefill: { payeeHandle: 'luis', payeeName: 'Luis R.', amountUsd: '15.00',
      frequency: 'weekly' }, proposal: 'Enviar a Luis.' });
    await act(async () => { tree.update(<SmartAccountRuleEditScreen />); });
    await flush();
    await type('rule-amount', '99');
    setRouteParams({ kind: 'send', prefill: { payeeHandle: 'eva', payeeName: 'Eva M.', amountUsd: '20.00',
      frequency: 'monthly' }, proposal: 'Enviar a Eva.' });
    await act(async () => { tree.update(<SmartAccountRuleEditScreen />); });
    await flush();
    const out = text(tree);
    expect(out).toContain('Tu cuenta envía US$20.00 a Eva M. cada mes.');
    expect(out).not.toContain('Luis');
  });

  it('a proposed bitcoin / gold buy is never signed where they are not offered', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ investingCryptoEnabled: false })));
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'crypto:BTCB', assetName: 'Bitcoin', amountUsd: '10.00',
      frequency: 'monthly' }, proposal: 'Nueva regla: invierte US$10.00 en Bitcoin cada mes.' });
    await mount(<SmartAccountRuleEditScreen />);
    const out = text(tree);
    expect(out).toContain(cryptoBlockedMessage());
    expect(out).not.toContain('Bitcoin cada mes');  // neither the form nor the banner names it
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(api.prepareSmartAccountBuyRule).not.toHaveBeenCalled();
  });

  it('an existing bitcoin / gold rule where they are not offered: gate message, no Revisar, can still stop', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ investingCryptoEnabled: false })));
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule({
      kind: 'buy', payeeName: null, payeeHandle: null, assetKey: 'crypto:BTCB', assetSymbol: 'BTC', assetName: 'Bitcoin',
    })] })));
    // From the Rules list.
    setRouteParams({ ruleId: 'r1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain(cryptoBlockedMessage());
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
    await act(async () => tree.unmount());
    // An update proposal that changes only the amount.
    setRouteParams({ ruleId: 'r1', prefill: { amountUsd: '20.00' }, proposal: 'Subir la regla a US$20.00.' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain(cryptoBlockedMessage());
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
    await tap(tree, 'rule-stop');
    await flush();
    expect(api.prepareSmartAccountCancelRule).toHaveBeenCalledWith('r1');
    expect(api.prepareSmartAccountBuyRule).not.toHaveBeenCalled();
  });

  it('an existing stock rule keeps Revisar even where bitcoin / gold are off', async () => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ investingCryptoEnabled: false })));
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule({
      kind: 'buy', payeeName: null, payeeHandle: null, assetKey: 'stock:SPYon', assetSymbol: 'SPY', assetName: 'SPY',
    })] })));
    setRouteParams({ ruleId: 'r1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).not.toContain(cryptoBlockedMessage());
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountBuyRule).toHaveBeenCalledWith(expect.objectContaining({ ruleId: 'r1', assetKey: 'stock:SPYon' }));
  });

  it('the gate message names bitcoin / gold only in builds that offer them', () => {
    expect(cryptoBlockedMessage(false)).toBe('Esa inversión no está disponible en esta versión de la app. Elige otra.');
    expect(cryptoBlockedMessage(true)).toBe('Oro y Bitcoin no están disponibles para tu cuenta. Elige otra inversión.');
    expect(cryptoBlockedMessage(false)).not.toMatch(/Bitcoin|Oro/);
  });

  it('after signing one step, opens the next step of the same proposal', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' } };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo: nueva regla de SPY.', next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('quedan 1 más');
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-done');
    expect(nav.replace).toHaveBeenCalledWith('SmartAccountRuleEdit', second);
    expect(nav.goBack).not.toHaveBeenCalled();
  });

  it('an unknown outcome on one step never opens the next: it stays and says how to finish the plan', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    api.signAndSubmitPrepared.mockResolvedValue({ status: 'unknown' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' } };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo: nueva regla de SPY.', next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-unknown-done');
    expect(nav.replace).not.toHaveBeenCalled();
    expect(nav.goBack).not.toHaveBeenCalled();
    const out = text(tree);
    expect(out).toContain('Este paso todavía se está confirmando');
    expect(out).toContain('No lo repitas. Cuando aparezca en tus reglas, vuelve a abrir la propuesta de Confío IA+ para seguir con el resto del plan.');
    expect(out).not.toContain('continuarlo');  // re-opening the chip restarts at step 1: never promise a resume
    expect(hasTappable(tree, 'rule-review')).toBe(false);  // no second signature of a step that may have gone through
    await tap(tree, 'rule-step-pending');
    // Back to the rules already under this screen, never a second Rules screen on top.
    expect(nav.popTo).toHaveBeenCalledWith('SmartAccountRules');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('while a step is unconfirmed, nothing else is signed and the plan never moves on', async () => {
    api.prepareSmartAccountSendRule.mockResolvedValue(prepared());
    api.signAndSubmitPrepared.mockResolvedValue({ status: 'unknown' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'stock:SPYon', amountUsd: '30.00', frequency: 'monthly' } };
    setRouteParams({ ruleId: 'r1', prefill: { amountUsd: '60.00', frequency: 'weekly' },
      proposal: 'Subir la regla a US$60.00.', next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-unknown-done');
    expect(text(tree)).toContain('Este paso todavía se está confirmando');
    expect(hasTappable(tree, 'rule-stop')).toBe(false);
    // Even if the sheet reports a signed step now, the next one never opens.
    const sheet = tree.root.findAll((n) => typeof n.props.onDone === 'function' && n.props.flow)[0];
    await act(async () => { sheet.props.onDone(); });
    expect(nav.replace).not.toHaveBeenCalled();
    expect(nav.goBack).not.toHaveBeenCalled();
    expect(api.prepareSmartAccountCancelRule).not.toHaveBeenCalled();
  });

  it('a step refused as a duplicate at prepare offers "Seguir con el plan" to the next step, with its own tags', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue({ success: false, errorCode: 'rule_duplicate', errorMessage: '' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' },
      proposalMessageId: '42', proposalStep: 2 };
    const third = { kind: 'buy', prefill: { assetKey: 'stock:QQQon', amountUsd: '10.00', frequency: 'monthly' },
      proposalMessageId: '42', proposalStep: 3 };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', proposalMessageId: '42', proposalStep: 1, next: [second, third] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    expect(text(tree)).toContain('Ya tienes esta regla. No la repitas. No se movió nada.');
    expect(hasTappable(tree, 'rule-duplicate-rules')).toBe(false);
    expect(text(tree)).toContain('Seguir con el plan');
    await tap(tree, 'rule-duplicate-continue');
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith('SmartAccountRuleEdit', { ...second, next: [third] });
    expect(nav.goBack).not.toHaveBeenCalled();
  });

  it('a duplicate refused at submit also moves the plan on', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    api.signAndSubmitPrepared.mockResolvedValue({ status: 'not_sent', code: 'rule_duplicate' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' },
      proposalMessageId: '42', proposalStep: 2 };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', proposalMessageId: '42', proposalStep: 1, next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'rule-duplicate-continue');
    expect(nav.replace).toHaveBeenCalledWith('SmartAccountRuleEdit', second);
  });

  it.each([
    ['at prepare', () => {
      api.prepareSmartAccountBuyRule.mockResolvedValue({ success: false, errorCode: 'rule_duplicate_pending', errorMessage: '' } as any);
    }, false],
    ['at submit', () => {
      api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
      api.signAndSubmitPrepared.mockResolvedValue({ status: 'not_sent', code: 'rule_duplicate_pending' } as any);
    }, true],
  ])('a step whose rule is still confirming (%s) never moves the plan on and turns into the pending notice', async (_label, arrange, signs) => {
    (arrange as () => void)();
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' },
      proposalMessageId: '42', proposalStep: 2 };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', proposalMessageId: '42', proposalStep: 1, next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    if (signs) {
      await tap(tree, 'sign-confirm');
      await flush();
    }
    expect(text(tree)).toContain('Esta regla se está confirmando. No la repitas. No se movió nada.');
    expect(text(tree)).not.toContain('Seguir con el plan');
    expect(hasTappable(tree, 'rule-duplicate-continue')).toBe(false);
    // The screen is the pending-step notice: no "Revisar", nothing else signed.
    expect(text(tree)).toContain('Este paso todavía se está confirmando');
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    const sheet = tree.root.findAll((n) => typeof n.props.onDone === 'function' && n.props.flow)[0];
    await act(async () => { sheet.props.onDone(); });
    expect(nav.replace).not.toHaveBeenCalled();
    await tap(tree, 'rule-duplicate-pending-rules');
    expect(nav.popTo).toHaveBeenCalledWith('SmartAccountRules');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('a duplicate on the last step shows the message and "Ir a tus reglas" only', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue({ success: false, errorCode: 'rule_duplicate', errorMessage: '' } as any);
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', proposalMessageId: '42', proposalStep: 1 });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    expect(text(tree)).toContain('Ya tienes esta regla');
    expect(text(tree)).not.toContain('Seguir con el plan');
    expect(hasTappable(tree, 'rule-duplicate-continue')).toBe(false);
    await tap(tree, 'rule-duplicate-rules');
    expect(nav.popTo).toHaveBeenCalledWith('SmartAccountRules');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('any other refusal never offers to move the plan on', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue({ success: false, errorCode: 'insufficient_balance', errorMessage: '' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' } };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    expect(text(tree)).toContain('No tienes saldo suficiente');
    expect(text(tree)).not.toContain('Seguir con el plan');
    expect(hasTappable(tree, 'rule-duplicate-continue')).toBe(false);
    expect(hasTappable(tree, 'rule-duplicate-rules')).toBe(false);
  });

  it('a duplicate is never offered as a way on while the step is unconfirmed', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    api.signAndSubmitPrepared.mockResolvedValue({ status: 'unknown' } as any);
    const second = { kind: 'buy', prefill: { assetKey: 'crypto:BTCB', amountUsd: '30.00', frequency: 'monthly' } };
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:SPYon', assetName: 'SPY', amountUsd: '70.00',
      frequency: 'monthly' }, proposal: 'Tu objetivo.', next: [second] });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    await tap(tree, 'sign-unknown-done');
    expect(text(tree)).toContain('Este paso todavía se está confirmando');
    // Even a duplicate refusal arriving now offers no way on.
    const sheet = tree.root.findAll((n) => typeof n.props.onDone === 'function' && n.props.flow)[0];
    await act(async () => {
      await sheet.props.flow.start({ prepare: async () => ({ success: false, errorCode: 'rule_duplicate', errorMessage: '' }) });
    });
    await flush();
    expect(text(tree)).toContain('Ya tienes esta regla');
    expect(hasTappable(tree, 'rule-duplicate-continue')).toBe(false);
    expect(hasTappable(tree, 'rule-duplicate-rules')).toBe(false);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('a proposed bank account that is no longer usable is never swapped for the current one', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule({
      kind: 'payout', payeeName: null, payeeHandle: null, payoutMethodId: 'pm9', payoutLabel: 'Bre-B · Vieja', payoutRail: 'co_breb',
    })] })));
    setRouteParams({ ruleId: 'r1', prefill: { payoutMethodId: 'pmGone', amountUsd: '40.00', frequency: 'monthly' },
      proposal: 'Cambiar el destino a Bre-B · Nueva.' });
    await mount(<SmartAccountRuleEditScreen />);
    let out = text(tree);
    expect(out).toContain('Esa cuenta ya no está disponible. Elige un destino.');
    expect(out).not.toContain('Bre-B · Nueva');  // the banner names no account that is not selected
    expect(out).not.toContain('Bre-B · Vieja');  // nor does the form fall back to the current one
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountPayoutRule).not.toHaveBeenCalled();
    await tap(tree, 'rule-destination');
    await act(async () => {
      tree.root.findAll((n) => n.props.title === 'Bre-B · Ana P.' && typeof n.props.onPress === 'function')[0].props.onPress();
    });
    out = text(tree);
    expect(out).not.toContain('Esa cuenta ya no está disponible.');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountPayoutRule).toHaveBeenCalledWith(expect.objectContaining({ ruleId: 'r1', payoutMethodId: 'pm1' }));
  });

  it('a proposed bank account still usable is selected and named', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule({
      kind: 'payout', payeeName: null, payeeHandle: null, payoutMethodId: 'pm9', payoutLabel: 'Bre-B · Vieja', payoutRail: 'co_breb',
    })] })));
    setRouteParams({ ruleId: 'r1', prefill: { payoutMethodId: 'pm1', amountUsd: '40.00', frequency: 'monthly' },
      proposal: 'Cambiar el destino a Bre-B · Ana P.' });
    await mount(<SmartAccountRuleEditScreen />);
    const out = text(tree);
    expect(out).toContain('Cambiar el destino a Bre-B · Ana P.');
    expect(out).not.toContain('Esa cuenta ya no está disponible.');
    await tap(tree, 'rule-review');
    await flush();
    expect(api.prepareSmartAccountPayoutRule).toHaveBeenCalledWith(expect.objectContaining({ payoutMethodId: 'pm1' }));
  });

  it('a proposed buy (an alert\'s prepared purchase) says it repeats until stopped', async () => {
    api.prepareSmartAccountBuyRule.mockResolvedValue(prepared());
    setRouteParams({ kind: 'buy', prefill: { assetKey: 'stock:TSLAon', assetName: 'Tesla', amountUsd: '100.00',
      frequency: 'monthly' }, proposal: 'Comprar US$100.00 de Tesla desde tu Cuenta inteligente.' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-review');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('se repite cada mes hasta que la detengas. Si solo querías una compra, detenla después de la primera.');
    expect(HELP_WATCHES.paragraphs[1]).toContain('una regla que se repite hasta que la detengas');
    expect(HELP_WATCHES.paragraphs[1]).toContain('Si solo querías una compra, detenla después de la primera.');
    expect(HELP_WATCHES.paragraphs[1]).not.toContain('mensual');
  });
});

describe('card and unknown rules (decision 35)', () => {
  const card = rule({ id: 'c1', kind: 'card', amountUsd: '100.00', frequency: 'monthly', nextRunAt: null,
    payeeName: 'Tarjeta Confío', payeeHandle: null });
  const unknown = rule({ id: 'u1', kind: 'something_new', amountUsd: '20.00', payeeName: null, payeeHandle: null });

  beforeEach(() => {
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule(), card, unknown] })));
    api.fetchSmartAccountCardRules.mockResolvedValue(ok([{
      ruleId: 'c1', spenderLabel: 'Tarjeta Confío', active: true, capUsd: '100.00', spentUsd: '30.00',
      remainingUsd: '70.00', periodDays: 28, periodStart: '2026-11-10T00:00:00Z', periodEnd: '2026-12-08T00:00:00Z',
      recentPulls: [{ pulledAt: '2026-11-20T12:00:00Z', usdSpent: '30.00', usdtOut: '29.73', txHash: '0x1' }],
    }]));
  });

  it('formats a card rule and any unknown kind without crashing', () => {
    const { ruleTitle } = require('../../components/smartAccount/format');
    expect(ruleTitle(card)).toBe('Tarjeta Confío: hasta US$100.00');
    expect(ruleTitle(unknown)).toBe('Regla automática de US$20.00');
    expect(ruleSubtitle(card)).toBe('Límite cada 28 días');
    expect(ruleSubtitle({ ...card, active: false })).toBe('detenida');
    expect(ruleSubtitle(unknown)).toBe('activa');
  });

  it('lists them in the rules list', async () => {
    await mount(<SmartAccountRulesScreen />);
    const out = text(tree);
    expect(out).toContain('Tarjeta Confío: hasta US$100.00');
    expect(out).toContain('Regla automática de US$20.00');
  });

  it('opens a card rule read-only, with its room this period and only the stop', async () => {
    setRouteParams({ ruleId: 'c1' });
    await mount(<SmartAccountRuleEditScreen />);
    const out = text(tree);
    expect(out).toContain('Tarjeta Confío: hasta US$100.00');
    expect(out).toContain('US$70.00');
    expect(out).toContain('comisión de salida de 0,9%');
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(hasTappable(tree, 'rule-destination')).toBe(false);
    await tap(tree, 'rule-stop');
    expect(api.prepareSmartAccountCancelRule).toHaveBeenCalledWith('c1');
  });

  it('still shows a card rule when its period read fails', async () => {
    api.fetchSmartAccountCardRules.mockResolvedValue(failedRead);
    setRouteParams({ ruleId: 'c1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('Tarjeta Confío: hasta US$100.00');
    expect(hasTappable(tree, 'rule-stop')).toBe(true);
  });

  it('opens an unknown kind read-only too', async () => {
    setRouteParams({ ruleId: 'u1' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('no se puede cambiar desde esta versión');
    expect(hasTappable(tree, 'rule-review')).toBe(false);
    expect(api.fetchSmartAccountCardRules).not.toHaveBeenCalled();
  });
});

describe('Pago Móvil destinations from the payout picker', () => {
  const saved = { payoutMethodId: 'pmv', rail: 've_pagomovil', label: 'Pago Móvil · Banesco · 4567', holderName: 'Ana Pérez', available: true };

  beforeEach(() => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ payoutRails: ['ve_pagomovil'] })));
    api.fetchSmartAccountPayoutMethods.mockResolvedValue(ok([]));
    api.fetchSmartAccountPagoMovilBanks.mockResolvedValue(ok([{ code: '0134', name: 'Banesco' }, { code: '0102', name: 'Banco de Venezuela' }]));
    (api.saveSmartAccountPagoMovilDestination as jest.Mock).mockResolvedValue(
      { success: true, errorCode: null, errorMessage: null, payoutMethod: saved });
  });

  it('the empty state never sends the user to Enviar for Pago Móvil, and offers the form', async () => {
    setRouteParams({ kind: 'payout' });
    await mount(<SmartAccountRuleEditScreen />);
    const out = text(tree);
    expect(out).toContain('Agrega una cuenta Pago Móvil');
    expect(out).not.toContain('desde Enviar');
    expect(hasTappable(tree, 'Agregar cuenta Pago Móvil')).toBe(true);
  });

  it('adds an account, selects it, and signs the rule naming it', async () => {
    setRouteParams({ kind: 'payout' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'Agregar cuenta Pago Móvil');
    await flush();
    expect(hasTappable(tree, 'pagomovil-save')).toBe(true);
    await tap(tree, 'pagomovil-save');  // nothing filled: local checks, nothing sent
    expect(api.saveSmartAccountPagoMovilDestination).not.toHaveBeenCalled();
    expect(text(tree)).toContain('Elige el banco.');
    await tap(tree, 'pagomovil-bank');
    await tap(tree, 'pagomovil-bank-0134');
    await type('pagomovil-phone', '0414 1234567');
    await type('pagomovil-id', 'v12345678');
    await type('pagomovil-name', 'Ana Pérez');
    await tap(tree, 'pagomovil-save');
    await flush();
    expect(api.saveSmartAccountPagoMovilDestination).toHaveBeenCalledWith(
      { phone: '0414 1234567', bankCode: '0134', idNumber: 'v12345678', holderName: 'Ana Pérez' });
    expect(text(tree)).toContain('Pago Móvil · Banesco · 4567');
    await type('rule-amount', '25');
    await tap(tree, 'rule-review');
    expect(api.prepareSmartAccountPayoutRule).toHaveBeenCalledWith(expect.objectContaining({ payoutMethodId: 'pmv', amountUsd: '25.00' }));
  });

  it('shows the server message when the account is refused, and keeps the form', async () => {
    (api.saveSmartAccountPagoMovilDestination as jest.Mock).mockResolvedValue(
      { success: false, errorCode: 'bad_pagomovil_destination', errorMessage: 'La cédula debe tener el formato V12345678.', payoutMethod: null });
    setRouteParams({ kind: 'payout' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'Agregar cuenta Pago Móvil');
    await flush();
    await tap(tree, 'pagomovil-bank');
    await tap(tree, 'pagomovil-bank-0102');
    await type('pagomovil-phone', '04141234567');
    await type('pagomovil-id', 'V12345678');
    await type('pagomovil-name', 'Ana');
    await tap(tree, 'pagomovil-save');
    await flush();
    expect(text(tree)).toContain('La cédula debe tener el formato V12345678.');
    expect(hasTappable(tree, 'pagomovil-save')).toBe(true);
  });

  it('the saved-accounts sheet offers to add one next to the saved list', async () => {
    api.fetchSmartAccountPayoutMethods.mockResolvedValue(ok([saved]));
    setRouteParams({ kind: 'payout' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-destination');
    expect(text(tree)).toContain('Pago Móvil · Banesco · 4567');
    expect(hasTappable(tree, 'payout-add-pagomovil')).toBe(true);
  });

  it('copy: Pago Móvil is added here, other rails from Enviar', () => {
    expect(payoutEmptyCopy([])).toBe('Los pagos automáticos a cuenta bancaria todavía no están disponibles para ti.');
    expect(payoutEmptyCopy(['co_breb'])).toContain('desde Enviar');
    expect(payoutEmptyCopy(['ve_pagomovil'])).toBe('Agrega una cuenta Pago Móvil y podrás pagarle de forma automática.');
    expect(payoutEmptyCopy(['ve_pagomovil', 'co_breb'])).toBe('Agrega aquí una cuenta Pago Móvil. Las cuentas Bre-B se guardan desde Enviar.');
    expect(payoutKindSubtitle(['ve_pagomovil'])).toContain('o a una Pago Móvil que agregues');
    expect(payoutKindSubtitle(['co_breb'])).toBe('A una cuenta que ya guardaste: Bre-B.');
  });

  it('local checks mirror the server format', () => {
    const ok_ = pagoMovilFieldErrors({ bank: { code: '0134', name: 'Banesco' }, phone: '+58 414-123-4567', idNumber: '12345678', holderName: 'Ana P' });
    expect(ok_).toEqual({ bank: '', phone: '', idNumber: '', holderName: '' });
    const bad = pagoMovilFieldErrors({ bank: null, phone: '0212 1234567', idNumber: 'X1', holderName: ' ' });
    expect(Object.values(bad).every(Boolean)).toBe(true);
  });
});

describe('audit copy fixes', () => {
  it('the pending-step notice names Confío IA+ only for a proposal', () => {
    expect(pendingStepBody(true)).toContain('Confío IA+');
    expect(pendingStepBody(false)).toBe('No lo repitas. Cuando aparezca en tus reglas, ya está lista.');
  });

  it('a manual rule whose signature is still confirming never mentions an IA+ proposal', async () => {
    api.prepareSmartAccountSendRule.mockResolvedValue({ ...prepared(), success: false, errorCode: 'rule_duplicate_pending',
      errorMessage: 'Esa regla se está confirmando.' } as any);
    setRouteParams({ kind: 'send' });
    await mount(<SmartAccountRuleEditScreen />);
    await tap(tree, 'rule-destination');
    await tap(tree, 'pick-ana');
    await type('rule-amount', '10');
    await tap(tree, 'rule-review');
    await flush();
    const out = text(tree);
    expect(out).toContain('Cuando aparezca en tus reglas, ya está lista.');
    expect(out).not.toContain('Confío IA+');
  });

  it('a card limit with no known frequency reads "por período", never "cada día"', async () => {
    const { cardPeriodLabel, cardPeriodDays } = require('../../components/smartAccount/format');
    expect(cardPeriodLabel(cardPeriodDays(null))).toBe('por período');
    expect(cardPeriodLabel(cardPeriodDays('fortnightly_v2'))).toBe('por período');
    expect(cardPeriodLabel(0)).toBe('por período');
    expect(cardPeriodLabel(1)).toBe('cada día');
    expect(cardPeriodLabel(28)).toBe('cada 28 días');
    const card = rule({ id: 'c2', kind: 'card', amountUsd: '40.00', frequency: null as any, nextRunAt: null,
      payeeName: 'Tarjeta Confío', payeeHandle: null });
    expect(ruleSubtitle(card)).toBe('Límite por período');
    api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [card] })));
    api.fetchSmartAccountCardRules.mockResolvedValue(failedRead);
    setRouteParams({ ruleId: 'c2' });
    await mount(<SmartAccountRuleEditScreen />);
    expect(text(tree)).toContain('hasta US$40.00 por período');
    expect(text(tree)).not.toContain('cada día');
  });
});
