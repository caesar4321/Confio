import { nav, resetMocks } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  account, beneficiary, failedRead, flush, hasTappable, offer, ok, prepared, rule, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountCancelScreen, cancelClosesNow } from '../SmartAccountCancelScreen';
import { SmartAccountBillingScreen, billingProblem, saleCandidateLabels } from '../SmartAccountBillingScreen';
import { DEX_TRADING_UI_ENABLED } from '../../config/features';
import { SmartAccountChargesScreen } from '../SmartAccountChargesScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (el: React.ReactElement) => {
  await act(async () => { tree = renderer.create(el); });
  await flush();
};
const charge = (id: string) => ({
  id, chargedAt: '2026-11-20T12:00:00Z', periodStart: '2026-11-20T12:00:00Z', periodEnd: '2026-12-20T12:00:00Z',
  plan: 'monthly', feeUsd: '14.99', paidWith: 'cusd_plus', txHash: '0x1',
});
const pageOf = (ids: string[], hasNextPage = false, endCursor: string | null = null) =>
  ok({ items: ids.map(charge), hasNextPage, endCursor });
const cancelling = () => {
  const base = account();
  return account({
    status: 'cancel_pending',
    billing: { ...base.billing!, cancelRequested: true, returnsAt: '2027-11-20T12:00:00Z' },
  });
};

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccount.mockResolvedValue(ok(account({ rules: [rule()], beneficiary: beneficiary() })));
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchSmartAccountCharges.mockResolvedValue(pageOf(['1', '2']));
  api.prepareSmartAccountCancel.mockResolvedValue(prepared());
  api.prepareSmartAccountUndoCancel.mockResolvedValue(prepared());
  api.prepareSmartAccountPlanChange.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

describe('cancel', () => {
  it('states the date and the three consequences before signing', async () => {
    await mount(<SmartAccountCancelScreen />);
    const out = text(tree);
    expect(out).toContain('tu cuenta sigue activa hasta el');
    expect(out).toContain('Todo vuelve a tu billetera');
    expect(out).toContain('La automatización se detiene');
    expect(out).toContain('Tu beneficiario deja de aplicar');
    expect(out).toContain('no se reembolsa');
  });

  it('cancels with a signature and keeps the right wording after the account reloads', async () => {
    await mount(<SmartAccountCancelScreen />);
    await tap(tree, 'cancel-confirm');
    await flush();
    expect(api.prepareSmartAccountCancel).toHaveBeenCalledTimes(1);
    api.fetchSmartAccount.mockResolvedValue(ok(cancelling()));
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('Cancelación programada');
    expect(text(tree)).not.toContain('Tu cuenta sigue activa\n');
  });

  it('offers only the undo while a cancellation is pending', async () => {
    api.fetchSmartAccount.mockResolvedValue(ok(cancelling()));
    await mount(<SmartAccountCancelScreen />);
    expect(text(tree)).toContain('Tu cuenta se cierra el');
    expect(hasTappable(tree, 'cancel-confirm')).toBe(false);
    await tap(tree, 'cancel-undo');
    await flush();
    expect(api.prepareSmartAccountUndoCancel).toHaveBeenCalledTimes(1);
  });

  it('with no paid period ahead, the account closes now and has no date', async () => {
    const base = account();
    const cases = [
      account({ billing: { ...base.billing!, status: 'payment_due', shortfallUsd: '14.99' } }),
      account({ billing: { ...base.billing!, paidUntil: '2026-01-01T00:00:00Z' } }),
    ];
    expect(cancelClosesNow(account())).toBe(false);
    for (const acct of cases) {
      expect(cancelClosesNow(acct)).toBe(true);
      api.fetchSmartAccount.mockResolvedValue(ok(acct));
      await mount(<SmartAccountCancelScreen />);
      const out = text(tree);
      expect(out).toContain('Si cancelas, tu cuenta se cierra ahora');
      expect(out).toContain('regresa ahora a tu billetera personal');
      expect(out).not.toContain('sigue activa hasta');
      expect(out).not.toContain('Pagado hasta el');
      expect(out).not.toMatch(/El \d/);
      await act(async () => tree.unmount());
    }
  });

  it('a scheduled cancellation with a future return date keeps its date', () => {
    const c = cancelling();
    expect(cancelClosesNow({ ...c, billing: { ...c.billing!, status: 'payment_due' } })).toBe(false);
  });

  it('offers a retry when the account cannot be loaded', async () => {
    api.fetchSmartAccount.mockResolvedValue(failedRead);
    await mount(<SmartAccountCancelScreen />);
    expect(text(tree)).toContain('No pudimos cargar esto');
    expect(hasTappable(tree, 'cancel-confirm')).toBe(false);
  });
});

describe('billing', () => {
  it('shows the plan, the next charge and a preview of charges', async () => {
    await mount(<SmartAccountBillingScreen />);
    const out = text(tree);
    expect(out).toContain('Plan anual');
    expect(out).toContain('US$149.99');
    expect(out).toContain('Se renueva el');
    expect(out).toContain('US$14.99');
    expect(out).toContain('Con Confío Dollar+');
    expect(hasTappable(tree, 'billing-problem')).toBe(false);
    expect(hasTappable(tree, 'Ver todos los cobros')).toBe(false);
  });

  it('bounds the preview and opens the full list', async () => {
    api.fetchSmartAccountCharges.mockResolvedValue(pageOf(['1', '2', '3', '4', '5', '6'], true, 'c6'));
    await mount(<SmartAccountBillingScreen />);
    expect(text(tree).split('Plan mensual ·').length - 1).toBe(5);
    await tap(tree, 'Ver todos los cobros');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountCharges');
  });

  it('lays out a payment problem: amount, dates, what would be sold, and the fix', async () => {
    const base = account();
    const billing = {
      ...base.billing!, status: 'notice', shortfallUsd: '49.99', noticeStartedAt: '2026-11-21T00:00:00Z',
      saleAllowedAt: '2026-11-26T00:00:00Z', saleCandidates: ['AAPLon', 'BTCB'],
    };
    api.fetchSmartAccount.mockResolvedValue(ok(account({ billing })));
    await mount(<SmartAccountBillingScreen />);
    const out = text(tree);
    expect(out).toContain('Faltan US$49.99 para tu plan');
    expect(out).toContain('Avisos desde el');
    expect(out).toContain('Venta posible desde el');
    expect(out).toContain(DEX_TRADING_UI_ENABLED
      ? 'en este orden: AAPLon, BTCB'
      : 'en este orden: AAPLon, otras inversiones de tu cuenta');
    await tap(tree, 'billing-add');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountMove', { direction: 'in' });
    expect(billingProblem(base.billing!)).toBeNull();
  });

  it('names bitcoin and gold generically where the build cannot show them, never hiding them', () => {
    expect(saleCandidateLabels(['AAPLon', 'BTCB', 'XAUT', 'TSLAon'], false))
      .toEqual(['AAPLon', 'otras inversiones de tu cuenta', 'TSLAon']);
    expect(saleCandidateLabels(['AAPLon', 'BTCB'], true)).toEqual(['AAPLon', 'BTCB']);
  });

  it('changes plan with the server price in the label', async () => {
    await mount(<SmartAccountBillingScreen />);
    await tap(tree, 'billing-change');
    await flush();
    expect(api.prepareSmartAccountPlanChange).toHaveBeenCalledWith('monthly');
    expect(tree.root.findAll((n) => n.props.testID === 'billing-change' && typeof n.props.onPress === 'function')[0]
      .props.accessibilityLabel).toContain('US$14.99');
  });

  it('a pending plan change can be withdrawn by keeping the current plan', async () => {
    const base = account();
    api.fetchSmartAccount.mockResolvedValue(ok(account({ billing: { ...base.billing!, nextPlan: 'monthly' } })));
    await mount(<SmartAccountBillingScreen />);
    expect(tree.root.findAll((n) => n.props.testID === 'billing-change' && typeof n.props.onPress === 'function'))
      .toHaveLength(0);
    await tap(tree, 'billing-keep');
    await flush();
    expect(api.prepareSmartAccountPlanChange).toHaveBeenCalledWith(base.billing!.plan);
  });

  it('leads to the cancellation', async () => {
    await mount(<SmartAccountBillingScreen />);
    await tap(tree, 'billing-cancel');
    expect(nav.navigate).toHaveBeenCalledWith('SmartAccountCancel');
  });
});

describe('charges', () => {
  it('loads the next page at the end of the list', async () => {
    api.fetchSmartAccountCharges
      .mockResolvedValueOnce(pageOf(['1', '2'], true, 'c2'))
      .mockResolvedValueOnce(pageOf(['3'], false, null));
    await mount(<SmartAccountChargesScreen />);
    expect(api.fetchSmartAccountCharges).toHaveBeenCalledWith(20);
    const list = tree.root.findAll((n) => typeof n.props.onEndReached === 'function')[0];
    expect(list.props.initialNumToRender).toBe(20);
    expect(list.props.maxToRenderPerBatch).toBe(10);
    expect(list.props.windowSize).toBe(21);
    await act(async () => { list.props.onEndReached(); });
    await flush();
    expect(api.fetchSmartAccountCharges).toHaveBeenLastCalledWith(20, 'c2');
    expect(text(tree).split('Plan mensual ·').length - 1).toBe(3);
    await act(async () => { list.props.onEndReached(); });
    expect(api.fetchSmartAccountCharges).toHaveBeenCalledTimes(2);
  });

  it('has empty and error states', async () => {
    api.fetchSmartAccountCharges.mockResolvedValue(pageOf([]));
    await mount(<SmartAccountChargesScreen />);
    expect(text(tree)).toContain('Todavía no hay cobros');
    await act(async () => tree.unmount());
    api.fetchSmartAccountCharges.mockResolvedValue(failedRead);
    await mount(<SmartAccountChargesScreen />);
    expect(text(tree)).toContain('No pudimos cargar esto');
  });
});
