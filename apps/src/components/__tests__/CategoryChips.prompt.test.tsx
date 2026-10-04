/**
 * The success-screen category prompt is optional: it appears only when the
 * server asks, one tap saves a counterparty rule, "Ahora no" is a skip, and
 * leaving unanswered is a dismissal. A failed save never pretends it worked.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockPrompt: any = { shouldAsk: true, category: null, counterpartyName: 'Ana' };
const mockCategorize = jest.fn();
const mockRecord = jest.fn(() => Promise.resolve({ data: { recordCategoryPrompt: { success: true } } }));
const mockLog = jest.fn();

jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useQuery: (_q: any, opts: any) => (opts?.skip ? { data: undefined } : { data: { categoryPrompt: mockPrompt } }),
  useMutation: (doc: any) => [String(doc).includes('categorizeMovement') ? mockCategorize : mockRecord],
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../services/analyticsService', () => ({
  AnalyticsService: { logFunnelEvent: (...args: any[]) => mockLog(...args) },
}));

import { CategoryPrompt } from '../CategoryChips';

const mount = (props: any = { internalId: 'tx-1' }) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CategoryPrompt {...props} />); });
  return tree;
};
const has = (tree: renderer.ReactTestRenderer, testID: string) => tree.root.findAllByProps({ testID }).length > 0;
const press = async (tree: renderer.ReactTestRenderer, testID: string) => {
  await act(async () => { tree.root.findAllByProps({ testID })[0].props.onPress(); });
};

beforeEach(() => {
  mockPrompt = { shouldAsk: true, category: null, counterpartyName: 'Ana' };
  mockCategorize.mockReset();
  mockRecord.mockClear();
  mockLog.mockClear();
});

describe('CategoryPrompt', () => {
  it('renders nothing when the server says not to ask (rule exists, skip limit, no permission)', () => {
    mockPrompt = { shouldAsk: false, category: 'food', counterpartyName: 'Ana' };
    const tree = mount();
    expect(tree.toJSON()).toBeNull();
    expect(mockLog).not.toHaveBeenCalled();
  });

  it('renders nothing without a movement reference', () => {
    const tree = mount({});
    expect(tree.toJSON()).toBeNull();
  });

  it('one tap saves a counterparty rule and shows the confirmation', async () => {
    mockCategorize.mockResolvedValue({ data: { categorizeMovement: { success: true, category: 'food' } } });
    const tree = mount();
    expect(mockLog).toHaveBeenCalledWith('category_chip_shown');
    await press(tree, 'category-chip-food');
    expect(mockCategorize).toHaveBeenCalledWith({
      variables: { movementId: null, internalId: 'tx-1', category: 'food', applyTo: 'counterparty' },
    });
    expect(has(tree, 'category-confirmation')).toBe(true);
    act(() => tree.unmount());
    expect(mockRecord).not.toHaveBeenCalled(); // answered, so not a dismissal
  });

  it('a failed save reverts to the question and says so', async () => {
    mockCategorize.mockResolvedValue({ data: { categorizeMovement: { success: false, error: 'x' } } });
    const tree = mount();
    await press(tree, 'category-chip-food');
    expect(has(tree, 'category-confirmation')).toBe(false);
    expect(has(tree, 'category-prompt')).toBe(true);
    expect(JSON.stringify(tree.toJSON())).toContain('No se guardó');
  });

  it('"Ahora no" records a skip and hides; unmount then is not a dismissal', async () => {
    const tree = mount();
    await press(tree, 'category-skip');
    expect(mockRecord).toHaveBeenCalledWith({ variables: { movementId: null, internalId: 'tx-1', outcome: 'skipped' } });
    expect(tree.toJSON()).toBeNull();
    act(() => tree.unmount());
    expect(mockRecord).toHaveBeenCalledTimes(1);
  });

  it('leaving without answering records a dismissal', () => {
    const tree = mount();
    act(() => tree.unmount());
    expect(mockRecord).toHaveBeenCalledWith({ variables: { movementId: null, internalId: 'tx-1', outcome: 'dismissed' } });
    expect(mockLog).toHaveBeenCalledWith('category_chip_dismissed');
  });

  it('a payment that fails after the prompt appeared hides it without recording a dismissal', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<CategoryPrompt internalId="tx-1" status="SUBMITTED" />); });
    expect(has(tree, 'category-prompt')).toBe(true);
    act(() => tree.update(<CategoryPrompt internalId="tx-1" status="FAILED" />));
    expect(tree.toJSON()).toBeNull();
    act(() => tree.unmount());
    expect(mockRecord).not.toHaveBeenCalled();
  });

  it('a slow failed save cannot overwrite a later choice (one save at a time)', async () => {
    let fail!: () => void;
    mockCategorize.mockImplementationOnce(() => new Promise((_, reject) => { fail = () => reject(new Error('x')); }));
    const tree = mount();
    act(() => { tree.root.findAllByProps({ testID: 'category-chip-food' })[0].props.onPress(); });
    // while saving: Cambiar is disabled and further picks are ignored
    expect(tree.root.findAllByProps({ testID: 'category-change' })[0].props.disabled).toBe(true);
    await act(async () => fail());
    expect(mockCategorize).toHaveBeenCalledTimes(1);
    expect(has(tree, 'category-prompt')).toBe(true);
  });

  it('the prompt shows the quick six plus "Más", which reveals all 12 categories', async () => {
    const tree = mount();
    const chipIds = () => tree.root.findAll(n => typeof n.props.testID === 'string'
      && n.props.testID.startsWith('category-chip-') && typeof n.props.onPress === 'function')
      .map(n => n.props.testID);
    const before = [...new Set(chipIds())];
    expect(before).toEqual(expect.arrayContaining(['category-chip-food', 'category-chip-bills', 'category-chip-more']));
    expect(before).not.toContain('category-chip-health');
    await press(tree, 'category-chip-more');
    const after = [...new Set(chipIds())];
    expect(after).toEqual(expect.arrayContaining(['category-chip-health', 'category-chip-debt', 'category-chip-other']));
    expect(after).not.toContain('category-chip-more');
  });
});

