import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { HeroMonthLine } from '../HeroMonthLine';

jest.mock('../../apollo/monthSummary', () => ({}));

const summary: any = {
  year: 2026, month: 10,
  current: { incomeUsd: '420', spendingUsd: '310.4', movementCount: 5, spendingByCategory: [] },
};

const textOf = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => (n.type as unknown) === 'Text')
    .map(n => (Array.isArray(n.props.children) ? n.props.children : [n.props.children])
      .filter((c: unknown) => typeof c === 'string').join(''))
    .join('|');

describe('HeroMonthLine', () => {
  it('reads month, income and spending in US$', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<HeroMonthLine summary={summary} masked={false} onPress={jest.fn()} />); });
    const text = textOf(tree);
    expect(text).toContain('Octubre');
    expect(text).toContain('US$420');
    expect(text).toContain('US$310');
    const button = tree.root.findByProps({ testID: 'hero-month-line' });
    expect(button.props.accessibilityLabel).toContain('entraron');
  });

  it('masks both amounts, on screen and for screen readers, when the balance is hidden', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<HeroMonthLine summary={summary} masked onPress={jest.fn()} />); });
    const text = textOf(tree);
    expect(text).not.toContain('420');
    expect(text).not.toContain('310');
    const button = tree.root.findByProps({ testID: 'hero-month-line' });
    expect(button.props.accessibilityLabel).not.toMatch(/\d{3}/);
  });

  it('opens Tu mes on tap', () => {
    const onPress = jest.fn();
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<HeroMonthLine summary={summary} masked={false} onPress={onPress} />); });
    act(() => tree.root.findByProps({ testID: 'hero-month-line' }).props.onPress());
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe('HeroMonthSlot', () => {
  const { HeroMonthSlot } = require('../HeroMonthLine');
  it('line, masked line and placeholder share one sizing template (same height)', () => {
    const sizing = (el: any) => {
      let tree!: renderer.ReactTestRenderer;
      act(() => { tree = renderer.create(el); });
      const flat = (node: any): string => (typeof node === 'string' ? node
        : Array.isArray(node) ? node.map(flat).join('') : node?.children ? flat(node.children) : '');
      const isTemplate = (n: any) => [].concat(n.props?.style ?? []).flat(Infinity)
        .some((st: any) => st && st.color === 'transparent');
      const find = (n: any): any => (!n || typeof n === 'string' ? null
        : isTemplate(n) ? n : (n.children ?? []).map(find).find(Boolean) ?? null);
      return flat(find(tree.toJSON()));
    };
    const line = sizing(<HeroMonthSlot summary={summary} reserved={false} masked={false} onPress={jest.fn()} />);
    expect(sizing(<HeroMonthSlot summary={summary} reserved={false} masked onPress={jest.fn()} />)).toBe(line);
    expect(sizing(<HeroMonthSlot summary={null} reserved masked={false} onPress={jest.fn()} />)).toBe(line);
    expect(line).toContain('Septiembre');
  });
  it('renders nothing when there is no line and no reservation', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<HeroMonthSlot summary={null} reserved={false} masked={false} onPress={jest.fn()} />); });
    expect(tree.toJSON()).toBeNull();
  });
});

describe('compact amounts', () => {
  const { formatUsd } = require('../../utils/monthSummary');
  it('never renders wider than the reserved US$99,999 template', () => {
    expect(formatUsd(99999, { whole: true, compact: true })).toBe('US$99,999');
    expect(formatUsd(123456, { whole: true, compact: true })).toBe('US$123K');
    expect(formatUsd(1234567, { whole: true, compact: true })).toBe('US$1.2M');
    expect(formatUsd(123456789, { whole: true, compact: true })).toBe('US$123M');
    expect(formatUsd(99999.6, { whole: true, compact: true })).toBe('US$100K');
    for (const v of [99999.5, 99999.99, 100000, 999999, 1000000, 99999999, 999999999]) {
      expect(formatUsd(v, { whole: true, compact: true }).length).toBeLessThanOrEqual('US$99,999'.length);
    }
  });
  it('screen readers still get full amounts', () => {
    const big: any = { year: 2026, month: 10, current: { incomeUsd: '250000', spendingUsd: '10', movementCount: 5, spendingByCategory: [] } };
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<HeroMonthLine summary={big} masked={false} onPress={jest.fn()} />); });
    expect(tree.root.findByProps({ testID: 'hero-month-line' }).props.accessibilityLabel).toContain('250,000');
  });
});
