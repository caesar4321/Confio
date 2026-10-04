import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Text, TouchableOpacity } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-svg', () => {
  const R = require('react');
  const C = (p: any) => R.createElement('Svg', p, p.children);
  return { __esModule: true, default: C, Defs: C, LinearGradient: C, Rect: C, Stop: C };
});

import { SummaryCard, comparisonText, resultLabel, resultText } from '../SummaryCard';
import { ProtectionCard, SavingsCard, StableCard } from '../ProtectionCard';
import { RecurringCard } from '../RecurringCard';
import { colors } from '../../../config/theme';
import type { MonthSummary } from '../../../apollo/monthSummary';

function mount(el: React.ReactElement) {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(el); });
  return tree;
}

/** Host nodes only (a testID appears on the component and its native view). */
const byId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((n) => typeof n.type === 'string' && n.props.testID === id);

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((t) => [].concat(t.props.children).join(''));

const totals = (income: string, spending: string, count = 3) => ({
  incomeUsd: income, spendingUsd: spending, topUpsUsd: '0', withdrawalsUsd: '0', savingsNetUsd: '0',
  investmentNetUsd: '0', movementCount: count, spendingByCategory: [],
});
const summary = (income: string, spending: string): MonthSummary => ({
  year: 2026, month: 9, timezone: 'UTC', previousIsPartial: false,
  current: totals(income, spending), previous: totals('204', '170'), counterparties: [],
});

describe('Card A', () => {
  it('labels the result honestly, never red for a negative month', () => {
    expect([resultLabel(39), resultText(39, false)]).toEqual(['Te quedaron', '+US$39']);
    expect([resultLabel(0.2), resultText(0.2, false)]).toEqual(['Quedaste a mano', 'US$0']);
    expect([resultLabel(-12), resultText(-12, false)]).toEqual(['Salió más de lo que entró', '−US$12']);
    const tree = mount(<SummaryCard summary={summary('100', '112')} masked={false} runKey="k" pace={null}
      onOpenIncome={jest.fn()} onOpenSpending={jest.fn()} />);
    const result = tree.root.findByProps({ testID: 'tumes-result' });
    expect([].concat(result.props.style).some((s: any) => s?.color === colors.flowIn.text)).toBe(false);
  });

  it('keeps the "Sin contar" caption and compares with last month as a delta', () => {
    expect(comparisonText(summary('215', '176'))).toBe('vs agosto: salió US$6 más, entró US$11 más');
    const tree = mount(<SummaryCard summary={summary('215', '176')} masked={false} runKey="k" pace={null}
      onOpenIncome={jest.fn()} onOpenSpending={jest.fn()} />);
    expect(texts(tree)).toContain('Sin contar recargas, retiros ni ahorro.');
  });

  it('masks every amount and drops the comparison (it would leak the direction)', () => {
    const tree = mount(<SummaryCard summary={summary('215', '176')} masked runKey="k" pace={null}
      onOpenIncome={jest.fn()} onOpenSpending={jest.fn()} />);
    const all = texts(tree).join(' ');
    expect(all).not.toMatch(/\d{2}/);
    expect(byId(tree, 'month-comparison')).toHaveLength(0);
  });

  it('exposes Entró and Salió as separate buttons', () => {
    const onIn = jest.fn(); const onOut = jest.fn();
    const tree = mount(<SummaryCard summary={summary('215', '176')} masked={false} runKey="k" pace={null}
      onOpenIncome={onIn} onOpenSpending={onOut} />);
    tree.root.findByProps({ testID: 'total-income' }).props.onPress();
    tree.root.findByProps({ testID: 'total-spending' }).props.onPress();
    expect([onIn.mock.calls.length, onOut.mock.calls.length]).toEqual([1, 1]);
  });
});

describe('dollar slot cards', () => {
  const protection = { currency: 'BOB', basis: 'purchase' as const, state: 'gained' as const, source: 'binance_p2p', protectedUsd: '100.00', paidLocal: '690.00', todayLocal: '740.00',
    gainLocal: '50.00', avgRate: '6.90', todayRate: '7.40', quotedAt: new Date().toISOString() };

  it('protection: sentence, two bars, and the explainer sheet from the same quote', () => {
    const tree = mount(<ProtectionCard value={protection} month={10} masked={false} />);
    const all = texts(tree).join(' ');
    expect(all).toContain('Bs 50 más');
    expect(all).toContain('Pagaste');
    const label = tree.root.find((n) => typeof n.type === 'string' && /Tu dólar te protegió:/.test(n.props.accessibilityLabel ?? ''));
    expect(label.props.accessibilityLabel).toContain('50 bolivianos más de lo que pagaste');
    act(() => { tree.root.findByProps({ testID: 'tumes-protection-how' }).props.onPress(); });
    const sheet = texts(tree).join(' ');
    expect(sheet).toContain('Bs 6.90 por dólar');
    expect(sheet).toContain('Hoy (Binance P2P)');
    expect(sheet).toContain('Bs 7.40 por dólar');
    expect(sheet).toMatch(/hoy, \d\d:\d\d/);
  });

  it('protection masked: no sentence, no amounts, sheet rates hidden', () => {
    const tree = mount(<ProtectionCard value={protection} month={10} masked />);
    act(() => { tree.root.findByProps({ testID: 'tumes-protection-how' }).props.onPress(); });
    expect(texts(tree).join(' ')).not.toMatch(/Bs \d/);
  });

  it('Venezuela compares with the 1st of the month, both at Binance P2P', () => {
    const tree = mount(<ProtectionCard value={{ ...protection, currency: 'VES', basis: 'month_start' }} month={10} masked={false} />);
    const all = texts(tree).join(' ');
    expect(all).toContain('1 oct');
    const label = tree.root.find((n) => typeof n.type === 'string' && /Tu dólar te protegió:/.test(n.props.accessibilityLabel ?? ''));
    expect(label.props.accessibilityLabel).toContain('bolívares más que el 1 de octubre');
    expect(all).not.toContain('Pagaste');
    act(() => { tree.root.findByProps({ testID: 'tumes-protection-how' }).props.onPress(); });
    expect(texts(tree).join(' ')).toContain('El 1 de octubre (Binance P2P)');
  });

  it('stable: the dollars kept their dollar value, no local amounts, no loss', () => {
    const tree = mount(<StableCard value={{ ...protection, state: 'stable', gainLocal: '-150' }} masked={false} />);
    const all = texts(tree).join(' ');
    expect(all).toContain('Tu dólar se mantuvo');
    expect(all).not.toMatch(/Bs|-150|perd/);
    const masked = mount(<StableCard value={{ ...protection, state: 'stable' }} masked />);
    expect(texts(masked).join(' ')).not.toContain('US$');
  });

  it('savings: cents, and bars only from the third day', () => {
    const two = { earnedUsd: '0.42', daily: [{ date: '2026-10-01', usd: '0.2' }, { date: '2026-10-02', usd: '0.22' }] };
    let tree = mount(<SavingsCard value={two} month={10} masked={false} />);
    expect(texts(tree)).toContain('~US$0.42');
    expect(byId(tree, 'tumes-savings-bars')).toHaveLength(0);
    const three = { ...two, daily: [...two.daily, { date: '2026-10-03', usd: '0.1' }] };
    tree = mount(<SavingsCard value={three} month={10} masked={false} />);
    expect(byId(tree, 'tumes-savings-bars')).toHaveLength(1);
  });
});

describe('Pagos habituales', () => {
  const item = (key: string, day: number) => ({ counterpartyKey: key, name: key, expectedDay: day, expectedAmountUsd: '100.00', category: null });

  it('sorts by day, greys passed days, shows the viewed month\'s date', () => {
    const tree = mount(<RecurringCard items={[item('wilber', 20), item('karen', 5)]} year={2026} month={10}
      today={new Date(2026, 9, 12)} masked={false} onOpen={jest.fn()} />);
    const all = texts(tree);
    expect(all.indexOf('karen')).toBeLessThan(all.indexOf('wilber'));
    expect(all).toEqual(expect.arrayContaining(['5 oct', '20 oct', 'casi cada mes', '~US$100']));
    expect(byId(tree, 'tumes-pill-past')).toHaveLength(1);
  });

  it('caps at three rows and expands in place', () => {
    const items = ['a', 'b', 'c', 'd', 'e'].map((k, i) => item(k, i + 1));
    const tree = mount(<RecurringCard items={items} year={2026} month={10} today={new Date(2026, 9, 1)}
      masked={false} onOpen={jest.fn()} />);
    const rows = () => tree.root.findAll((n) => typeof n.props.testID === 'string' && n.props.testID.startsWith('tumes-recurring-')
      && n.props.testID !== 'tumes-recurring-more' && n.type === TouchableOpacity);
    expect(rows()).toHaveLength(3);
    expect(texts(tree)).toContain('+2 más');
    act(() => { tree.root.findByProps({ testID: 'tumes-recurring-more' }).props.onPress(); });
    expect(rows()).toHaveLength(5);
    expect(texts(tree)).toContain('Ver menos');
  });

  it('masks amounts in text and in spoken labels', () => {
    const tree = mount(<RecurringCard items={[item('karen', 5)]} year={2026} month={10}
      today={new Date(2026, 9, 1)} masked onOpen={jest.fn()} />);
    expect(texts(tree).join(' ')).not.toContain('US$');
    const row = tree.root.findByProps({ testID: 'tumes-recurring-karen' });
    expect(row.props.accessibilityLabel).toContain('monto oculto');
  });
});
