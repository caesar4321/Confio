const mockSave = jest.fn(async () => 'ph://1');
const mockRequest = jest.fn(async () => 'denied');
jest.mock('@react-native-camera-roll/camera-roll', () => ({ CameraRoll: { save: (...a: any[]) => (mockSave as any)(...a) } }));
jest.mock('react-native', () => ({
  Platform: { OS: 'android', Version: 28 },
  PermissionsAndroid: {
    PERMISSIONS: { WRITE_EXTERNAL_STORAGE: 'android.permission.WRITE_EXTERNAL_STORAGE' },
    RESULTS: { GRANTED: 'granted' },
    request: (...a: any[]) => (mockRequest as any)(...a),
  },
}));

import { Platform } from 'react-native';
import { saveImageToGallery } from '../saveImageToGallery';

describe('saveImageToGallery', () => {
  beforeEach(() => { mockSave.mockClear(); mockRequest.mockClear(); });

  it('asks for storage on Android 9 and refuses without it', async () => {
    await expect(saveImageToGallery('file:///a.png')).rejects.toThrow();
    expect(mockSave).not.toHaveBeenCalled();
    mockRequest.mockResolvedValueOnce('granted');
    await saveImageToGallery('file:///a.png');
    expect(mockSave).toHaveBeenCalledWith('file:///a.png', { type: 'photo' });
  });

  it('asks nothing on Android 10+', async () => {
    (Platform as any).Version = 29;
    await saveImageToGallery('file:///b.png');
    expect(mockRequest).not.toHaveBeenCalled();
    expect(mockSave).toHaveBeenCalledTimes(1);
  });
});
