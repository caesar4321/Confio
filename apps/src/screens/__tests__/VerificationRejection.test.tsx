import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, Linking} from 'react-native';
import {startDiditVerification} from '../../services/diditService';

let mockBusiness = false;
let mockDocuments: any[] | null = [];
let mockBusinessStatus: string | null = 'rejected';
let mockAnyStatus: string | null = null;
let mockPersonalStatus: string | null = 'rejected';
const mockCreateSession = jest.fn();
const mockSyncSession = jest.fn();
const mockBrowserSession = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
const mockReason = 'El documento no coincide con tu identidad verificada.';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray) => parts.join(''),
  useMutation: (query: string) => [query === 'create' ? mockCreateSession : query === 'browser' ? mockBrowserSession : mockSyncSession],
  useQuery: (query: string) => ({loading: false, refetch: mockRefetch, data:
    query.includes('MyIdentityDocuments') ? (mockDocuments === null ? {} : {myIdentityDocuments: mockDocuments})
      : query === 'personal' ? {myPersonalKycStatus: {status: mockPersonalStatus, statusDetail: mockPersonalStatus ? mockReason : null}}
        : query === 'business' ? {businessKycStatus: mockBusinessStatus ? {status: mockBusinessStatus, statusDetail: mockReason} : null}
          : query === 'any' ? {myKycStatus: {status: mockAnyStatus, statusDetail: 'Personal verification'}} : {},
  }),
}));
let mockRouteParams: any;
const mockSetParams = jest.fn();
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({setParams: mockSetParams}), useFocusEffect: () => {}, useRoute: () => ({params: mockRouteParams}),
}));
let mockAccountLoading = false;
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: mockAccountLoading ? null : {
  type: mockBusiness ? 'business' : 'personal', business: {id: '1', name: 'Business'},
}})}));
jest.mock('../../hooks/useRampCountry', () => ({useRampCountry: () => ({countryCode: 'PY', isBlocked: false})}));
jest.mock('../../apollo/queries', () => ({GET_ME: 'me', GET_MY_KYC_STATUS: 'any', GET_MY_PERSONAL_KYC_STATUS: 'personal', GET_BUSINESS_KYC_STATUS: 'business'}));
jest.mock('../../apollo/mutations', () => ({
  CREATE_DIDIT_VERIFICATION_SESSION: 'create', CREATE_DIDIT_BROWSER_VERIFICATION_SESSION: 'browser', SYNC_DIDIT_VERIFICATION_SESSION: 'sync',
}));
jest.mock('../../services/diditService', () => ({getDiditResultSessionId: jest.fn(), startDiditVerification: jest.fn()}));
jest.mock('../../services/analyticsService', () => ({AnalyticsService: {logEvent: jest.fn()}}));
jest.mock('../../navigation/Header', () => ({Header: () => null}));
jest.mock('../../components/common/Button', () => ({Button: 'Button'}));
jest.mock('../../components/common/InlineBanner', () => ({InlineBanner: () => null}));

import VerificationScreen from '../VerificationScreen';

beforeEach(() => { mockRouteParams = undefined; mockSetParams.mockReset(); mockAccountLoading = false; mockBusiness = false; mockDocuments = []; mockBusinessStatus = 'rejected'; mockAnyStatus = null; mockPersonalStatus = 'rejected'; });

it.each(['verified', 'pending', 'rejected'])('does not use %s personal KYC for an unverified business', async personalStatus => {
  mockBusiness = true;
  mockBusinessStatus = null;
  mockAnyStatus = personalStatus;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  const texts = tree.root.findAllByType(Text).map(n => n.props.children);
  expect(texts).toContain('Sin verificar');
  expect(texts).not.toContain('Personal verification');
  expect(texts).not.toContain('Tu negocio está verificado.');
  expect(texts).not.toContain('Verifica tu identidad');
  await act(async () => tree.unmount());
});

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

it.each(['In Review', 'Awaiting User', 'Resubmission Requested'])('keeps business %s in progress', async status => {
  mockBusiness = true;
  mockBusinessStatus = status;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  const texts = tree.root.findAllByType(Text).map(n => n.props.children);
  expect(texts).toContain('En revisión');
  expect(texts).not.toContain('Sin verificar');
  await act(async () => tree.unmount());
});

it('opens a server-bound hosted business session instead of the personal native SDK', async () => {
  mockBusiness = true;
  mockBusinessStatus = 'pending';
  mockCreateSession.mockResolvedValue({data: {createDiditVerificationSession: {success: true,
    session: {sessionId: 'kyb-1', sessionUrl: 'https://verify.didit.me/session/kyb-1'}}}});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  await act(async () => { await tree.root.findByType('Button' as any).props.onPress(); });
  expect(open).toHaveBeenCalledWith('https://verify.didit.me/session/kyb-1');
  expect(startDiditVerification).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('does not open a generic workflow or an untrusted hosted URL', async () => {
  mockBusiness = true;
  mockCreateSession.mockResolvedValue({data: {createDiditVerificationSession: {success: true,
    session: {sessionId: 'kyb-1', sessionUrl: 'https://verify.didit.me/u/generic'}}}});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  await act(async () => { await tree.root.findByType('Button' as any).props.onPress(); });
  expect(open).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('never uses latest business verification for an unverified personal account', async () => {
  mockDocuments = null;
  mockPersonalStatus = null;
  mockAnyStatus = 'verified';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(tree.root.findAllByType(Text).map(n => n.props.children)).toContain('Sin verificar');
  await act(async () => tree.unmount());
});

const browserLink = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => n.props.accessibilityRole === 'button' && typeof n.props.onPress === 'function'
    && n.findAllByType(Text).some(t => String(t.props.children).includes('navegador')), {deep: false});

it('offers personal verification on Didit\'s page in the browser', async () => {
  mockPersonalStatus = null;
  mockBrowserSession.mockResolvedValue({data: {createDiditVerificationSession: {success: true,
    session: {sessionId: 'web-1', sessionUrl: 'https://verify.didit.me/session/web-1'}}}});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  const links = browserLink(tree);
  expect(links).toHaveLength(1);
  await act(async () => { await links[0].props.onPress(); });
  expect(open).toHaveBeenCalledWith('https://verify.didit.me/session/web-1');
  expect(startDiditVerification).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('never opens an untrusted link from the browser fallback', async () => {
  mockPersonalStatus = null;
  mockBrowserSession.mockResolvedValue({data: {createDiditVerificationSession: {success: true,
    session: {sessionId: 'web-1', sessionUrl: 'https://evil.example/session/web-1'}}}});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  await act(async () => { await browserLink(tree)[0].props.onPress(); });
  expect(open).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('keeps the browser fallback off business accounts and additional documents', async () => {
  mockBusiness = true;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(browserLink(tree)).toHaveLength(0);
  await act(async () => tree.unmount());

  mockBusiness = false;
  mockDocuments = [{id: '1', documentType: 'passport', issuingCountry: 'CO', status: 'rejected',
    isAdditional: true, localCountries: [], rejectedReason: mockReason},
  {id: '2', documentType: 'national_id', issuingCountry: 'PY', status: 'verified',
    isAdditional: false, localCountries: [], rejectedReason: null}];
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(browserLink(tree)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('syncs the session Didit\'s redirect names, then clears it', async () => {
  mockPersonalStatus = null;
  mockSyncSession.mockReset().mockResolvedValue({data: {syncDiditVerificationSession: {success: true, verificationStatus: 'pending'}}});
  mockRouteParams = {verificationSessionId: 'web-2', status: 'Approved'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(mockSyncSession).toHaveBeenCalledTimes(1);
  expect(mockSyncSession).toHaveBeenCalledWith({variables: {sessionId: 'web-2'}});
  expect(mockSetParams).toHaveBeenCalledWith({verificationSessionId: undefined, status: undefined});
  await act(async () => tree.unmount());
});

it('ignores a malformed redirected session id', async () => {
  mockSyncSession.mockReset();
  mockRouteParams = {verificationSessionId: '../admin'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(mockSyncSession).not.toHaveBeenCalled();
  expect(mockSetParams).toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('leaves business redirects to the webhook', async () => {
  mockBusiness = true;
  mockSyncSession.mockReset();
  mockRouteParams = {verificationSessionId: 'kyb-8', status: 'Approved'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(mockSyncSession).not.toHaveBeenCalled();
  expect(mockSetParams).toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('waits for the active account before handling a redirect', async () => {
  mockBusiness = true;
  mockAccountLoading = true;
  mockSyncSession.mockReset();
  mockRouteParams = {verificationSessionId: 'kyb-cold', status: 'Approved'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  expect(mockSetParams).not.toHaveBeenCalled();
  mockAccountLoading = false;
  await act(async () => { tree.update(<VerificationScreen />); });
  expect(mockSyncSession).not.toHaveBeenCalled();
  expect(mockSetParams).toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('never shows the session link when no browser can open it', async () => {
  mockPersonalStatus = null;
  mockBrowserSession.mockResolvedValue({data: {createDiditVerificationSession: {success: true,
    session: {sessionId: 'web-4', sessionUrl: 'https://verify.didit.me/session/web-4'}}}});
  const open = jest.spyOn(Linking, 'openURL').mockRejectedValue(
    new Error("Could not open URL 'https://verify.didit.me/session/web-4': No Activity found"));
  const banners: any[] = [];
  const banner = jest.requireMock('../../components/common/InlineBanner');
  const original = banner.InlineBanner;
  banner.InlineBanner = (props: any) => { banners.push(props.message); return null; };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<VerificationScreen />); });
  await act(async () => { await browserLink(tree)[0].props.onPress(); });
  expect(banners.length).toBeGreaterThan(0);
  expect(banners.some(m => String(m).includes('verify.didit.me'))).toBe(false);
  await act(async () => tree.unmount());
  banner.InlineBanner = original;
  open.mockRestore();
});
