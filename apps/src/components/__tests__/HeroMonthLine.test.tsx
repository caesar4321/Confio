/** Home month strip (design C): two stat blocks, invitation, placeholder. */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { HeroMonthInvite, HeroMonthLine, HeroMonthSlot } from '../HeroMonthLine';

jest.mock('../../apollo/monthSummary', () => ({}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

const summary: any = {
  year: 2026, month: 9,
  current: { incomeUsd: '215', spendingUsd: '176.4', movementCount: 5, spendingByCategory: [] },
};

const textOf = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => (n.type as unknown) === 'Text')
    .map(n => [].concat(n.props.children).filter((c: unknown) => typeof c === 'string').join(''))
    .join('|');

const render = (el: React.ReactElement) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(el); });
  return tree;
};

describe('HeroMonthLine (strip)', () => {
  it('shows ENTRÓ EN <MES> and SALIÓ as two blocks, whole dollars', () => {
    const text = textOf(render(<HeroMonthLine summary={summary} masked={false} onPress={jest.fn()} />));
    expect(text).toContain('ENTRÓ EN SEPTIEMBRE');
    expect(text).toContain('US$215');
    expect(text).toContain('SALIÓ');
    expect(text).toContain('US$176');
  });

  it('masks both amounts on screen and for screen readers', () => {
    const tree = render(<HeroMonthLine summary={summary} masked onPress={jest.fn()} />);
    expect(textOf(tree)).not.toMatch(/215|176/);
    expect(tree.root.findByProps({ testID: 'hero-month-line' }).props.accessibilityLabel).not.toMatch(/\d{3}/);
  });

  it('large amounts are exact (no K/M) and shrink to fit one line instead of wrapping', () => {
    const big: any = { ...summary, current: { ...summary.current, incomeUsd: '1250000', spendingUsd: '123456.7' } };
    const tree = render(<HeroMonthLine summary={big} masked={false} onPress={jest.fn()} />);
    const text = textOf(tree);
    expect(text).toContain('US$1,250,000');
    expect(text).toContain('US$123,457');
    expect(text).not.toMatch(/\d[KM]\b/);
    const amounts = tree.root.findAll(n => (n.type as unknown) === 'Text' && /US\$/.test(String(n.props.children)));
    for (const a of amounts) {
      expect(a.props.numberOfLines).toBe(1);
      expect(a.props.adjustsFontSizeToFit).toBe(true);
    }
  });

  it('opens Tu mes on tap', () => {
    const onPress = jest.fn();
    const tree = render(<HeroMonthLine summary={summary} masked={false} onPress={onPress} />);
    act(() => tree.root.findAll(n => n.props.testID === 'hero-month-line' && n.props.onPress)[0].props.onPress());
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe('HeroMonthSlot', () => {
  it('invitation reads the feature name and opens Tu mes without a month', () => {
    const onPress = jest.fn();
    const tree = render(<HeroMonthSlot state={{ kind: 'invite' }} masked={false} onPress={onPress} />);
    expect(textOf(tree)).toContain('TU MES');
    const invite = tree.root.findAll(n => n.props.testID === 'hero-month-invite' && n.props.onPress)[0];
    expect(invite.props.accessibilityLabel).toContain('Tu mes');
    act(() => invite.props.onPress());
    expect(onPress).toHaveBeenCalledWith(undefined);
  });

  it('every state has the same fixed height (verbs never move), whatever the amounts', () => {
    const height = (el: React.ReactElement) => {
      const root = render(el).root;
      const strip = root.findAll(n => typeof n.props.testID === 'string' && n.props.testID.startsWith('hero-month')
        && Array.isArray(n.props.style))[0];
      return ([] as any[]).concat(strip.props.style).flat(Infinity).reduce((h: any, st: any) => (st && st.height) || h, undefined);
    };
    const big: any = { ...summary, current: { ...summary.current, incomeUsd: '9999999', spendingUsd: '9999999' } };
    const h = height(<HeroMonthSlot state={{ kind: 'month', summary }} masked={false} onPress={jest.fn()} />);
    expect(h).toBeGreaterThan(44);
    expect(height(<HeroMonthSlot state={{ kind: 'month', summary: big }} masked={false} onPress={jest.fn()} />)).toBe(h);
    expect(height(<HeroMonthSlot state={{ kind: 'month', summary }} masked onPress={jest.fn()} />)).toBe(h);
    expect(height(<HeroMonthSlot state={{ kind: 'invite' }} masked={false} onPress={jest.fn()} />)).toBe(h);
    expect(height(<HeroMonthSlot state={{ kind: 'loading' }} masked={false} onPress={jest.fn()} />)).toBe(h);
  });

  it('renders nothing for employees (hidden)', () => {
    expect(render(<HeroMonthSlot state={{ kind: 'hidden' }} masked={false} onPress={jest.fn()} />).toJSON()).toBeNull();
  });
});

describe('HeroMonthInvite', () => {
  it('exists as its own component', () => {
    expect(render(<HeroMonthInvite onPress={jest.fn()} />).toJSON()).not.toBeNull();
  });
});
