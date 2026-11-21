import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import { Platform } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  account, failedRead, flush, hasTappable, offer, ok, prepared, rule, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountRulesScreen, ruleNote, ruleSubtitle } from '../SmartAccountRulesScreen';
import { SmartAccountRuleEditScreen, cryptoBuyAllowed } from '../SmartAccountRuleEditScreen';
import { DEX_TRADING_UI_ENABLED } from '../../config/features';

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
      ruleId: null, payeeHandle: 'ana', amountUsd: '25.00', frequency: 'biweekly',
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
      ruleId: 'r1', payeeHandle: 'ana', amountUsd: '50.00', frequency: 'monthly',
    });
  });

  it('offers bitcoin and gold only where the build and the server both do', () => {
    expect(cryptoBuyAllowed(false)).toBe(false);
    expect(cryptoBuyAllowed(undefined)).toBe(false);
    expect(cryptoBuyAllowed(true)).toBe(DEX_TRADING_UI_ENABLED);
    expect(DEX_TRADING_UI_ENABLED).toBe(Platform.OS !== 'ios');
  });
});
