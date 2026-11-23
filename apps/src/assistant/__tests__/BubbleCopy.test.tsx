import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Bubble } from '../AssistantSheet';
import type { AssistantMessage } from '../api';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('../../components/common/AppText', () => ({
  Text: require('react-native').Text, TextInput: require('react-native').TextInput,
}));
jest.mock('../../agentTasks/TaskChips', () => ({ TaskChips: () => null }));
jest.mock('../../apollo/mutations', () => ({ MARK_MESSAGE_CHANNEL_SEEN: 'markSeen' }));
jest.mock('../../apollo/queries', () => ({}));
jest.mock('../../components/DirectInboxContent', () => ({ DirectInboxContent: 'DirectInboxContent' }));
jest.mock('../../components/MessageInboxContent', () => ({ MessageInboxContent: 'MessageInboxContent' }));
jest.mock('../../components/MessageInboxShared', () => ({ ChannelAvatar: 'ChannelAvatar' }));
jest.mock('../../components/smartAccount/useSmartRead', () => ({ useSmartRead: () => ({ data: undefined, failed: false }) }));
jest.mock('../../components/svg/CuentaInteligenteMark', () => 'CuentaInteligenteMark');
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: null }) }));
jest.mock('../../navigation/RootNavigation', () => ({ navigationRef: { isReady: () => false, navigate: jest.fn() } }));
jest.mock('../../services/paidOffers', () => ({ logDoorShown: jest.fn() }));
jest.mock('../../services/smartAccount', () => ({}));
jest.mock('../AssistantContext', () => ({ useAssistant: () => ({}) }));
jest.mock('../AssistantMascot', () => 'AssistantMascot');
jest.mock('../AssistantPlusPanel', () => 'AssistantPlusPanel');
jest.mock('../MascotPicker', () => 'MascotPicker');
jest.mock('../SmartContextNotice', () => ({}));
jest.mock('../VoiceCallPanel', () => 'VoiceCallPanel');
jest.mock('../callStore', () => ({}));
jest.mock('../connections/ConnectionsHost', () => 'ConnectionsHost');
jest.mock('../connections/ConnectionsPrompt', () => 'ConnectionsPrompt');
jest.mock('../voiceNote', () => ({}));
jest.mock('@apollo/client', () => ({
  gql: () => 'query', useApolloClient: jest.fn(), useMutation: () => [jest.fn()], useQuery: () => ({}),
}));

const message = (role: AssistantMessage['role'], body: string): AssistantMessage => ({
  id: `${role}-1`, role, body, createdAt: '2026-11-23T00:00:00Z', senderName: 'Equipo Confío', actions: [],
});

const texts = (tree: renderer.ReactTestRenderer) => tree.root.findAll((n) => typeof n.props?.children === 'string')
  .map((n) => n.props.children as string);

describe('a chat bubble', () => {
  for (const role of ['user', 'assistant', 'team'] as const) {
    it(`copies the whole ${role} message on a long press and says so`, async () => {
      const Clipboard = require('@react-native-clipboard/clipboard');
      Clipboard.setString.mockClear();
      let tree!: renderer.ReactTestRenderer;
      await act(async () => {
        tree = renderer.create(<Bubble message={message(role, 'Desde Recibir: elige tu banco.')} onAction={() => {}}
          onWalk={() => {}} pet={null as any} />);
      });
      const bubble = tree.root.findAll((n) => typeof n.props?.onLongPress === 'function')[0];
      jest.useFakeTimers();
      try {
        await act(async () => { bubble.props.onLongPress(); });
        expect(Clipboard.setString).toHaveBeenCalledWith('Desde Recibir: elige tu banco.');
        expect(texts(tree)).toContain('Copiado');
        await act(async () => { jest.advanceTimersByTime(1600); });
        expect(texts(tree)).not.toContain('Copiado');
      } finally {
        jest.useRealTimers();
      }
      await act(async () => tree.unmount());
    });
  }
});
