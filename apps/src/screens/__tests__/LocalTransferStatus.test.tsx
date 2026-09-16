import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {RefreshControl} from 'react-native';

let mockStage = 'refunded';
let mockDirection = 'to_bank';
const mockStop = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: jest.fn(), navigate: jest.fn(), popToTop: jest.fn()}),
  useRoute: () => ({params: {journeyId: 'journey'}}), useFocusEffect: () => {},
}));
jest.mock('@apollo/client', () => ({useApolloClient: jest.fn(), useQuery: () => ({
  data: {infiniaJourney: {internalId: 'journey', direction: mockDirection,
    stage: mockStage, localAsset: 'MXN', destinationSummary: 'CLABE', refundAmount: '1.982'}},
  stopPolling: mockStop, startPolling: jest.fn(), refetch: mockRefetch,
})}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../services/infiniaJourney', () => ({infiniaStage: (stage: string) => stage}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: 'Reveal'}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../services/localMoney', () => ({
  LOCAL_JOURNEY: 'journey', LOCAL_JOURNEY_BRIDGE: 'bridge', LOCAL_JOURNEYS: 'journeys',
  journeySteps: () => ['Convirtiendo', 'Completado'], journeyStepIndex: () => 0,
}));
import Screen from '../LocalTransferStatusScreen';

// RefreshControl is a React element prop with an owner cycle, not screen text.
const screenText = (tree: renderer.ReactTestRenderer) =>
  JSON.stringify(tree.toJSON(), (key, value) => key === 'refreshControl' ? undefined : value);

beforeEach(() => {mockStage = 'refunded'; mockDirection = 'to_bank'; mockStop.mockClear(); mockRefetch.mockReset().mockResolvedValue({data: {infiniaJourney: {}}});});
it('shows a refund without promising a future completion', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const text = screenText(tree);
  expect(text).toContain('1.982 USDT');
  expect(text).not.toContain('Puedes cerrar la app');
  expect(mockStop).toHaveBeenCalled();
  await act(async () => tree.unmount());
});
it('explains that an incoming conversion resumes in the foreground', async () => {
  mockStage = 'awaiting_wallet_conversion'; mockDirection = 'to_wallet';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(screenText(tree)).toContain('se retomará cuando vuelvas');
  expect(screenText(tree)).not.toContain('Te avisaremos cuando termine');
  await act(async () => tree.unmount());
});

it('pulls both status queries and keeps the last status when refresh fails', async () => {
  mockStage = 'converting';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  mockRefetch.mockRejectedValueOnce(new Error('offline'));
  await act(async () => {await tree.root.findByType(RefreshControl).props.onRefresh();});
  expect(mockRefetch).toHaveBeenCalledTimes(2);
  expect(screenText(tree)).toContain('última información disponible');
  expect(screenText(tree)).toContain('En proceso');
  expect(tree.root.findByType(RefreshControl).props.refreshing).toBe(false);
  await act(async () => {await tree.root.findByType(RefreshControl).props.onRefresh();});
  expect(screenText(tree)).not.toContain('última información disponible');
  await act(async () => tree.unmount());
});

it('shows the refresh spinner and prevents overlapping manual refreshes', async () => {
  let finish!: (value: any) => void;
  // Both reads share this pending result so neither is left unresolved.
  const pending = new Promise(resolve => {finish = resolve;});
  mockRefetch.mockReturnValue(pending);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  act(() => {void tree.root.findByType(RefreshControl).props.onRefresh();});
  expect(tree.root.findByType(RefreshControl).props.refreshing).toBe(true);
  act(() => {void tree.root.findByType(RefreshControl).props.onRefresh();});
  expect(mockRefetch).toHaveBeenCalledTimes(2);
  await act(async () => {finish({}); await pending;});
  expect(tree.root.findByType(RefreshControl).props.refreshing).toBe(false);
  await act(async () => tree.unmount());
});
