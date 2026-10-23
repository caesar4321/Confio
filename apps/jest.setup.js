// Jest setup — back the native CSPRNG with Node's CSPRNG.
//
// src/setup/entropyGuard.ts deliberately has NO runtime environment exemption:
// a guard that can be switched off by a mutable global is not a guard. The
// test-only substitution lives here instead, in jest configuration, where a
// shipped build cannot reach it.
//
// This mirrors the real native contract: RNGetRandomValues.getRandomBase64(n)
// returns n cryptographically random bytes as a base64 string, synchronously.
const { randomBytes } = require('crypto');
const { NativeModules } = require('react-native');

NativeModules.RNGetRandomValues = {
  getRandomBase64: (byteLength) => randomBytes(byteLength).toString('base64'),
};

// @react-native-clipboard/clipboard is a TurboModule: without its mock, any
// screen that imports it (LocalSendScreen's "Pegar") fails to load in Jest.
jest.mock('@react-native-clipboard/clipboard', () =>
  require('@react-native-clipboard/clipboard/jest/clipboard-mock.js'));

// react-native-maps renders native views Jest doesn't have (Comprar's
// delivery pin): plain host components keep the screens testable.
jest.mock('react-native-maps', () => {
  const React = require('react');
  const { View } = require('react-native');
  const MapView = React.forwardRef((props, ref) => {
    React.useImperativeHandle(ref, () => ({ animateToRegion: jest.fn() }));
    return React.createElement(View, { ...props, testID: props.testID || 'map-view' }, props.children);
  });
  const Marker = (props) => React.createElement(View, props);
  return { __esModule: true, default: MapView, Marker };
});

// Native GPS: screens that can ask for a delivery pin load without it.
jest.mock('@react-native-community/geolocation', () => ({
  __esModule: true,
  default: { getCurrentPosition: jest.fn(), requestAuthorization: jest.fn(), watchPosition: jest.fn(), clearWatch: jest.fn() },
}));
