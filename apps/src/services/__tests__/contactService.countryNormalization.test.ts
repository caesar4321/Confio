/// <reference types="jest" />

const mockGetAll = jest.fn();
const mockGetInternetCredentials = jest.fn().mockResolvedValue(false);
const mockSetInternetCredentials = jest.fn().mockResolvedValue(true);

jest.mock('react-native-contacts', () => ({
  getAll: (...args: any[]) => mockGetAll(...args),
  checkPermission: jest.fn().mockResolvedValue('authorized'),
}));

jest.mock('react-native-keychain', () => ({
  getInternetCredentials: (...args: any[]) => mockGetInternetCredentials(...args),
  setInternetCredentials: (...args: any[]) => mockSetInternetCredentials(...args),
}));

// The old discovery path loaded this module lazily to query the server. Record
// any load so the test can prove the sync never reaches for it again.
const mockDiscoveryQueriesLoaded = jest.fn();
jest.mock('../../apollo/queries', () => {
  mockDiscoveryQueriesLoaded();
  return { CHECK_USERS_BY_PHONES: {} };
});

jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
  PermissionsAndroid: {
    PERMISSIONS: { READ_CONTACTS: 'android.permission.READ_CONTACTS' },
    RESULTS: { GRANTED: 'granted' },
    check: jest.fn().mockResolvedValue(true),
    request: jest.fn().mockResolvedValue('granted'),
  },
}));

import { contactService, hasDefaultPhoneRegion, setDefaultPhoneRegion } from '../contactService';

describe('contact country normalization', () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeAll(() => {
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterAll(() => {
    consoleErrorSpy.mockRestore();
  });

  beforeEach(async () => {
    jest.clearAllMocks();
    mockGetInternetCredentials.mockResolvedValue(false);
    mockSetInternetCredentials.mockResolvedValue(true);
    setDefaultPhoneRegion(null);
    await contactService.setContactOwner(null);
    await contactService.setContactOwner('sender-1', 'CO');
  });

  it('does not guess a country before the verified user region is available', async () => {
    await expect(contactService.syncContacts()).resolves.toBe(false);
    expect(mockGetAll).not.toHaveBeenCalled();
    expect(mockSetInternetCredentials).not.toHaveBeenCalled();
  });

  it('rejects an unsupported two-letter region instead of accepting it as a country', async () => {
    setDefaultPhoneRegion('XX');

    expect(hasDefaultPhoneRegion()).toBe(false);
    await expect(contactService.syncContacts()).resolves.toBe(false);
    expect(mockGetAll).not.toHaveBeenCalled();
  });

  it('abandons a sync if the signed-in country changes while contacts are loading', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockImplementation(async () => {
      setDefaultPhoneRegion('VE');
      return [];
    });

    await expect(contactService.syncContacts()).resolves.toBe(false);
    expect(mockSetInternetCredentials).not.toHaveBeenCalled();
  });

  it('uses the user country for national numbers and preserves explicit international numbers', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([
      {
        recordID: 'local',
        givenName: 'Local',
        familyName: 'Contact',
        phoneNumbers: [{ number: '313 258 7634' }],
        hasThumbnail: false,
      },
      {
        recordID: 'international',
        givenName: 'Foreign',
        familyName: 'Contact',
        phoneNumbers: [{ number: '+58 412 123 4567' }],
        hasThumbnail: false,
      },
    ]);

    await expect(contactService.syncContacts()).resolves.toBe(true);

    const stored = await contactService.getAllContacts();
    const local = stored.find(contact => contact.id === 'local');
    const international = stored.find(contact => contact.id === 'international');
    expect(local?.normalizedPhones).toContain('+573132587634');
    expect(local?.inferredE164Phones).toEqual(['+573132587634']);
    expect(international?.normalizedPhones).toContain('+584121234567');
    expect(international?.inferredE164Phones).toEqual([]);
  });

  it('does not store a countryless number that parses into a different calling plan as a full number', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'ambiguous-idd',
      givenName: 'Prefijo',
      familyName: 'Ambiguo',
      phoneNumbers: [{ number: '0058 412 123 4567' }],
      hasThumbnail: false,
    }]);

    await expect(contactService.syncContacts()).resolves.toBe(true);

    const stored = await contactService.getAllContacts();
    expect(stored).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'ambiguous-idd',
        isOnConfio: false,
      }),
    ]));
    expect(stored[0].normalizedPhones).not.toContain('+84121234567');
    expect(stored[0].normalizedPhones.some(phone => phone.startsWith('+'))).toBe(false);
    expect(stored[0].inferredE164Phones).toEqual([]);
  });

  it('does not expose cached recipient mappings after the authenticated user changes', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'private-contact',
      givenName: 'Privado',
      familyName: '',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);

    await expect(contactService.syncContacts()).resolves.toBe(true);
    await expect(contactService.getAllContacts()).resolves.toHaveLength(1);
    expect(mockSetInternetCredentials).toHaveBeenCalledWith(
      'com.confio.contacts.sender-1.CO',
      'user_contacts',
      expect.any(String),
    );

    await contactService.setContactOwner(null);
    await contactService.setContactOwner('sender-2', 'CO');

    await expect(contactService.getAllContacts()).resolves.toEqual([]);
  });

  it('does not reuse cached mappings after the verified phone country changes', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'country-bound',
      givenName: 'Cambio',
      familyName: 'País',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);

    await expect(contactService.syncContacts()).resolves.toBe(true);
    await expect(contactService.getAllContacts()).resolves.toHaveLength(1);

    setDefaultPhoneRegion('VE');
    await contactService.setContactOwner('sender-1', 'VE');

    await expect(contactService.getAllContacts()).resolves.toEqual([]);
    expect(mockGetInternetCredentials).toHaveBeenCalledWith('com.confio.contacts.sender-1.VE_array');
  });

  it('abandons a sync before storage if the authenticated user changes while contacts are loading', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockImplementation(async () => {
      await contactService.setContactOwner('sender-2', 'CO');
      return [{
        recordID: 'local',
        givenName: 'Local',
        familyName: '',
        phoneNumbers: [{ number: '313 258 7634' }],
        hasThumbnail: false,
      }];
    });
    mockSetInternetCredentials.mockClear();

    await expect(contactService.syncContacts()).resolves.toBe(false);
    expect(mockSetInternetCredentials).not.toHaveBeenCalled();
  });

  it('does not let an older secure-cache preload overwrite a newer sync', async () => {
    setDefaultPhoneRegion('CO');
    await contactService.setContactOwner(null);
    let resolvePreload: ((value: any) => void) | undefined;
    mockGetInternetCredentials.mockImplementation((service: string) => {
      if (service === 'com.confio.contacts.sender-1.CO_array') {
        return new Promise(resolve => { resolvePreload = resolve; });
      }
      return Promise.resolve(false);
    });

    const ownerBinding = contactService.setContactOwner('sender-1', 'CO');
    await Promise.resolve();
    mockGetAll.mockResolvedValue([{
      recordID: 'fresh',
      givenName: 'Nuevo',
      familyName: '',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);

    await expect(contactService.syncContacts()).resolves.toBe(true);
    resolvePreload?.({
      username: 'user_contacts',
      password: JSON.stringify([{
        id: 'stale',
        name: 'Viejo',
        phoneNumbers: ['300 000 0000'],
        normalizedPhones: ['+573000000000'],
        lastSynced: '2020-01-01T00:00:00.000Z',
      }]),
    });
    await ownerBinding;

    const stored = await contactService.getAllContacts();
    expect(stored.map(contact => contact.id)).toEqual(['fresh']);
  });

  it('keeps contacts on the phone: nothing is sent to Confío and no one is marked as a user', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([
      {
        recordID: 'local',
        givenName: 'Local',
        familyName: '',
        phoneNumbers: [{ number: '313 258 7634' }],
        hasThumbnail: false,
      },
      {
        recordID: 'international',
        givenName: 'Extranjero',
        familyName: '',
        phoneNumbers: [{ number: '+58 412 123 4567' }],
        hasThumbnail: false,
      },
    ]);
    const originalFetch = (globalThis as any).fetch;
    const fetchSpy = jest.fn();
    (globalThis as any).fetch = fetchSpy;

    try {
      await expect(contactService.syncContacts()).resolves.toBe(true);
    } finally {
      (globalThis as any).fetch = originalFetch;
    }

    expect(mockDiscoveryQueriesLoaded).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    const stored = await contactService.getAllContacts();
    expect(stored).toHaveLength(2);
    stored.forEach(contact => {
      expect(contact.isOnConfio).toBe(false);
      expect(contact.confioUserId).toBeUndefined();
      expect(contact.confioMatchedPhone).toBeUndefined();
    });
    // The only writes are this owner's on-device secure cache.
    mockSetInternetCredentials.mock.calls.forEach(([service]) => {
      expect(service).toMatch(/^com\.confio\.contacts\.sender-1\.CO(_array)?$/);
    });
  });

  it('replaces a previous cache when the device address book becomes empty', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'deleted-later',
      givenName: 'Temporal',
      familyName: '',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);
    await expect(contactService.syncContacts()).resolves.toBe(true);
    await expect(contactService.getAllContacts()).resolves.toHaveLength(1);

    mockGetAll.mockResolvedValue([]);
    await expect(contactService.syncContacts()).resolves.toBe(true);

    await expect(contactService.getAllContacts()).resolves.toEqual([]);
    expect(mockSetInternetCredentials).toHaveBeenCalledWith(
      'com.confio.contacts.sender-1.CO_array',
      'user_contacts',
      '[]',
    );
  });
});
