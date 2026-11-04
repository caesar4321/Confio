const mockSingle = jest.fn((..._a: any[]) => Promise.resolve({}));
const mockOpen = jest.fn((..._a: any[]) => Promise.resolve({}));
const mockSave = jest.fn((..._a: any[]) => Promise.resolve('ph://ABC-123'));
jest.mock('react-native-share', () => ({
  __esModule: true,
  default: { shareSingle: (...a: any[]) => mockSingle(...a), open: (...a: any[]) => mockOpen(...a) },
  Social: { Whatsapp: 'whatsapp', Instagram: 'instagram' },
}));
jest.mock('@react-native-camera-roll/camera-roll', () => ({ CameraRoll: { save: (...a: any[]) => mockSave(...a) } }));

const setOS = (os: string) => { require('react-native').Platform.OS = os; };

import { shareImageToApp } from '../shareToApp';

beforeEach(() => { mockSingle.mockClear(); mockOpen.mockClear(); mockSave.mockClear(); });

describe('shareImageToApp', () => {
  it('Android: WhatsApp gets the image and the text directly', async () => {
    setOS('android');
    await shareImageToApp('whatsapp', 'file:///c.png', 'hola https://confio.lat/invite/ANA', 'Confio_TSLA');
    expect(mockSingle).toHaveBeenCalledWith(expect.objectContaining({ social: 'whatsapp', url: 'file:///c.png',
      message: 'hola https://confio.lat/invite/ANA' }));
    expect(mockOpen).not.toHaveBeenCalled();
  });

  it('Android: a failed direct route falls back to the share sheet', async () => {
    setOS('android');
    mockSingle.mockRejectedValueOnce(new Error('not installed'));
    await shareImageToApp('instagram', 'file:///c.png', 'm', 'f');
    expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ url: 'file:///c.png', message: 'm' }));
  });

  it('iOS: WhatsApp goes through the share sheet so the link travels with the image', async () => {
    setOS('ios');
    await shareImageToApp('whatsapp', 'file:///c.png', 'm https://confio.lat/invite/ANA', 'f');
    expect(mockSingle).not.toHaveBeenCalled();
    expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ url: 'file:///c.png', message: 'm https://confio.lat/invite/ANA' }));
  });

  it('iOS: Instagram receives a Photos asset id, not a file', async () => {
    setOS('ios');
    await shareImageToApp('instagram', 'file:///c.png', 'm', 'f');
    expect(mockSave).toHaveBeenCalledWith('file:///c.png', { type: 'photo' });
    expect(mockSingle).toHaveBeenCalledWith(expect.objectContaining({ social: 'instagram', url: 'ph://ABC-123' }));
  });

  it('iOS: Instagram not installed does not also open the sheet', async () => {
    setOS('ios');
    mockSingle.mockRejectedValueOnce(new Error('Not installed'));
    await shareImageToApp('instagram', 'file:///c.png', 'm', 'f');
    expect(mockOpen).not.toHaveBeenCalled();
  });

  it('iOS: Photos access denied still opens the share sheet', async () => {
    setOS('ios');
    mockSave.mockRejectedValueOnce(new Error('Access to photo library was denied'));
    await shareImageToApp('instagram', 'file:///c.png', 'm', 'f');
    expect(mockSingle).not.toHaveBeenCalled();
    expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ url: 'file:///c.png' }));
  });
});
