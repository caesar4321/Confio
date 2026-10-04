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
