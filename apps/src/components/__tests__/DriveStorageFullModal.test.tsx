/**
 * Full Google storage is the one Drive backup failure only the user can fix,
 * so the prompt must say how to free space, open Google's storage manager,
 * and hand retry/dismiss back to the caller.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, Linking, ScrollView } from 'react-native';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('react-native-vector-icons/MaterialCommunityIcons', () => 'Icon');

import { DriveStorageFullModal, GOOGLE_STORAGE_MANAGER_URL } from '../DriveStorageFullModal';

const render = (props: Partial<React.ComponentProps<typeof DriveStorageFullModal>> = {}) => {
  const onRetry = jest.fn();
  const onClose = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <DriveStorageFullModal visible onRetry={onRetry} onClose={onClose} {...props} />,
    );
  });
  return { tree, onRetry, onClose };
};

const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const [button] = tree.root.findAll(
    node => node.props.accessibilityLabel === label && typeof node.props.onPress === 'function',
  );
  expect(button).toBeDefined();
  await act(async () => {
    await button.props.onPress();
  });
};

describe('DriveStorageFullModal', () => {
  afterEach(() => jest.restoreAllMocks());

  it('explains that Google storage is shared and how to free space', () => {
    const { tree } = render();
    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain('Tu almacenamiento de Google está lleno');
    expect(text).toContain('respaldos de WhatsApp');
    expect(text).toContain('Vacía la papelera y el spam');
  });

  it('opens Google storage manager', async () => {
    const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
    const { tree } = render();
    await press(tree, 'Liberar espacio en Google');
    expect(openURL).toHaveBeenCalledWith(GOOGLE_STORAGE_MANAGER_URL);
  });

  it('falls back to written instructions when the link cannot open', async () => {
    jest.spyOn(Linking, 'openURL').mockRejectedValue(new Error('no handler'));
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    const { tree } = render();
    await press(tree, 'Liberar espacio en Google');
    expect(alert).toHaveBeenCalledWith(
      'No pudimos abrir Google',
      expect.stringContaining('one.google.com/storage/management'),
    );
  });

  it('hands retry and dismiss back to the caller', async () => {
    const { tree, onRetry, onClose } = render();
    await press(tree, 'Ya liberé espacio, reintentar');
    expect(onRetry).toHaveBeenCalledTimes(1);
    await press(tree, 'Cerrar');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('moves the footer into the scrolling content when the window is too short', () => {
    const { tree } = render();
    const scrolledButtons = () => tree.root.findByType(ScrollView).findAll(
      node => node.props.accessibilityLabel === 'Cerrar' && typeof node.props.onPress === 'function',
    );
    expect(scrolledButtons()).toHaveLength(0);
    const [footer] = tree.root.findAll(node => node.props.testID === 'drive-storage-full-footer');
    act(() => footer.props.onLayout({ nativeEvent: { layout: { height: 100000 } } }));
    expect(scrolledButtons().length).toBeGreaterThan(0);
  });

  it('renders nothing while hidden', () => {
    const { tree } = render({ visible: false });
    expect(JSON.stringify(tree.toJSON())).not.toContain('Tu almacenamiento de Google está lleno');
  });
});
