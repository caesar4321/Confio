// "Invitar y ganar": the referral programme, on its own screen.
import React from 'react';
import { Linking, Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockLogFunnel = jest.fn();
let mockAccount: any = { id: 'personal_0', type: 'personal' };
let mockProfile: any = { id: 7, username: 'ana', referralCount: 0 };
let mockSummary: any = null;
let mockReferrals: any[] = [];

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../assets/svg/WhatsApp.svg', () => 'WhatsAppLogo');
jest.mock('../common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../CommissionsEntryRow', () => ({ CommissionsEntryRow: 'CommissionsEntryRow' }));
jest.mock('../StatusTierBadge', () => ({ TierProgress: 'TierProgress' }));
jest.mock('../../apollo/queries', () => ({ GET_MY_REFERRALS: 'referrals' }));
jest.mock('@apollo/client', () => ({ useQuery: () => ({ data: { myReferrals: mockReferrals } }) }));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: mockProfile }) }));
jest.mock('../../hooks/useFeeReferralSummary', () => ({
  DEFAULT_TERMS: { windowDays: 365 },
  commissionPercents: () => ({ sharePct: '50%' }),
  useFeeReferralSummary: () => mockSummary,
  windowRule: () => 'Durante un año',
}));
jest.mock('../../services/analyticsService', () => ({
  AnalyticsService: { logFunnelEvent: (...args: unknown[]) => mockLogFunnel(...args) },
}));
jest.mock('../../utils/inviteLinks', () => ({
  buildInviteLink: ({ username }: { username: string }) => `https://confio.lat/invite/${username}`,
  buildReferralShareMessage: (username: string) => `Únete con @${username}`,
  normalizeInviteUsername: (username: string) => username,
}));

import { ReferralProgramCard } from '../ReferralProgramCard';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const pressText = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => typeof n.props.onPress === 'function'
    && n.findAllByType(RNText).some((t) => [t.props.children].flat(Infinity).join('') === label)).pop();
  if (!node) throw new Error(`nothing pressable says ${label}`);
  await act(async () => { await node.props.onPress(); });
};
async function mount(surface?: string) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<ReferralProgramCard surface={surface} />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAccount = { id: 'personal_0', type: 'personal' };
  mockProfile = { id: 7, username: 'ana', referralCount: 0 };
  mockSummary = null;
  mockReferrals = [];
  jest.spyOn(Linking, 'canOpenURL').mockResolvedValue(true);
  jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined as never);
});

it('invites by WhatsApp with the person\'s own link, and says which screen the tap came from', async () => {
  const tree = await mount('invite');
  expect(texts(tree)).toEqual(expect.arrayContaining(['Tu red de confianza ahora te paga', 'Invitar por WhatsApp', '¿Cómo funciona?']));
  await pressText(tree, 'Invitar por WhatsApp');
  expect(Linking.openURL).toHaveBeenCalledWith(`whatsapp://send?text=${encodeURIComponent('Únete con @ana')}`);
  expect(mockLogFunnel).toHaveBeenCalledWith('referral_whatsapp_share_tapped',
    { surface: 'invite', referral_code: 'ana' }, { sourceType: 'referral_link', channel: 'whatsapp' });
  await act(async () => tree.unmount());
});

it('its rows open what they name', async () => {
  mockSummary = { friendCount: 2, viewerVerified: false };
  mockProfile = { id: 7, username: 'user_8f3k2', referralCount: 0 };
  const tree = await mount();
  expect(texts(tree).join(' ')).toContain('Ya tienes 2 invitados.');
  await pressText(tree, 'Verifica tu identidad para empezar a ganar');
  expect(mockNavigate).toHaveBeenLastCalledWith('Verification');
  // An auto-generated handle makes a poor code: offer to change it.
  await pressText(tree, 'Personalizar mi código');
  expect(mockNavigate).toHaveBeenLastCalledWith('UpdateUsername');
  await pressText(tree, '¿Te invitó alguien? Pon su código');
  expect(mockNavigate).toHaveBeenLastCalledWith('Achievements');
  tree.root.findByType('CommissionsEntryRow' as any).props.onPress();
  expect(mockNavigate).toHaveBeenLastCalledWith('FeeReferralCommissions');
  await act(async () => tree.unmount());
});

it('someone already invited is not asked for a code; earned bonuses keep their row', async () => {
  mockReferrals = [
    { referrerUser: { id: 3 }, referredUser: { id: 7 }, refereeRewardStatus: 'ELIGIBLE', rewardRefereeConfio: '5.00' },
  ];
  const tree = await mount();
  expect(texts(tree)).not.toContain('¿Te invitó alguien? Pon su código');
  expect(texts(tree)).not.toContain('Personalizar mi código');
  await act(async () => tree.unmount());
});

it('a business has no invitations of its own', async () => {
  mockAccount = { id: 'business_1_0', type: 'business' };
  const tree = await mount();
  expect(texts(tree)).toEqual([]);
  await act(async () => tree.unmount());
});
