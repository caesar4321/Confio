import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { TouchableOpacity } from 'react-native';

const mockQuery = jest.fn();
const mockRefresh = jest.fn();
const mockLogin = jest.fn();
const mockBackup = jest.fn();
const mockClient = { query: mockQuery };
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'), useApolloClient: () => mockClient,
}));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({
  refreshProfile: mockRefresh, handleSuccessfulLogin: mockLogin, signOut: jest.fn(),
}) }));
jest.mock('../../services/authService', () => ({ __esModule: true, default: {
  enableDriveBackup: (...args: any[]) => mockBackup(...args),
} }));
jest.mock('../../components/DriveStorageFullModal', () => ({ DriveStorageFullModal: () => null }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-svg', () => ({ __esModule: true, default: 'Svg', Defs: 'Defs',
  LinearGradient: 'LinearGradient', Stop: 'Stop', Circle: 'Circle' }));

import BackupCompletionScreen from '../BackupCompletionScreen';

beforeEach(() => {
  jest.resetAllMocks();
  mockRefresh.mockResolvedValue(undefined);
  mockLogin.mockResolvedValue(undefined);
  mockBackup.mockResolvedValue({ success: true });
});

async function retry() {
  let tree: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BackupCompletionScreen />); });
  await act(async () => { await tree!.root.findAllByType(TouchableOpacity)[0].props.onPress(); });
  return tree!;
}

it('lets an already-blocked legacy user continue when the server no longer requires V2 backup', async () => {
  mockQuery.mockResolvedValue({ data: { me: { requiresBackupCompletion: false, phoneNumber: '123', phoneCountry: 'JP' } } });
  await retry();
  expect(mockBackup).not.toHaveBeenCalled();
  expect(mockLogin).toHaveBeenCalledWith(true, false);
});

it('still backs up V2 and rechecks server acknowledgement before continuing', async () => {
  mockQuery.mockResolvedValueOnce({ data: { me: { requiresBackupCompletion: true } } })
    .mockResolvedValueOnce({ data: { me: { requiresBackupCompletion: false } } });
  await retry();
  expect(mockBackup).toHaveBeenCalledTimes(1);
  expect(mockQuery).toHaveBeenCalledTimes(2);
  expect(mockLogin).toHaveBeenCalledWith(false, false);
});

it.each([null, {}, { requiresBackupCompletion: true }])('does not continue without explicit server clearance: %j', async me => {
  mockQuery.mockResolvedValue({ data: { me } });
  await retry();
  expect(mockLogin).not.toHaveBeenCalled();
});

it('does not continue or touch keys when the preflight query fails', async () => {
  mockQuery.mockRejectedValue(new Error('offline'));
  await retry();
  expect(mockBackup).not.toHaveBeenCalled();
  expect(mockLogin).not.toHaveBeenCalled();
});

it('does not continue if backup fails', async () => {
  mockQuery.mockResolvedValue({ data: { me: { requiresBackupCompletion: true } } });
  mockBackup.mockResolvedValue({ success: false, error: 'Drive unavailable' });
  await retry();
  expect(mockLogin).not.toHaveBeenCalled();
});

it.each([null, {}, { requiresBackupCompletion: true }])('requires server clearance after successful upload: %j', async me => {
  mockQuery.mockResolvedValueOnce({ data: { me: { requiresBackupCompletion: true } } })
    .mockResolvedValueOnce({ data: { me } });
  await retry();
  expect(mockBackup).toHaveBeenCalledTimes(1);
  expect(mockLogin).not.toHaveBeenCalled();
});
