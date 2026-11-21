import { resetMocks } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import { Alert } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import { flush, ok, tap, text } from '../../components/smartAccount/testing/fixtures';
import { SmartAccountWatchesScreen, watchSubtitle } from '../SmartAccountWatchesScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const watch = {
  watchId: 'w1', text: 'Te aviso si TSLA baja 5% desde hoy.', hasAction: false, lastTriggeredAt: null,
  createdAt: '2026-11-21T10:00:00Z',
};

beforeEach(() => {
  resetMocks();
  api.fetchSmartAccountWatches.mockResolvedValue(ok([watch]));
  api.deleteSmartAccountWatch.mockResolvedValue({ success: true, errorCode: null, errorMessage: null });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('lists the alerts the owner set and deletes one after confirming', async () => {
  const alert = jest.spyOn(Alert, 'alert');
  await act(async () => { tree = renderer.create(<SmartAccountWatchesScreen />); });
  await flush();
  expect(text(tree)).toContain('Te aviso si TSLA baja 5% desde hoy.');
  await tap(tree, 'watch-w1');
  const buttons = alert.mock.calls[0][2] as any[];
  await act(async () => { await buttons.find((b) => b.text === 'Borrar').onPress(); });
  expect(api.deleteSmartAccountWatch).toHaveBeenCalledWith('w1');
});

it('has an empty state that never suggests a level or an asset', async () => {
  api.fetchSmartAccountWatches.mockResolvedValue(ok([]));
  await act(async () => { tree = renderer.create(<SmartAccountWatchesScreen />); });
  await flush();
  expect(text(tree)).toContain('Aún no tienes alertas');
  expect(text(tree)).toContain('al nivel que tú elijas');
  expect(watchSubtitle({ ...watch, lastTriggeredAt: '2026-11-20T10:00:00Z' })).toMatch(/^Último aviso: /);
});
