import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ goBack: jest.fn() }),
  useRoute: () => ({ params: {} }),
}));
const mockSave = jest.fn();
jest.mock('@apollo/client', () => {
  const store = { data: { myMarketStore: { countryCode: 'BO' }, myMarketStoreProducts: [], marketplaceCategories: [], marketplaceFeeBps: 800 } };
  return {
    gql: () => ({}),
    useQuery: (q: any, opts: any) => (opts?.variables?.countryCode !== undefined ? { data: undefined } : store),
    useMutation: () => [mockSave, { loading: false }],
  };
});
const mockPick = jest.fn();
jest.mock('../../services/systemPicker', () => ({ pickFromLibrary: (o: any) => mockPick(o) }));
const mockUpload = jest.fn();
jest.mock('../../services/comprar', () => {
  const actual = jest.requireActual('../../services/comprar');
  return { ...actual, uploadMarketPhoto: (...a: any[]) => mockUpload(...a) };
});
jest.mock('react-native-image-picker', () => ({ launchImageLibrary: jest.fn() }));

import { MarketProductEditScreen } from '../MarketProductEditScreen';

const render = () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MarketProductEditScreen />); });
  return tree;
};
const byTestId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((n) => n.props.testID === id && typeof n.props.onPress === 'function')[0];
const addButton = (tree: renderer.ReactTestRenderer) => byTestId(tree, 'product-add-photo');
const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => { mockPick.mockReset(); mockUpload.mockReset(); mockSave.mockReset(); });

it('picks through the resume-lock guard, resized under the upload cap', async () => {
  mockPick.mockResolvedValue({ assets: [] });
  const tree = render();
  await act(async () => { addButton(tree).props.onPress(); });
  expect(mockPick).toHaveBeenCalledWith(expect.objectContaining({ maxWidth: 1600, maxHeight: 1600 }));
  const { launchImageLibrary } = require('react-native-image-picker');
  expect(launchImageLibrary).not.toHaveBeenCalled();
});

it('shows an upload failure next to the photos', async () => {
  mockPick.mockResolvedValue({ assets: [{ uri: 'file:///a.jpg', type: 'image/jpeg' }] });
  mockUpload.mockRejectedValue(new Error('upload_too_large'));
  const tree = render();
  await act(async () => { addButton(tree).props.onPress(); });
  expect(text(tree)).toContain('La foto es muy pesada');
});

it('says so when the photo library cannot open', async () => {
  mockPick.mockResolvedValue({ errorCode: 'permission' });
  const tree = render();
  await act(async () => { addButton(tree).props.onPress(); });
  expect(text(tree)).toContain('Permite el acceso a tus fotos');
});

it('shows a save that throws instead of swallowing it', async () => {
  mockSave.mockRejectedValue(Object.assign(new Error('Network request failed'), { networkError: {} }));
  const tree = render();
  const submit = byTestId(tree, 'product-submit');
  await act(async () => { submit.props.onPress(); });
  expect(text(tree)).toContain('Sin conexión');
});

it('labels picker JPEGs the way the upload allowlist spells them', () => {
  const { normalizeImageType } = jest.requireActual('../../services/comprar');
  expect(normalizeImageType('image/jpg')).toBe('image/jpeg');   // iOS picker
  expect(normalizeImageType('image/heic')).toBe('image/jpeg');  // Android, re-encoded on resize
  expect(normalizeImageType('image/png')).toBe('image/png');
  expect(normalizeImageType('image/webp')).toBe('image/webp');
});
