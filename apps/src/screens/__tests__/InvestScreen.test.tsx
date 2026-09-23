import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
let mockEnabled = true;
let mockEmployee = false;
let mockClaims = false;
let mockPhase: any = {
  name: 'Fase 1', pricePerToken: '0.25', totalRaised: '4084', goalAmount: '10000',
  progressPercentage: 40.84, totalParticipants: 312,
};
let mockPositions: any[] = [];
let mockCurve: any = null;
let mockKnown = true;
let mockCurveLoading = false;
let mockClaimable = 0;

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate }),
  useFocusEffect: (fn: any) => { require('react').useEffect(fn, [fn]); },
  useIsFocused: () => true,
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('../../components/svg/StocksMark', () => 'StocksMark');
jest.mock('../../assets/png/Ondo.png', () => 1);
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: 'BrandFieldBackground' }));
jest.mock('../../utils/numberFormatting', () => ({
  useNumberFormat: () => ({
    formatNumber: (v: number, o: any = {}) => v.toLocaleString('en-US', o),
  }),
}));
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({
    stocks: [
      { ticker: 'SPY', name: 'S&P 500', dayChangePct: 0.8 },
      { ticker: 'QQQ', name: 'NASDAQ 100', dayChangePct: -0.3 },
      { ticker: 'GLD', name: 'Oro', dayChangePct: 0.1 },
      { ticker: 'AAPL', name: 'Apple', dayChangePct: 0.2 },
    ],
  }),
}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({
    stocks: {
      enabled: mockEnabled,
      eligibilityKnown: mockKnown,
      positions: mockPositions,
      totalUsd: mockPositions.reduce((s, p) => s + p.valueUsd, 0),
      earnedTodayUsd: 0,
    },
  }),
}));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { isEmployee: mockEmployee } }) }));
jest.mock('../../apollo/queries', () => ({
  GET_ACTIVE_PRESALE: 'active', GET_PRESALE_STATUS: 'status',
  GET_PRESALE_CURVE_STATS: 'curve', GET_MY_PRESALE_ONCHAIN_INFO: 'onchain',
}));
jest.mock('@apollo/client', () => ({
  useQuery: (query: string) => ({
    loading: query === 'curve' && mockCurveLoading,
    data: query === 'active' ? { activePresalePhase: mockPhase }
      : query === 'curve' ? { presaleCurveStats: mockCurve }
        : query === 'onchain' ? { myPresaleOnchainInfo: { claimable: mockClaimable } }
          : { isPresaleClaimsUnlocked: mockClaims },
    refetch: () => Promise.resolve(),
  }),
}));

import { InvestScreen } from '../InvestScreen';

const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => {
  mockEnabled = true; mockEmployee = false; mockClaims = false; mockPositions = [];
  mockCurve = { currentPrice: '0.25', totalRaisedUsd: '4084', nextMilestoneUsd: '10000', participants: 312 };
  mockCurveLoading = false; mockClaimable = 0;
  mockPhase = {
    name: 'Fase 1', pricePerToken: '0.25', totalRaised: '4084', goalAmount: '10000',
    progressPercentage: 40.84, totalParticipants: 312,
  };
  jest.clearAllMocks();
});

it('opens both investment flows', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  await act(async () => { tree.root.findByProps({ accessibilityLabel: 'Acciones de EE. UU.' }).props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('StocksList');
  await act(async () => { tree.root.findByProps({ accessibilityLabel: '$CONFIO' }).props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('ConfioPresale');
  await act(async () => tree.unmount());
});

it('shows each door with a live signal: market tickers and the raise progress', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('S&P 500');
  expect(t).toContain('NASDAQ 100');
  expect(t).toContain('Participar en la preventa');
  expect(t).toContain('Fase 1');
  expect(t).toContain('312 participantes');
  expect(t).toContain('$4,084');
  expect(t).toContain(' · meta $10,000');
  // Careful framing: risk stated on the card, no growth promise, no count.
  expect(t).toContain('Un token nuevo puede perder valor');
  expect(t).not.toMatch(/Haz crecer|Dos caminos/);
  expect(t).toContain('No disponible para residentes de EE.UU.');
  expect(t).not.toContain('Corea');
  await act(async () => tree.unmount());
});

it('shows the user their own stock position instead of the pitch', async () => {
  mockPositions = [{ ticker: 'SPY', valueUsd: 60.42 }];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('Tu inversión');
  expect(t).toContain('$60.42');
  expect(t).toContain('Ver mis acciones');
  await act(async () => tree.unmount());
});

it('does not expose stocks when eligibility or the feature flag denies access', async () => {
  mockEnabled = false;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  expect(tree.root.findAllByProps({ accessibilityLabel: 'Acciones de EE. UU.' })).toHaveLength(0);
  // Not silently missing: the muted card explains who cannot use it.
  expect(tree.root.findAllByProps({ accessibilityLabel: 'Acciones de EE. UU., no disponible para tu cuenta' }).length).toBeGreaterThan(0);
  expect(text(tree)).toContain('No se ofrece a residentes de EE.UU. ni de Brasil.');
  expect(tree.root.findAllByProps({ accessibilityLabel: '$CONFIO' }).length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});

it('does not add investment entry points for employees', async () => {
  mockEmployee = true;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  expect(tree.root.findAllByProps({ accessibilityRole: 'button' })).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('prices from the live curve, not the stale phase row', async () => {
  mockCurve = { currentPrice: '0.31', totalRaisedUsd: '5200', nextMilestoneUsd: '8000', participants: 400 };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('$0.3100 por token');
  expect(t).not.toContain('$0.2500');
  expect(t).toContain('$5,200');
  expect(t).toContain('400 participantes');
  await act(async () => tree.unmount());
});

it.each([true, false])('never substitutes phase pricing when curve data is missing (loading=%s)', async loading => {
  mockCurve = null;
  mockCurveLoading = loading;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('Fase 1');
  expect(t).toContain('Participar en la preventa');
  expect(t).not.toContain('por token');
  expect(t).not.toContain('$4,084');
  expect(t).not.toContain('meta $10,000');
  expect(t).not.toContain('312 participantes');
  expect(t).toContain(loading ? 'Cargando datos de la preventa' : 'Datos de la preventa no disponibles');
  await act(async () => tree.unmount());
});

it('retains the last real curve price while refreshing', async () => {
  mockCurveLoading = true;
  mockCurve.currentPrice = '0.31';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  expect(text(tree)).toContain('$0.3100 por token');
  expect(text(tree)).not.toContain('$0.2500');
  await act(async () => tree.unmount());
});

it('open claims are not a personal promise when this user has nothing to claim', async () => {
  mockClaims = true; mockClaimable = 0;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).not.toContain('Reclamar mis tokens');
  expect(t).toContain('Conocer $CONFIO');
  await act(async () => tree.unmount());
});

it('switches from presale to claims when this user has tokens to claim', async () => {
  mockClaims = true; mockClaimable = 1200;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('Reclamar mis tokens');
  expect(t).not.toContain('Participar en la preventa');
  await act(async () => tree.unmount());
});

it('without an active phase, invites to learn about $CONFIO', async () => {
  mockPhase = null;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  const t = text(tree);
  expect(t).toContain('Conocer $CONFIO');
  expect(t).not.toContain('participantes');
  await act(async () => tree.unmount());
});

it('does not claim "no disponible" before eligibility is known (loading or failed)', async () => {
  mockEnabled = false; mockKnown = false;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  expect(text(tree)).not.toContain('No disponible para tu cuenta');
  await act(async () => tree.unmount());
});
