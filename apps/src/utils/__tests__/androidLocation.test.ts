// Fresh react-native after each resetModules: the modules under test require it too.
const rn = () => require('react-native');
const setAndroid = () => Object.defineProperty(rn().Platform, 'OS', { get: () => 'android', configurable: true });
const native = () => rn().NativeModules as any;

describe('getPreciseFix on Android (native module)', () => {
  beforeEach(() => {
    jest.resetModules();
    setAndroid();
    const { PermissionsAndroid } = require('react-native');
    jest.spyOn(PermissionsAndroid, 'check').mockResolvedValue(true);
  });
  afterEach(() => { delete native().ConfioLocation; });

  it('asks the native module for a fresh, accurate GPS fix', async () => {
    const currentPosition = jest.fn().mockResolvedValue({
      latitude: -16.4764, longitude: -68.1104, accuracy: 12, ageMs: 900, provider: 'gps', mocked: false });
    native().ConfioLocation = { currentPosition };
    const { getPreciseFix } = require('../deliveryLocation');
    await expect(getPreciseFix()).resolves.toEqual({ pin: { latitude: -16.4764, longitude: -68.1104 } });
    expect(currentPosition).toHaveBeenCalledWith(expect.objectContaining({ precise: true, maxAccuracyM: 100 }));
  });

  it('tells "location is off" apart from a plain failure', async () => {
    native().ConfioLocation = {
      currentPosition: jest.fn().mockRejectedValue(Object.assign(new Error('off'), { code: 'LOCATION_DISABLED' })) };
    const { getPreciseFix } = require('../deliveryLocation');
    await expect(getPreciseFix()).resolves.toEqual({ error: 'disabled' });
  });

  it('maps a refused permission and a timeout', async () => {
    const { androidCurrentPosition } = require('../androidLocation');
    native().ConfioLocation = {
      currentPosition: jest.fn()
        .mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'LOCATION_PERMISSION' }))
        .mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'LOCATION_TIMEOUT' })) };
    const opts = { precise: false, maxAgeMs: 1, maxAccuracyM: 0, timeoutMs: 1 };
    await expect(androidCurrentPosition(opts)).resolves.toEqual({ error: 'denied' });
    await expect(androidCurrentPosition(opts)).resolves.toEqual({ error: 'unavailable' });
  });

  it('falls back to the geolocation library on builds without the module', () => {
    const { nativeLocationAvailable } = require('../androidLocation');
    expect(nativeLocationAvailable()).toBe(false);
  });
});
