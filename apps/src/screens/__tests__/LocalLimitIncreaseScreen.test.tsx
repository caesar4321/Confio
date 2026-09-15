import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';

let mockStatus = 'forwarded';
const mockPoll = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'request' ? {limitIncreaseRequest: {id: 'edd-1', status: mockStatus}}
    : query === 'limits' ? {localMoneyLimits: {known: true, limit: '25000'}} : {},
  refetch: mockRefetch, startPolling: mockPoll, stopPolling: jest.fn(),
})}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({
  addListener: () => () => {}, goBack: jest.fn(), isFocused: () => true,
})}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {type: 'personal'}})}));
jest.mock('../../apollo/queries', () => ({GET_MY_RAMP_ADDRESS: 'address'}));
jest.mock('../../services/localMoney', () => ({
  LIMIT_INCREASE_REQUEST: 'request', LIMIT_INCREASE_REQUIREMENTS: 'requirements', LOCAL_MONEY_LIMITS: 'limits',
}));
jest.mock('../../services/diditService', () => ({}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: 'Reveal'}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
import Screen from '../LocalLimitIncreaseScreen';

beforeEach(() => {jest.clearAllMocks(); mockStatus = 'forwarded';});

it('treats forwarding as completed submission without claiming provider approval', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const texts = tree.root.findAllByType(Text).map(node => node.props.children);
  expect(texts).toContain('Tus documentos ya están adjuntos a tu cuenta de pagos locales. El procesador determina si corresponde aumentar tu límite.');
  expect(texts.join(' ')).not.toContain('Tu solicitud fue aprobada');
  expect(mockPoll).not.toHaveBeenCalled();
  const update = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Enviar nuevos documentos'))!;
  await act(async () => {update.props.onPress();});
  expect(tree.root.findAllByType(TextInput).length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});

it.each(['submitted', 'in_review'])('keeps polling while handoff is pending (%s)', async status => {
  mockStatus = status;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(mockPoll).toHaveBeenCalledWith(30000);
  expect(tree.root.findAllByType(Text).map(node => node.props.children)).not.toContain('Enviar nuevos documentos');
  await act(async () => tree.unmount());
});
