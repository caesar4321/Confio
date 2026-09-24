import React from 'react';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {FlatList, Text, TouchableOpacity} from 'react-native';
import PhoneVerificationScreen from '../PhoneVerificationScreen';
import {getCountryByIso} from '../../utils/countries';

let mockProfile: any;
const mockGoBack = jest.fn();
jest.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({userProfile: mockProfile, isAuthenticated: !!mockProfile}),
}));
jest.mock('@apollo/client', () => ({useMutation: () => [jest.fn(), {loading: false}]}));
jest.mock('../../apollo/queries', () => ({}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({goBack: mockGoBack})}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../assets/svg/TelegramLogo.svg', () => 'TelegramLogo');
jest.mock('react-native-safe-area-context', () => ({SafeAreaView: require('react-native').View}));
jest.mock('../../components/PhoneRelinkModal', () => ({PhoneRelinkModal: () => null}));

describe('phone country draft', () => {
  let tree: ReactTestRenderer;
  const text = () => tree.root.findAllByType(Text).map(node => node.props.children).flat().join(' ');
  afterEach(async () => { await act(async () => tree?.unmount()); });

  it('shows an explicit Argentina default for a new signup', async () => {
    mockProfile = undefined;
    await act(async () => { tree = create(<PhoneVerificationScreen />); });
    expect(text()).toContain('Argentina');
    expect(text()).toContain('+54');
    expect(text()).not.toContain('Seleccionar país');
  });

  it('discards a changed country when the phone edit is reopened', async () => {
    mockProfile = {id: 'luis', phoneCountry: 'MX'};
    const mount = async () => { await act(async () => { tree = create(<PhoneVerificationScreen />); }); };
    await mount();
    expect(text()).toContain('México');
    const picker = tree.root.findAllByType(TouchableOpacity).find(node => node.props.activeOpacity === 0.8)!;
    await act(async () => picker.props.onPress());
    const list = tree.root.findByType(FlatList);
    const row = list.props.renderItem({item: getCountryByIso('AR')});
    await act(async () => row.props.onPress());
    expect(text()).toContain('Argentina');
    await act(async () => tree.unmount());
    await mount();
    expect(text()).toContain('México');
    expect(text()).toContain('+52');
  });
});
