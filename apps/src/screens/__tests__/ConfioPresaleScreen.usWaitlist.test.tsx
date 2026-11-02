/**
 * US residents can't buy the presale yet, but wait for a US exemption: the
 * purchase button becomes the waitlist, and joining reaches the server
 * instead of stopping at the client-side US block.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert } from 'react-native';

const mockNavigate = jest.fn();
const mockMutate = jest.fn();
let mockCountry: any;
let mockSelected: any;

jest.mock('@react-navigation/native', () => {
  const navigation = { goBack: jest.fn(), navigate: (...a: any[]) => mockNavigate(...a) };
  return { useNavigation: () => navigation };
});
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useApolloClient: () => ({ mutate: (...a: any[]) => mockMutate(...a) }),
  useQuery: (query: any, options?: any) => {
    if (options?.skip) return {};
    if (query === 'curve') {
      return {
        loading: false,
        data: {
          presaleChain: 'bsc',
          presaleCurveStats: {
            currentPrice: '0.20', startPrice: '0.20', finalPrice: '1.00',
            totalRaisedUsd: '4000', nextMilestoneUsd: '10000', participants: 40,
          },
        },
      };
    }
    if (query === 'active') return { data: { activePresalePhase: { phaseNumber: 1 } } };
    if (query === 'status') return { data: { isPresaleClaimsUnlocked: false } };
    return {};
  },
}));
jest.mock('../../apollo/queries', () => ({
  GET_PRESALE_CURVE_STATS: 'curve',
  GET_ACTIVE_PRESALE: 'active',
  GET_PRESALE_STATUS: 'status',
  GET_MY_PRESALE_ONCHAIN_INFO: 'onchain',
}));
jest.mock('../../services/presaleWs', () => ({ PresaleWsSession: class {} }));
jest.mock('../../services/algorandService', () => ({ __esModule: true, default: {} }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/LoadingOverlay', () => ({ LoadingOverlay: () => null }));
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: () => null }));
jest.mock('../../components/ConfioNarrative', () => ({
  CONFIO_DOCUMENTS: {}, TrustPillars: () => null, openConfioDocument: jest.fn(),
}));
jest.mock('../../contexts/CountryContext', () => ({
  useCountry: () => ({ selectedCountry: mockSelected ?? mockCountry, userCountry: mockCountry }),
}));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { type: 'personal' } }) }));
jest.mock('../../contexts/NumberLocaleProvider', () => ({ useNumberLocale: () => undefined }));
jest.mock('../../utils/numberLocale', () => ({
  ...jest.requireActual('../../utils/numberLocale'),
  getNumberLocaleCountry: () => 'HN',
}));
jest.mock('../../assets/png/CONFIO.png', () => 1);

import { ConfioPresaleScreen } from '../ConfioPresaleScreen';

let tree: renderer.ReactTestRenderer;
const mount = async (iso: string, pickerIso?: string) => {
  mockCountry = ['', '', iso];
  mockSelected = pickerIso ? ['', '', pickerIso] : undefined;
  await act(async () => { tree = renderer.create(<ConfioPresaleScreen />); });
};
const button = (title: string) =>
  tree.root.findAll(node => node.props.title === title && typeof node.props.onPress === 'function')[0];

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  mockMutate.mockResolvedValue({ data: { joinPresaleWaitlist: { success: true, message: 'ok', alreadyJoined: false } } });
});
afterEach(() => {
  act(() => { tree?.unmount(); });
  jest.restoreAllMocks();
});

it('offers US residents the waitlist instead of the purchase', async () => {
  await mount('US');

  expect(button('Participar en la Preventa')).toBeUndefined();
  await act(async () => { await button('Unirme a la lista de espera').props.onPress(); });

  expect(mockMutate).toHaveBeenCalledTimes(1);
  expect(Alert.alert).toHaveBeenCalledWith('Lista de Espera', 'ok', expect.anything());
  expect(mockNavigate).not.toHaveBeenCalled();
});

it('follows residence, not a country picked on the exchange', async () => {
  await mount('US', 'AR');

  expect(button('Participar en la Preventa')).toBeUndefined();
  expect(button('Unirme a la lista de espera')).toBeDefined();
});

it('keeps the purchase for everyone else', async () => {
  await mount('HN');

  expect(button('Unirme a la lista de espera')).toBeUndefined();
  await act(async () => { button('Participar en la Preventa').props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('ConfioPresaleParticipate');
});

it('still refuses other blocked countries', async () => {
  await mount('GB');

  await act(async () => { button('Participar en la Preventa').props.onPress(); });
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(Alert.alert).toHaveBeenCalledWith('Restricción', expect.stringContaining('Reino Unido'));
});
