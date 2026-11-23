// "El fundador": who is behind Confío, his channel in the app, where to follow him.
import React from 'react';
import { Linking, Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockOpen = jest.fn();
const mockLogHomeNav = jest.fn();
let mockAssistant: any;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ goBack: jest.fn() }) }));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../assets/svg/WhatsApp.svg', () => 'WhatsAppLogo');
jest.mock('../../assistant/AssistantContext', () => ({ useOptionalAssistant: () => mockAssistant }));
jest.mock('../../services/homeNavAnalytics', () => ({ logHomeNav: (...a: unknown[]) => mockLogHomeNav(...a) }));

import FounderScreen, { FOUNDER_CHANNELS } from '../FounderScreen';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
  if (!node) throw new Error(`no button ${label}`);
  await act(async () => { node.props.onPress(); });
};
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<FounderScreen />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAssistant = { open: mockOpen };
  jest.spyOn(Linking, 'openURL').mockResolvedValue(true as any);
});

it('says who he is and opens his own channel inside the app', async () => {
  const tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining(
    ['Julian Moon', '@julianmoonluna · fundador de Confío', 'Un coreano que sueña con una nueva Latinoamérica']));
  await press(tree, 'Mensajes de Julian');
  expect(mockOpen).toHaveBeenCalledWith({ channel: 'julian' });
  expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'founder_messages');
  await act(async () => tree.unmount());
});

it('each channel is a row that opens it, and which one is counted', async () => {
  const tree = await mount();
  expect(FOUNDER_CHANNELS.map((c) => c.key)).toEqual(['tiktok', 'instagram', 'youtube', 'facebook', 'whatsapp']);
  for (const channel of FOUNDER_CHANNELS) {
    await press(tree, `${channel.name} de Julian Moon`);
    expect(Linking.openURL).toHaveBeenLastCalledWith(channel.url);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', `founder_${channel.key}`);
    // The server keeps only short slugs.
    expect(`founder_${channel.key}`).toMatch(/^[a-z][a-z0-9_]{0,23}$/);
  }
  await act(async () => tree.unmount());
});

it('with no chat to open (signed out of it), the channels are still there', async () => {
  mockAssistant = null;
  const tree = await mount();
  expect(texts(tree)).not.toContain('Mensajes de Julian');
  expect(texts(tree)).toContain('TikTok');
  await act(async () => tree.unmount());
});
