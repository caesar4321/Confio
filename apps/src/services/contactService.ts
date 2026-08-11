import Contacts from 'react-native-contacts';
import * as Keychain from 'react-native-keychain';
import { PermissionsAndroid, Platform } from 'react-native';
import {
  getCountryCallingCode,
  isSupportedCountry,
  parsePhoneNumber,
  type CountryCode,
} from 'libphonenumber-js';
import {
  hasUsableInternetCredentials,
  softClearInternetCredentials,
} from '../utils/keychainInternetCredentials';

interface StoredContact {
  id: string;
  name: string;
  phoneNumbers: string[]; // Primary field for phone numbers
  phones?: string[]; // Legacy field for backward compatibility
  normalizedPhones: string[];
  avatar?: string;
  lastSynced: string;
  isOnConfio?: boolean;
  confioUserId?: string;
  confioUsername?: string;
  confioFirstName?: string;
  confioLastName?: string;
  confioSuiAddress?: string;
  confioAlgorandAddress?: string;
  confioMatchedPhone?: string;
  confioMatchWasInferred?: boolean;
  inferredE164Phones?: string[];
  statusTier?: string | null;
  isReferralVerified?: boolean;
}

interface ContactMap {
  [phoneNumber: string]: StoredContact;
}

/**
 * Progress for a running sync. `total` is 0 while a step cannot be measured
 * (the native address-book read is a single opaque call), which the UI renders
 * as an indeterminate bar instead of a fake percentage.
 */
export type ContactSyncPhase = 'reading' | 'normalizing' | 'matching' | 'saving';

export interface ContactSyncProgress {
  phase: ContactSyncPhase;
  processed: number;
  total: number;
}

export type ContactSyncProgressListener = (progress: ContactSyncProgress) => void;

// A tight loop over thousands of contacts freezes the JS thread, which is what
// makes a big address book feel hung. Yield every chunk so progress can paint.
const NORMALIZE_CHUNK_SIZE = 150;
const yieldToUiThread = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 0));

const CONTACTS_KEYCHAIN_SERVICE = 'com.confio.contacts';
const CONTACTS_KEYCHAIN_KEY = 'user_contacts';
const CONTACT_PERMISSION_STATUS_KEY = 'contact_permission_status';
const contactsServiceForOwner = (
  ownerUserId: string,
  phoneRegion: CountryCode,
  array = false,
): string => (
  `${CONTACTS_KEYCHAIN_SERVICE}.${encodeURIComponent(ownerUserId)}.${phoneRegion}${array ? '_array' : ''}`
);

/**
 * Region used to read address-book numbers that omit a country code — most
 * people save local contacts that way. It has to be the SIGNED-IN USER's
 * country: a Colombian's "313 258 7634" is +57, not +58, and parsing it as
 * Venezuela produces a number belonging to someone else entirely.
 *
 * If the country is not available yet, discovery waits. Guessing a fallback
 * can turn an innocent address-book entry into the wrong payment recipient.
 */
let defaultPhoneRegion: CountryCode | null = null;

export const setDefaultPhoneRegion = (country?: string | null): void => {
  const iso = (country || '').trim().toUpperCase();
  defaultPhoneRegion = isSupportedCountry(iso) ? iso : null;
};

export const hasDefaultPhoneRegion = (): boolean => defaultPhoneRegion !== null;

const getDefaultPhoneRegion = (): CountryCode | undefined => defaultPhoneRegion || undefined;
const CONTACTS_PRIVACY_SERVICE = 'com.confio.contacts_privacy';
// Use a dedicated keychain service for upload consent to avoid overwriting permission status
const CONTACTS_CONSENT_SERVICE = 'com.confio.contacts_upload_consent';
const CONTACTS_UPLOAD_CONSENT_KEY = 'contacts_upload_consent';

export class ContactService {
  private static instance: ContactService;
  private contactsCache: ContactMap | null = null;
  private contactsArray: StoredContact[] | null = null;
  private contactOwnerUserId: string | null = null;
  private contactOwnerRegion: CountryCode | null = null;
  private cacheGeneration = 0;
  private activeSyncGeneration: number | null = null;

  private constructor() {}

  static getInstance(): ContactService {
    if (!ContactService.instance) {
      ContactService.instance = new ContactService();
    }
    return ContactService.instance;
  }

  /**
   * Preload contacts into memory for instant access
   */
  private async preloadContacts(
    expectedOwnerUserId: string,
    expectedPhoneRegion: CountryCode,
    expectedGeneration: number,
  ) {
    const startTime = Date.now();
    try {
      // Try to load from array format (fastest)
      const keychainStart = Date.now();
      const arrayCredentials = await Keychain.getInternetCredentials(
        contactsServiceForOwner(expectedOwnerUserId, expectedPhoneRegion, true),
      );
      if (hasUsableInternetCredentials(arrayCredentials) && arrayCredentials.username === CONTACTS_KEYCHAIN_KEY) {
        const parseStart = Date.now();
        const contactsArray = JSON.parse(arrayCredentials.password);
        if (Array.isArray(contactsArray)
          && this.contactOwnerUserId === expectedOwnerUserId
          && this.contactOwnerRegion === expectedPhoneRegion
          && this.cacheGeneration === expectedGeneration) {
          this.contactsArray = contactsArray;        }
      }
    } catch (error) {
    }
  }

  /**
   * Bind cached contact-to-account mappings to the authenticated user. Device
   * contacts are shared, but the inferred country and server matches are not.
   */
  async setContactOwner(userId?: string | null, country?: string | null): Promise<void> {
    const nextOwnerUserId = userId ? String(userId) : null;
    const iso = (country || '').trim().toUpperCase();
    const nextPhoneRegion = isSupportedCountry(iso) ? iso : null;
    if (this.contactOwnerUserId === nextOwnerUserId && this.contactOwnerRegion === nextPhoneRegion) return;

    this.contactOwnerUserId = nextOwnerUserId;
    this.contactOwnerRegion = nextPhoneRegion;
    const ownerGeneration = ++this.cacheGeneration;
    this.activeSyncGeneration = null;
    this.contactsCache = null;
    this.contactsArray = null;
    if (!nextOwnerUserId || !nextPhoneRegion) return;

    try {
      await this.preloadContacts(nextOwnerUserId, nextPhoneRegion, ownerGeneration);
      if (this.contactOwnerUserId === nextOwnerUserId
        && this.contactOwnerRegion === nextPhoneRegion
        && this.cacheGeneration === ownerGeneration
        && this.contactsArray === null) {
        this.contactsArray = [];
      }
    } catch (error) {
      console.error('Error binding contacts to authenticated user:', error);
      if (this.contactOwnerUserId === nextOwnerUserId
        && this.contactOwnerRegion === nextPhoneRegion
        && this.cacheGeneration === ownerGeneration) {
        this.contactsArray = [];
      }
    }
  }

  /**
   * Request contact permission from the user
   */
  async requestContactPermission(): Promise<boolean> {
    try {
      if (Platform.OS === 'android') {
        const granted = await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.READ_CONTACTS,
          {
            title: 'Acceso a Contactos',
            message: 'Confío necesita acceso a tus contactos para mostrarte los nombres de tus amigos en las transacciones.',
            buttonPositive: 'Permitir',
            buttonNegative: 'Cancelar',
          }
        );
        return granted === PermissionsAndroid.RESULTS.GRANTED;
      } else {
        // iOS
        const permission = await Contacts.checkPermission();
        if (permission === 'undefined') {
          const newPermission = await Contacts.requestPermission();
          return newPermission === 'authorized';
        }
        return permission === 'authorized';
      }
    } catch (error) {
      console.error('Error requesting contact permission:', error);
      return false;
    }
  }

  /**
   * Check if we have contact permission
   */
  async hasContactPermission(): Promise<boolean> {
    try {
      if (Platform.OS === 'android') {
        const granted = await PermissionsAndroid.check(
          PermissionsAndroid.PERMISSIONS.READ_CONTACTS
        );
        return granted;
      } else {
        const permission = await Contacts.checkPermission();
        return permission === 'authorized';
      }
    } catch (error) {
      console.error('Error checking contact permission:', error);
      return false;
    }
  }

  /**
   * Store permission status in keychain
   */
  async storePermissionStatus(status: 'granted' | 'denied' | 'pending'): Promise<void> {
    try {
      // Store under dedicated privacy service to avoid overwriting contacts data
      await Keychain.setInternetCredentials(
        CONTACTS_PRIVACY_SERVICE,
        CONTACT_PERMISSION_STATUS_KEY,
        status
      );
    } catch (error) {
      console.error('Error storing permission status:', error);
    }
  }

  /**
   * Get stored permission status
   */
  async getStoredPermissionStatus(): Promise<'granted' | 'denied' | 'pending' | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(CONTACTS_PRIVACY_SERVICE);
      if (hasUsableInternetCredentials(credentials) && credentials.username === CONTACT_PERMISSION_STATUS_KEY) {
        return credentials.password as 'granted' | 'denied' | 'pending';
      }
      return null;
    } catch (error) {
      console.error('Error getting permission status:', error);
      return null;
    }
  }

  /**
   * Store and check explicit upload consent (iOS requirement)
   */
  async setUploadConsent(consented: boolean): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        CONTACTS_CONSENT_SERVICE,
        CONTACTS_UPLOAD_CONSENT_KEY,
        consented ? 'true' : 'false'
      );
    } catch (error) {
      console.error('Error storing upload consent:', error);
    }
  }

  async hasUploadConsent(): Promise<boolean> {
    try {
      const credentials = await Keychain.getInternetCredentials(CONTACTS_CONSENT_SERVICE);
      if (hasUsableInternetCredentials(credentials) && credentials.username === CONTACTS_UPLOAD_CONSENT_KEY) {
        return credentials.password === 'true';
      }
      return false;
    } catch (error) {
      console.error('Error reading upload consent:', error);
      return false;
    }
  }

  /**
   * Check which phone numbers are Confío users
   */
  async checkConfioUsers(
    phoneNumbers: string[],
    apolloClient?: any,
    onBatchDone?: (processed: number, total: number) => void,
  ): Promise<Map<string, any>> {
    const confioUsersMap = new Map<string, any>();

    if (!apolloClient || phoneNumbers.length === 0) {
      return confioUsersMap;
    }

    // Import the query dynamically to avoid circular dependencies
    const { CHECK_USERS_BY_PHONES } = await import('../apollo/queries');

    // Query the server in batches of 50 phone numbers
    const batchSize = 50;
    for (let i = 0; i < phoneNumbers.length; i += batchSize) {
      const batch = phoneNumbers.slice(i, i + batchSize);
      const result = await apolloClient.query({
        query: CHECK_USERS_BY_PHONES,
        variables: { phoneNumbers: batch },
        fetchPolicy: 'network-only'
      });

      const users = result.data?.checkUsersByPhones;
      if (!Array.isArray(users)) {
        throw new Error('Contact discovery returned an invalid response');
      }
      const requestedPhones = new Set(batch);
      const returnedPhones = new Set<string>();
      users.forEach((userInfo: any) => {
        if (!userInfo?.phoneNumber || !requestedPhones.has(userInfo.phoneNumber)) {
          throw new Error('Contact discovery returned an unexpected phone number');
        }
        returnedPhones.add(userInfo.phoneNumber);
        if (userInfo?.isOnConfio) {
          if (!userInfo.userId) {
            throw new Error('Contact discovery returned an incomplete recipient');
          }
          confioUsersMap.set(userInfo.phoneNumber, {
            userId: userInfo.userId,
            username: userInfo.username,
            firstName: userInfo.firstName,
            lastName: userInfo.lastName,
            algorandAddress: userInfo.activeAccountAlgorandAddress,
            statusTier: userInfo.statusTier || null,
            isReferralVerified: userInfo.isReferralVerified || false,
          });
        }
      });
      if (returnedPhones.size !== requestedPhones.size) {
        throw new Error('Contact discovery omitted one or more phone numbers');
      }
      onBatchDone?.(Math.min(i + batchSize, phoneNumbers.length), phoneNumbers.length);
    }

    return confioUsersMap;
  }

  /**
   * Sync contacts from device and store in keychain
   * @param apolloClient - Apollo client for GraphQL queries
   */
  async syncContacts(apolloClient?: any, onProgress?: ContactSyncProgressListener): Promise<boolean> {
    const syncGeneration = ++this.cacheGeneration;
    this.activeSyncGeneration = syncGeneration;
    try {
      // A bare national number has no globally correct interpretation. Wait
      // for the authenticated user's verified phone country instead of
      // silently assigning an unrelated fallback country.
      const phoneRegion = defaultPhoneRegion;
      const ownerUserId = this.contactOwnerUserId;
      if (!phoneRegion || !ownerUserId || this.contactOwnerRegion !== phoneRegion) {
        return false;
      }
      const syncContextIsCurrent = () => (
        defaultPhoneRegion === phoneRegion
        && this.contactOwnerUserId === ownerUserId
        && this.contactOwnerRegion === phoneRegion
        && this.cacheGeneration === syncGeneration
      );
      const contactsService = contactsServiceForOwner(ownerUserId, phoneRegion);
      const contactsArrayService = contactsServiceForOwner(ownerUserId, phoneRegion, true);
      // A superseded sync must never move the progress bar of the current one.
      const report = (phase: ContactSyncPhase, processed: number, total: number) => {
        if (onProgress && syncContextIsCurrent()) onProgress({ phase, processed, total });
      };

      const hasPermission = await this.hasContactPermission();
      if (!hasPermission) {
        return false;
      }
      if (!syncContextIsCurrent()) return false;

      // Get all contacts from device
      report('reading', 0, 0);
      const contacts = await Contacts.getAll();
      if (!syncContextIsCurrent()) return false;

      if (!contacts || contacts.length === 0) {
        await Keychain.setInternetCredentials(
          contactsService,
          CONTACTS_KEYCHAIN_KEY,
          JSON.stringify({}),
        );
        if (!syncContextIsCurrent()) return false;
        await Keychain.setInternetCredentials(
          contactsArrayService,
          CONTACTS_KEYCHAIN_KEY,
          JSON.stringify([]),
        );
        if (!syncContextIsCurrent()) return false;
        this.contactsCache = {};
        this.contactsArray = [];
        return true;
      }

      // Process and normalize contacts
      const contactMap: ContactMap = {};
      const allPhoneNumbers: string[] = [];

      report('normalizing', 0, contacts.length);
      for (let index = 0; index < contacts.length; index++) {
        const contact = contacts[index];
        // Hand the JS thread back periodically: without this the progress text
        // cannot repaint and a large address book looks frozen.
        if (index > 0 && index % NORMALIZE_CHUNK_SIZE === 0) {
          report('normalizing', index, contacts.length);
          await yieldToUiThread();
          if (!syncContextIsCurrent()) return false;
        }
        if (!contact || !contact.phoneNumbers || contact.phoneNumbers.length === 0) {
          continue; // Skip contacts without phone numbers
        }

        const name = `${contact.givenName || ''} ${contact.familyName || ''}`.trim() ||
          contact.displayName ||
          'Unknown';

        const phones: string[] = [];
        const normalizedPhones: string[] = [];
        const inferredE164Phones: string[] = [];

        // Process all phone numbers
        contact.phoneNumbers.forEach(phoneObj => {
          const phone = phoneObj.number;
          phones.push(phone);

          // Try to normalize the phone number
          try {
            // Snapshot the region for this entire sync. An account switch or
            // sign-out must not produce one batch containing mixed countries.
            const parsed = parsePhoneNumber(phone, phoneRegion);
            const hasExplicitPlus = phone.trim().startsWith('+');
            const staysInLocalCallingPlan = parsed?.countryCallingCode === getCountryCallingCode(phoneRegion);
            if (parsed && parsed.isValid() && (hasExplicitPlus || staysInLocalCallingPlan)) {
              // Store in E.164 format for consistent matching
              normalizedPhones.push(parsed.format('E.164'));
              // Also store without + for backward compatibility
              normalizedPhones.push(parsed.format('E.164').substring(1));
              // Only a FULL number can be matched against a Confío account —
              // the server refuses countryless digits because they name no
              // country, and a wrong match here would hand the app a userId
              // that later sends resolve directly.
              allPhoneNumbers.push(parsed.format('E.164'));
              if (!hasExplicitPlus) {
                inferredE164Phones.push(parsed.format('E.164'));
              }
            } else {
              // If parsing fails, store cleaned version
              const cleaned = phone.replace(/\D/g, '');
              if (cleaned) {
                normalizedPhones.push(cleaned);
              }
            }
          } catch (error) {
            // If parsing fails, store cleaned version
            const cleaned = phone.replace(/\D/g, '');
            if (cleaned) {
              normalizedPhones.push(cleaned);
            }
          }
        });

        if (phones.length > 0) {
          const storedContact: StoredContact = {
            id: contact.recordID,
            name,
            phoneNumbers: phones,  // Changed from 'phones' to 'phoneNumbers'
            normalizedPhones,
            inferredE164Phones,
            avatar: contact.hasThumbnail ? contact.thumbnailPath : undefined,
            lastSynced: new Date().toISOString(),
            isOnConfio: false, // Default to false, will be updated later
          };

          // Map by all normalized phone numbers for easy lookup
          normalizedPhones.forEach(phone => {
            contactMap[phone] = storedContact;
          });
        }
      }

      // Check which contacts are Confío users
      let canUpload = true;
      if (Platform.OS === 'ios') {
        canUpload = await this.hasUploadConsent();
        if (!syncContextIsCurrent()) return false;
        if (!canUpload) {        }
      }

      if (apolloClient && allPhoneNumbers.length > 0 && canUpload) {
        const startCheck = Date.now();
        const uniquePhoneNumbers = Array.from(new Set(allPhoneNumbers));
        report('matching', 0, uniquePhoneNumbers.length);
        const confioUsersMap = await this.checkConfioUsers(
          uniquePhoneNumbers,
          apolloClient,
          (processed, total) => report('matching', processed, total),
        );
        if (!syncContextIsCurrent()) return false;

        type ContactMatch = { phoneNumber: string; userInfo: any };
        const matchesByContact = new Map<StoredContact, ContactMatch[]>();
        confioUsersMap.forEach((userInfo, phoneNumber) => {
          const contact = contactMap[phoneNumber];
          if (!contact) return;
          const matches = matchesByContact.get(contact) || [];
          matches.push({ phoneNumber, userInfo });
          matchesByContact.set(contact, matches);
        });

        const applyMatch = (contact: StoredContact, match: ContactMatch) => {
          contact.isOnConfio = true;
          contact.confioUserId = match.userInfo.userId;
          contact.confioUsername = match.userInfo.username;
          contact.confioFirstName = match.userInfo.firstName || undefined;
          contact.confioLastName = match.userInfo.lastName || undefined;
          contact.confioAlgorandAddress = match.userInfo.algorandAddress;
          contact.confioMatchedPhone = match.phoneNumber;
          contact.confioMatchWasInferred = Boolean(contact.inferredE164Phones?.includes(match.phoneNumber));
          contact.statusTier = match.userInfo.statusTier || null;
          contact.isReferralVerified = match.userInfo.isReferralVerified || false;
        };

        matchesByContact.forEach((matches, contact) => {
          const matchesByUser = new Map<string, ContactMatch[]>();
          matches.forEach(match => {
            const userMatches = matchesByUser.get(match.userInfo.userId) || [];
            userMatches.push(match);
            matchesByUser.set(match.userInfo.userId, userMatches);
          });

          if (matchesByUser.size === 1) {
            const userMatches = Array.from(matchesByUser.values())[0];
            const preferred = userMatches.find(match => !contact.inferredE164Phones?.includes(match.phoneNumber))
              || userMatches[0];
            applyMatch(contact, preferred);
            return;
          }

          // One address-book record can contain numbers owned by different
          // people (shared office/family cards). Never let server result order
          // choose which account receives money: split it into one recipient
          // per Confío account and keep any unmatched numbers as an invite.
          const matchedPhones = new Set(matches.map(match => match.phoneNumber));
          const originallyInferredPhones = new Set(contact.inferredE164Phones || []);
          const rawPhoneToE164 = new Map<string, string>();
          contact.phoneNumbers.forEach(rawPhone => {
            try {
              const parsed = parsePhoneNumber(rawPhone, phoneRegion);
              if (parsed?.isValid()) rawPhoneToE164.set(rawPhone, parsed.format('E.164'));
            } catch {}
          });

          Object.keys(contactMap).forEach(key => {
            if (contactMap[key] === contact) delete contactMap[key];
          });

          const unmatchedRawPhones = contact.phoneNumbers.filter(rawPhone => {
            const e164 = rawPhoneToE164.get(rawPhone);
            return !e164 || !matchedPhones.has(e164);
          });
          const unmatchedNormalizedPhones = contact.normalizedPhones.filter(phone => {
            const e164 = phone.startsWith('+') ? phone : `+${phone}`;
            return !matchedPhones.has(e164);
          });
          if (unmatchedRawPhones.length > 0 && unmatchedNormalizedPhones.length > 0) {
            contact.phoneNumbers = unmatchedRawPhones;
            contact.normalizedPhones = unmatchedNormalizedPhones;
            contact.inferredE164Phones = Array.from(originallyInferredPhones)
              .filter(phone => !matchedPhones.has(phone));
            unmatchedNormalizedPhones.forEach(phone => { contactMap[phone] = contact; });
          }

          matchesByUser.forEach(userMatches => {
            const phones = Array.from(new Set(userMatches.map(match => match.phoneNumber)));
            const preferred = userMatches.find(match => !originallyInferredPhones.has(match.phoneNumber))
              || userMatches[0];
            const recipientContact: StoredContact = {
              ...contact,
              phoneNumbers: contact.phoneNumbers.length > 0
                ? Array.from(rawPhoneToE164.entries())
                  .filter(([, e164]) => phones.includes(e164))
                  .map(([rawPhone]) => rawPhone)
                : phones,
              normalizedPhones: phones.flatMap(phone => [phone, phone.substring(1)]),
              inferredE164Phones: phones.filter(phone => originallyInferredPhones.has(phone)),
              isOnConfio: false,
            };
            if (recipientContact.phoneNumbers.length === 0) recipientContact.phoneNumbers = phones;
            applyMatch(recipientContact, preferred);
            phones.forEach(phone => {
              contactMap[phone] = recipientContact;
              contactMap[phone.substring(1)] = recipientContact;
            });
          });
        });      }

      if (!syncContextIsCurrent()) return false;

      // Store in keychain
      report('saving', 0, 0);
      const contactsData = JSON.stringify(contactMap);
      await Keychain.setInternetCredentials(
        contactsService,
        CONTACTS_KEYCHAIN_KEY,
        contactsData
      );
      if (!syncContextIsCurrent()) return false;

      // Update cache
      this.contactsCache = contactMap;

      // Create array of unique contacts for faster retrieval
      const uniqueContactsMap = new Map<string, StoredContact>();
      if (contactMap && typeof contactMap === 'object') {
        Object.values(contactMap).forEach(contact => {
          if (contact && contact.name && contact.phoneNumbers && contact.phoneNumbers[0]) {
            const key = `${contact.id}_${contact.confioUserId || contact.confioMatchedPhone || contact.phoneNumbers[0]}`;
            if (!uniqueContactsMap.has(key)) {
              uniqueContactsMap.set(key, contact);
            }
          }
        });
      }

      // Store as array for faster loading
      this.contactsArray = Array.from(uniqueContactsMap.values());

      // Also store the array format in keychain for next app launch
      const arrayData = JSON.stringify(this.contactsArray);
      await Keychain.setInternetCredentials(
        contactsArrayService,
        CONTACTS_KEYCHAIN_KEY,
        arrayData
      );
      return syncContextIsCurrent();
    } catch (error) {
      console.error('Error syncing contacts:', error);
      return false;
    } finally {
      if (this.activeSyncGeneration === syncGeneration) this.activeSyncGeneration = null;
    }
  }

  /**
   * Load contacts from keychain
   */
  async loadContactsFromKeychain(): Promise<ContactMap | null> {
    try {
      if (!this.contactOwnerUserId || !this.contactOwnerRegion) return null;
      const expectedOwnerUserId = this.contactOwnerUserId;
      const expectedPhoneRegion = this.contactOwnerRegion;
      const expectedGeneration = this.cacheGeneration;
      const credentials = await Keychain.getInternetCredentials(
        contactsServiceForOwner(expectedOwnerUserId, expectedPhoneRegion),
      );
      if (this.contactOwnerUserId !== expectedOwnerUserId
        || this.contactOwnerRegion !== expectedPhoneRegion
        || this.cacheGeneration !== expectedGeneration) return null;
      if (hasUsableInternetCredentials(credentials) && credentials.username === CONTACTS_KEYCHAIN_KEY) {
        const contactMap = JSON.parse(credentials.password) as ContactMap;
        this.contactsCache = contactMap;
        return contactMap;
      }
      return null;
    } catch (error) {
      console.error('Error loading contacts from keychain:', error);
      return null;
    }
  }

  /**
   * Get all stored contacts - Optimized for instant loading
   */
  async getAllContacts(): Promise<StoredContact[]> {
    const startTime = Date.now();

    // Return immediately if contacts are already in memory
    if (this.contactsArray && this.contactsArray.length > 0) {
      return this.contactsArray;
    }
    // If no contacts in memory, return empty array immediately
    // and trigger background load
    if (!this.contactsArray) {
      if (this.activeSyncGeneration !== null) return [];
      this.loadContactsInBackground();
      return [];
    }

    return this.contactsArray;
  }

  /**
   * Load contacts in background without blocking UI
   */
  private async loadContactsInBackground(): Promise<void> {
    const expectedOwnerUserId = this.contactOwnerUserId;
    const expectedPhoneRegion = this.contactOwnerRegion;
    const expectedGeneration = this.cacheGeneration;
    try {
      if (!expectedOwnerUserId || !expectedPhoneRegion) {
        this.contactsArray = [];
        return;
      }
      // Try to load from array format first (faster)
      try {
        const arrayCredentials = await Keychain.getInternetCredentials(
          contactsServiceForOwner(expectedOwnerUserId, expectedPhoneRegion, true),
        );
        if (hasUsableInternetCredentials(arrayCredentials) && arrayCredentials.username === CONTACTS_KEYCHAIN_KEY) {
          const contactsArray = JSON.parse(arrayCredentials.password);
          if (Array.isArray(contactsArray)
            && this.contactOwnerUserId === expectedOwnerUserId
            && this.contactOwnerRegion === expectedPhoneRegion
            && this.cacheGeneration === expectedGeneration) {
            this.contactsArray = contactsArray;
            return;
          }
        }
      } catch (e) {
        // Array format not found, try old format
      }

      // Fallback to old format
      const credentials = await Keychain.getInternetCredentials(
        contactsServiceForOwner(expectedOwnerUserId, expectedPhoneRegion),
      );
      if (this.contactOwnerUserId !== expectedOwnerUserId
        || this.contactOwnerRegion !== expectedPhoneRegion
        || this.cacheGeneration !== expectedGeneration) return;
      if (!hasUsableInternetCredentials(credentials) || credentials.username !== CONTACTS_KEYCHAIN_KEY) {
        this.contactsArray = [];
        return;
      }

      const contactsData = JSON.parse(credentials.password);

      // Old format: convert map to array
      if (contactsData && typeof contactsData === 'object') {
        const uniqueContacts = new Map<string, StoredContact>();

        Object.values(contactsData).forEach((contact: any) => {
          if (contact && contact.name && contact.phoneNumbers && contact.phoneNumbers.length > 0) {
            const key = `${contact.id}_${contact.confioUserId || contact.confioMatchedPhone || contact.phoneNumbers[0]}`;
            if (!uniqueContacts.has(key)) {
              uniqueContacts.set(key, contact);
            }
          }
        });

        this.contactsArray = Array.from(uniqueContacts.values());

        // Save in array format for next time
        const arrayData = JSON.stringify(this.contactsArray);
        await Keychain.setInternetCredentials(
          contactsServiceForOwner(expectedOwnerUserId, expectedPhoneRegion, true),
          CONTACTS_KEYCHAIN_KEY,
          arrayData
        );
      } else {
        this.contactsArray = [];
      }
    } catch (error) {
      console.error('Error loading contacts in background:', error);
      if (this.contactOwnerUserId === expectedOwnerUserId
        && this.contactOwnerRegion === expectedPhoneRegion
        && this.cacheGeneration === expectedGeneration) this.contactsArray = [];
    }
  }

  /**
   * Build cache from array - synchronous for performance
   */
  private buildCacheFromArray(): void {
    if (!this.contactsArray || this.contactsArray.length === 0) return;

    const cache: ContactMap = {};
    for (const contact of this.contactsArray) {
      // Add entries for all phone numbers and their variations
      // Use phoneNumbers field (correct field name) instead of phones
      const phoneNumbers = contact.phoneNumbers || contact.phones || [];
      for (const phone of phoneNumbers) {
        // Direct phone number
        cache[phone] = contact;

        // Cleaned version
        const cleaned = phone.replace(/\D/g, '');
        if (cleaned) {
          cache[cleaned] = contact;
        }

        // Try to parse and add variations
        try {
          const parsed = parsePhoneNumber(phone, getDefaultPhoneRegion());
          if (parsed && parsed.isValid()) {
            const e164 = parsed.format('E.164');
            const withoutPlus = e164.substring(1);
            cache[e164] = contact;
            cache[withoutPlus] = contact;
          }
        } catch (e) {
          // Parsing failed, continue
        }
      }

      // Also add normalized phones for better matching
      if (contact.normalizedPhones) {
        for (const phone of contact.normalizedPhones) {
          cache[phone] = contact;
        }
      }
    }
    this.contactsCache = cache;
  }

  /**
   * Get contact by phone number - SYNCHRONOUS for performance
   */
  getContactByPhoneSync(phoneNumber: string): StoredContact | null {
    if (!phoneNumber) return null;

    // Build cache from array if not available
    if (!this.contactsCache && this.contactsArray && this.contactsArray.length > 0) {
      this.buildCacheFromArray();
    }

    if (!this.contactsCache) return null;

    // Try direct lookup
    if (this.contactsCache[phoneNumber]) {
      return this.contactsCache[phoneNumber];
    }

    // Handle Confio format: "DO9293993618" (2-letter country code + phone number)
    const countryCodeMatch = phoneNumber.match(/^([A-Z]{2})(.+)$/);
    if (countryCodeMatch) {
      const [, countryCode, phoneWithoutCountry] = countryCodeMatch;

      // Try lookup with just the phone number part
      if (this.contactsCache[phoneWithoutCountry]) {
        return this.contactsCache[phoneWithoutCountry];
      }

      // Map country codes to dialing codes
      const countryDialingCodes: Record<string, string> = {
        'DO': '1809', // Dominican Republic
        'US': '1',
        'CA': '1',
        'VE': '58',
        'CO': '57',
        'MX': '52',
        'AR': '54',
        'BR': '55',
        'CL': '56',
        'PE': '51',
        'EC': '593',
        // Add more as needed
      };

      const dialingCode = countryDialingCodes[countryCode];
      if (dialingCode) {
        // Try various formats
        const withDialingCode = dialingCode + phoneWithoutCountry;
        const withPlus = '+' + dialingCode + phoneWithoutCountry;
        const justDialingWithoutCountry = '+' + phoneWithoutCountry;

        if (this.contactsCache[withDialingCode]) {
          return this.contactsCache[withDialingCode];
        }
        if (this.contactsCache[withPlus]) {
          return this.contactsCache[withPlus];
        }
        if (this.contactsCache[justDialingWithoutCountry]) {
          return this.contactsCache[justDialingWithoutCountry];
        }

        // For countries like DO that share +1, try without area code
        if (dialingCode.startsWith('1')) {
          const withJust1 = '1' + phoneWithoutCountry;
          const withPlus1 = '+1' + phoneWithoutCountry;
          if (this.contactsCache[withJust1]) {
            return this.contactsCache[withJust1];
          }
          if (this.contactsCache[withPlus1]) {
            return this.contactsCache[withPlus1];
          }
        }
      }
    }

    // Try cleaned lookup
    const cleaned = phoneNumber.replace(/\D/g, '');
    if (cleaned && this.contactsCache[cleaned]) {
      return this.contactsCache[cleaned];
    }

    // Try normalized lookup
    try {
      const parsed = parsePhoneNumber(phoneNumber, getDefaultPhoneRegion());
      if (parsed && parsed.isValid()) {
        const e164 = parsed.format('E.164');
        const withoutPlus = e164.substring(1);

        if (this.contactsCache[e164]) {
          return this.contactsCache[e164];
        }
        if (this.contactsCache[withoutPlus]) {
          return this.contactsCache[withoutPlus];
        }
      }
    } catch (error) {
      // Parsing failed, continue
    }

    return null;
  }

  /**
   * Get contact name by phone number - ASYNC version (use sync version for better performance)
   */
  async getContactByPhone(phoneNumber: string): Promise<StoredContact | null> {
    try {
      // Load from cache or keychain
      if (!this.contactsCache) {
        await this.loadContactsFromKeychain();
      }

      if (!this.contactsCache) {
        return null;
      }

      // Try direct lookup
      if (this.contactsCache[phoneNumber]) {
        return this.contactsCache[phoneNumber];
      }

      // Try normalized lookup
      try {
        // Clean the phone number
        const cleaned = phoneNumber.replace(/\D/g, '');
        if (this.contactsCache[cleaned]) {
          return this.contactsCache[cleaned];
        }

        // Try parsing and normalizing
        const parsed = parsePhoneNumber(phoneNumber, getDefaultPhoneRegion());
        if (parsed && parsed.isValid()) {
          const e164 = parsed.format('E.164');
          const withoutPlus = e164.substring(1);

          if (this.contactsCache[e164]) {
            return this.contactsCache[e164];
          }
          if (this.contactsCache[withoutPlus]) {
            return this.contactsCache[withoutPlus];
          }
        }
      } catch (error) {
        // Parsing failed, continue
      }

      return null;
    } catch (error) {
      console.error('Error getting contact by phone:', error);
      return null;
    }
  }

  /**
   * Get contact by exact display name (case-insensitive) - SYNCHRONOUS
   * Useful when transaction payload lacks phone but we have a contact name
   */
  getContactByNameSync(name: string): StoredContact | null {
    if (!name) return null;
    // Ensure contacts are available in memory
    if (!this.contactsArray || this.contactsArray.length === 0) return null;
    const target = name.trim().toLowerCase();
    for (const contact of this.contactsArray) {
      if ((contact.name || '').trim().toLowerCase() === target) {
        return contact;
      }
    }
    return null;
  }

  /**
   * Get contact by display name using fuzzy matching.
   * - Normalizes accents/diacritics
   * - Collapses whitespace and lowercases
   * - Tries exact, then startsWith, then contains
   */
  getContactByNameFuzzy(name: string): StoredContact | null {
    if (!name) return null;
    if (!this.contactsArray || this.contactsArray.length === 0) return null;

    const normalize = (s: string) => (s || '')
      .normalize('NFD')
      .replace(/\p{Diacritic}+/gu, '')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();

    const target = normalize(name);
    if (!target) return null;

    // 1) Exact normalized match
    for (const c of this.contactsArray) {
      const nm = normalize(c.name);
      if (nm === target) return c;
    }
    // 2) startsWith
    for (const c of this.contactsArray) {
      const nm = normalize(c.name);
      if (nm.startsWith(target)) return c;
    }
    // 3) contains
    for (const c of this.contactsArray) {
      const nm = normalize(c.name);
      if (nm.includes(target)) return c;
    }
    return null;
  }

  /**
   * Get all contacts that are Confío users
   */
  async getConfioContacts(confioUserPhones: string[]): Promise<StoredContact[]> {
    try {
      if (!this.contactsCache) {
        await this.loadContactsFromKeychain();
      }

      if (!this.contactsCache) {
        return [];
      }

      const confioContacts: StoredContact[] = [];
      const processedIds = new Set<string>();

      // Create a set of normalized Confío phone numbers for faster lookup
      const confioPhoneSet = new Set<string>();
      confioUserPhones.forEach(phone => {
        confioPhoneSet.add(phone);
        const cleaned = phone.replace(/\D/g, '');
        if (cleaned) {
          confioPhoneSet.add(cleaned);
        }
      });

      // Check each contact
      Object.values(this.contactsCache).forEach(contact => {
        if (!processedIds.has(contact.id)) {
          // Check if any of the contact's normalized phones match Confío users
          const isConfioUser = contact.normalizedPhones.some(phone =>
            confioPhoneSet.has(phone)
          );

          if (isConfioUser) {
            confioContacts.push(contact);
            processedIds.add(contact.id);
          }
        }
      });

      return confioContacts;
    } catch (error) {
      console.error('Error getting Confío contacts:', error);
      return [];
    }
  }

  /**
   * Find a contact by Algorand address (matches confioAlgorandAddress saved during sync)
   */
  getContactByAlgorandAddressSync(address: string): StoredContact | null {
    if (!address) return null;
    if (!this.contactsArray || this.contactsArray.length === 0) return null;
    const target = String(address).trim().toLowerCase();
    for (const c of this.contactsArray) {
      const a = (c as any).confioAlgorandAddress ? String((c as any).confioAlgorandAddress).trim().toLowerCase() : '';
      if (a && a === target) return c;
    }
    return null;
  }

  /**
   * Clear cached contacts
   */
  async clearContacts(): Promise<void> {
    const clearGeneration = ++this.cacheGeneration;
    this.activeSyncGeneration = null;
    try {
      const ownerUserId = this.contactOwnerUserId;
      const phoneRegion = this.contactOwnerRegion;
      if (ownerUserId && phoneRegion) {
        await softClearInternetCredentials(contactsServiceForOwner(ownerUserId, phoneRegion));
        await softClearInternetCredentials(contactsServiceForOwner(ownerUserId, phoneRegion, true));
      }
      if (this.contactOwnerUserId === ownerUserId
        && this.contactOwnerRegion === phoneRegion
        && this.cacheGeneration === clearGeneration) {
        this.contactsCache = null;
        this.contactsArray = [];
      }
    } catch (error) {
      console.error('Error clearing contacts:', error);
    }
  }


  /**
   * Get contacts count for quick UI updates
   */
  getContactsCount(): number {
    return this.contactsArray ? this.contactsArray.length : 0;
  }
}

// Export both the class and the singleton instance
export default ContactService;
export const contactService = ContactService.getInstance();
