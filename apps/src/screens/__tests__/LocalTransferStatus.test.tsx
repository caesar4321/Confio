import React from 'react';
import renderer, {act} from 'react-test-renderer';

let mockStage = 'refunded';
let mockDirection = 'to_bank';
const mockStop = jest.fn();
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: jest.fn(), navigate: jest.fn(), popToTop: jest.fn()}),
  useRoute: () => ({params: {journeyId: 'journey'}}), useFocusEffect: () => {},
}));
jest.mock('@apollo/client', () => ({useApolloClient: jest.fn(), useQuery: () => ({
  data: {infiniaJourney: {internalId: 'journey', direction: mockDirection,
    stage: mockStage, localAsset: 'MXN', destinationSummary: 'CLABE', refundAmount: '1.982'}},
  stopPolling: mockStop, startPolling: jest.fn(), refetch: jest.fn().mockResolvedValue({}),
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

beforeEach(() => {mockStage = 'refunded'; mockDirection = 'to_bank'; mockStop.mockClear();});
it('shows a refund without promising a future completion', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const text = JSON.stringify(tree.toJSON());
  expect(text).toContain('1.982 USDT');
  expect(text).not.toContain('Puedes cerrar la app');
  expect(mockStop).toHaveBeenCalled();
  await act(async () => tree.unmount());
});
it('explains that an incoming conversion resumes in the foreground', async () => {
  mockStage = 'awaiting_wallet_conversion'; mockDirection = 'to_wallet';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(JSON.stringify(tree.toJSON())).toContain('se retomará cuando vuelvas');
  expect(JSON.stringify(tree.toJSON())).not.toContain('Te avisaremos cuando termine');
  await act(async () => tree.unmount());
});
