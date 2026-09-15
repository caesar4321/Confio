import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text} from 'react-native';

let mockBusiness = false;
let mockDocuments: any[] | null = [];
const mockReason = 'El documento no coincide con tu identidad verificada.';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray) => parts.join(''),
  useMutation: () => [jest.fn()],
  useQuery: (query: string) => ({loading: false, refetch: jest.fn().mockResolvedValue({}), data:
    query.includes('MyIdentityDocuments') ? (mockDocuments === null ? {} : {myIdentityDocuments: mockDocuments})
      : query === 'personal' ? {myPersonalKycStatus: {status: 'rejected', statusDetail: mockReason}}
        : query === 'business' ? {businessKycStatus: {status: 'rejected', statusDetail: mockReason}} : {},
  }),
}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({}), useFocusEffect: () => {}}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {
  type: mockBusiness ? 'business' : 'personal', business: {id: '1', name: 'Business'},
}})}));
jest.mock('../../hooks/useRampCountry', () => ({useRampCountry: () => ({countryCode: 'PY', isBlocked: false})}));
jest.mock('../../apollo/queries', () => ({GET_ME: 'me', GET_MY_KYC_STATUS: 'any', GET_MY_PERSONAL_KYC_STATUS: 'personal', GET_BUSINESS_KYC_STATUS: 'business'}));
jest.mock('../../apollo/mutations', () => ({CREATE_DIDIT_VERIFICATION_SESSION: 'create', SYNC_DIDIT_VERIFICATION_SESSION: 'sync'}));
jest.mock('../../services/diditService', () => ({getDiditResultSessionId: jest.fn(), startDiditVerification: jest.fn()}));
jest.mock('../../services/analyticsService', () => ({AnalyticsService: {logEvent: jest.fn()}}));
jest.mock('../../navigation/Header', () => ({Header: () => null}));
jest.mock('../../components/common/Button', () => ({Button: () => null}));
jest.mock('../../components/common/InlineBanner', () => ({InlineBanner: () => null}));

import VerificationScreen from '../VerificationScreen';

beforeEach(() => { mockBusiness = false; mockDocuments = []; });

it.each([false, true])('retains the rejection reason on a document card (additional=%s)', async additional => {
  mockDocuments = [{id: '1', documentType: 'national_id', issuingCountry: 'PY', status: 'rejected',
    isAdditional: additional, localCountries: [], rejectedReason: mockReason}];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(tree.root.findAllByType(Text).some(n => n.props.children === mockReason)).toBe(true);
  await act(async () => tree.unmount());
});

it.each([false, true])('retains the rejection reason in status views (business=%s)', async business => {
  mockBusiness = business;
  mockDocuments = null;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(tree.root.findAllByType(Text).some(n => n.props.children === mockReason)).toBe(true);
  await act(async () => tree.unmount());
});
