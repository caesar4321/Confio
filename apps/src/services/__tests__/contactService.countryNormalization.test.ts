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
    const apolloClient = { query: jest.fn() };

    await expect(contactService.syncContacts(apolloClient)).resolves.toBe(false);
    expect(mockGetAll).not.toHaveBeenCalled();
    expect(apolloClient.query).not.toHaveBeenCalled();
  });

  it('rejects an unsupported two-letter region instead of accepting it as a country', async () => {
    setDefaultPhoneRegion('XX');

    expect(hasDefaultPhoneRegion()).toBe(false);
    await expect(contactService.syncContacts({ query: jest.fn() })).resolves.toBe(false);
    expect(mockGetAll).not.toHaveBeenCalled();
  });

  it('abandons a sync if the signed-in country changes while contacts are loading', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockImplementation(async () => {
      setDefaultPhoneRegion('VE');
      return [];
    });
    const query = jest.fn();

    await expect(contactService.syncContacts({ query })).resolves.toBe(false);
    expect(query).not.toHaveBeenCalled();
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
    const query = jest.fn().mockImplementation(({ variables }) => Promise.resolve({
      data: {
        checkUsersByPhones: variables.phoneNumbers.map((phoneNumber: string, index: number) => ({
          phoneNumber,
          userId: `user-${index}`,
          username: `user${index}`,
          firstName: index === 0 ? 'Cuenta local' : 'Cuenta extranjera',
          lastName: '',
          isOnConfio: true,
          activeAccountAlgorandAddress: `address-${index}`,
        })),
      },
    }));

    await expect(contactService.syncContacts({ query })).resolves.toBe(true);

    expect(query).toHaveBeenCalledWith(expect.objectContaining({
      variables: { phoneNumbers: ['+573132587634', '+584121234567'] },
    }));
    const stored = await contactService.getAllContacts();
    expect(stored.find(contact => contact.id === 'local')).toEqual(expect.objectContaining({
      confioMatchedPhone: '+573132587634',
      confioMatchWasInferred: true,
      confioFirstName: 'Cuenta local',
    }));
    expect(stored.find(contact => contact.id === 'international')).toEqual(expect.objectContaining({
      confioMatchedPhone: '+584121234567',
      confioMatchWasInferred: false,
      confioFirstName: 'Cuenta extranjera',
    }));
  });

  it('does not upload a countryless number that parses into a different calling plan', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'ambiguous-idd',
      givenName: 'Prefijo',
      familyName: 'Ambiguo',
      phoneNumbers: [{ number: '0058 412 123 4567' }],
      hasThumbnail: false,
    }]);
    const query = jest.fn();

    await expect(contactService.syncContacts({ query })).resolves.toBe(true);

    expect(query).not.toHaveBeenCalled();
    const stored = await contactService.getAllContacts();
    expect(stored).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'ambiguous-idd',
        isOnConfio: false,
      }),
    ]));
    expect(stored[0].normalizedPhones).not.toContain('+84121234567');
  });

  it('separates one device contact whose phone numbers belong to different Confío users', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'shared',
      givenName: 'Familia',
      familyName: 'Pérez',
      phoneNumbers: [{ number: '313 258 7634' }, { number: '+58 412 123 4567' }],
      hasThumbnail: false,
    }]);
    const query = jest.fn().mockImplementation(({ variables }) => Promise.resolve({
      data: {
        checkUsersByPhones: variables.phoneNumbers.map((phoneNumber: string, index: number) => ({
          phoneNumber,
          userId: `recipient-${index}`,
          username: `recipient${index}`,
          firstName: `Recipient ${index}`,
          lastName: '',
          isOnConfio: true,
        })),
      },
    }));

    await expect(contactService.syncContacts({ query })).resolves.toBe(true);

    const stored = await contactService.getAllContacts();
    expect(stored).toHaveLength(2);
    expect(stored.map(contact => contact.confioUserId).sort()).toEqual(['recipient-0', 'recipient-1']);
    expect(stored.map(contact => contact.confioMatchedPhone).sort()).toEqual([
      '+573132587634',
      '+584121234567',
    ]);
    expect(stored.every(contact => contact.normalizedPhones.includes(contact.confioMatchedPhone!))).toBe(true);
    expect(stored.find(contact => contact.confioMatchedPhone === '+573132587634')?.confioMatchWasInferred).toBe(true);
    expect(stored.find(contact => contact.confioMatchedPhone === '+584121234567')?.confioMatchWasInferred).toBe(false);
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

  it('abandons a sync before storage if the authenticated user changes during lookup', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'local',
      givenName: 'Local',
      familyName: '',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);
    const query = jest.fn().mockImplementation(async () => {
      await contactService.setContactOwner('sender-2', 'CO');
      return { data: { checkUsersByPhones: [] } };
    });
    mockSetInternetCredentials.mockClear();

    await expect(contactService.syncContacts({ query })).resolves.toBe(false);
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

  it('preserves the last good cache when server discovery fails', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([{
      recordID: 'known-good',
      givenName: 'Conocido',
      familyName: '',
      phoneNumbers: [{ number: '313 258 7634' }],
      hasThumbnail: false,
    }]);
    const successfulQuery = jest.fn().mockResolvedValue({
      data: {
        checkUsersByPhones: [{
          phoneNumber: '+573132587634',
          userId: 'recipient-1',
          username: 'recipient1',
          firstName: 'Recipient',
          lastName: 'One',
          isOnConfio: true,
        }],
      },
    });
    await expect(contactService.syncContacts({ query: successfulQuery })).resolves.toBe(true);

    mockGetAll.mockResolvedValue([{
      recordID: 'new-device-contact',
      givenName: 'Nuevo',
      familyName: '',
      phoneNumbers: [{ number: '300 111 2233' }],
      hasThumbnail: false,
    }]);
    await expect(contactService.syncContacts({
      query: jest.fn().mockRejectedValue(new Error('network unavailable')),
    })).resolves.toBe(false);

    const stored = await contactService.getAllContacts();
    expect(stored).toHaveLength(1);
    expect(stored[0]).toEqual(expect.objectContaining({
      id: 'known-good',
      confioUserId: 'recipient-1',
    }));
  });

  it('rejects an incomplete discovery response instead of treating omissions as non-users', async () => {
    setDefaultPhoneRegion('CO');
    mockGetAll.mockResolvedValue([
      {
        recordID: 'one',
        givenName: 'Uno',
        familyName: '',
        phoneNumbers: [{ number: '313 258 7634' }],
        hasThumbnail: false,
      },
      {
        recordID: 'two',
        givenName: 'Dos',
        familyName: '',
        phoneNumbers: [{ number: '300 111 2233' }],
        hasThumbnail: false,
      },
    ]);
    const query = jest.fn().mockResolvedValue({
      data: {
        checkUsersByPhones: [{
          phoneNumber: '+573132587634',
          userId: null,
          isOnConfio: false,
        }],
      },
    });

    await expect(contactService.syncContacts({ query })).resolves.toBe(false);
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
