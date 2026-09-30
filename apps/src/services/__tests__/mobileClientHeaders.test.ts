jest.mock('react-native', () => ({ Platform: { OS: 'android' } }));
jest.mock('react-native-device-info', () => ({
  getVersion: jest.fn(() => '5.1.5'),
  getBuildNumber: jest.fn(() => '157'),
}));

import { Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { mobileClientHeaders, createMobileWebSocket } from '../mobileClientHeaders';

describe('Face release compatibility headers', () => {
  it('sends the same compatibility headers on native WebSockets', () => {
    const original = globalThis.WebSocket;
    const constructor = jest.fn();
    globalThis.WebSocket = constructor as unknown as typeof WebSocket;
    try {
      createMobileWebSocket('wss://example.test/ws/send_session');
      expect(constructor).toHaveBeenCalledWith('wss://example.test/ws/send_session', undefined, {
        headers: mobileClientHeaders(),
      });
    } finally {
      globalThis.WebSocket = original;
    }
  });
  it('advertises the installed native version/build and capability', () => {
    expect(mobileClientHeaders()).toEqual({
      'X-Confio-Platform': 'android', 'X-Confio-Version': '5.1.5',
      'X-Confio-Build': '157', 'X-Confio-Face-Capable': '1',
    });
  });

  it('reads iOS build independently of Android and never asserts a passed face', () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    (DeviceInfo.getBuildNumber as jest.Mock).mockReturnValue('1');
    expect(mobileClientHeaders()).toEqual({
      'X-Confio-Platform': 'ios', 'X-Confio-Version': '5.1.5',
      'X-Confio-Build': '1', 'X-Confio-Face-Capable': '1',
    });
  });
});
