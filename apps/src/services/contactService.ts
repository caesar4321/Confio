import Contacts from 'react-native-contacts';
import * as Keychain from 'react-native-keychain';
import { PermissionsAndroid, Platform } from 'react-native';
import { parsePhoneNumber } from 'libphonenumber-js';

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
  confioSuiAddress?: string;
}

interface ContactMap {
  [phoneNumber: string]: StoredContact;
}

const CONTACTS_KEYCHAIN_SERVICE = 'com.confio.contacts';
const CONTACTS_KEYCHAIN_KEY = 'user_contacts';
const CONTACT_PERMISSION_STATUS_KEY = 'contact_permission_status';

export class ContactService {
  private static instance: ContactService;
  private contactsCache: ContactMap | null = null;
  private contactsArray: StoredContact[] | null = null;

  private constructor() {
    // Preload contacts asynchronously to avoid blocking
    setTimeout(() => {
      this.preloadContacts();
    }, 50);
  }

  static getInstance(): ContactService {
    if (!ContactService.instance) {
      ContactService.instance = new ContactService();
    }
    return ContactService.instance;
  }

  /**
   * Preload contacts into memory for instant access
   */
  private async preloadContacts() {
    const startTime = Date.now();
    try {
      // Try to load from array format (fastest)
      const keychainStart = Date.now();
      const arrayCredentials = await Keychain.getInternetCredentials(CONTACTS_KEYCHAIN_SERVICE + '_array');
      console.log(`[PERF] Keychain read took: ${Date.now() - keychainStart}ms`);
      
      if (arrayCredentials && arrayCredentials.username === CONTACTS_KEYCHAIN_KEY) {
        const parseStart = Date.now();
        const contactsArray = JSON.parse(arrayCredentials.password);
        console.log(`[PERF] JSON parse took: ${Date.now() - parseStart}ms`);
        
        if (Array.isArray(contactsArray)) {
          this.contactsArray = contactsArray;
          console.log(`[PERF] Preloaded ${contactsArray.length} contacts in ${Date.now() - startTime}ms`);
        }
      }
    } catch (error) {
      console.log('Failed to preload contacts:', error);
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
      await Keychain.setInternetCredentials(
        CONTACTS_KEYCHAIN_SERVICE,
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
      const credentials = await Keychain.getInternetCredentials(CONTACTS_KEYCHAIN_SERVICE);
      if (credentials && credentials.username === CONTACT_PERMISSION_STATUS_KEY) {
        return credentials.password as 'granted' | 'denied' | 'pending';
      }
      return null;
    } catch (error) {
      console.error('Error getting permission status:', error);
      return null;
    }
  }

  /**
   * Check which phone numbers are Confío users
   */
  async checkConfioUsers(phoneNumbers: string[], apolloClient?: any): Promise<Map<string, any>> {
    const confioUsersMap = new Map<string, any>();
    
    if (!apolloClient || phoneNumbers.length === 0) {
      return confioUsersMap;
    }
    
    try {
      // Import the query dynamically to avoid circular dependencies
      const { CHECK_USERS_BY_PHONES } = await import('../apollo/queries');
      
      // Query the server in batches of 50 phone numbers
      const batchSize = 50;
      const totalBatches = Math.ceil(phoneNumbers.length / batchSize);
      console.log(`[SYNC] Will check users in ${totalBatches} batches`);
      
      for (let i = 0; i < phoneNumbers.length; i += batchSize) {
        const batch = phoneNumbers.slice(i, i + batchSize);
        const batchNum = Math.floor(i / batchSize) + 1;
        console.log(`[SYNC] Checking batch ${batchNum}/${totalBatches} with ${batch.length} phone numbers`);
        
        const result = await apolloClient.query({
          query: CHECK_USERS_BY_PHONES,
          variables: { phoneNumbers: batch },
          fetchPolicy: 'network-only'
        });
        
        if (result.data?.checkUsersByPhones) {
          result.data.checkUsersByPhones.forEach((userInfo: any) => {
            if (userInfo.isOnConfio) {
              confioUsersMap.set(userInfo.phoneNumber, {
                userId: userInfo.userId,
                username: userInfo.username,
                suiAddress: userInfo.activeAccountSuiAddress
              });
            }
          });
        }
      }
    } catch (error) {
      console.error('Error checking Confío users:', error);
    }
    
    return confioUsersMap;
  }

  /**
   * Sync contacts from device and store in keychain
   * @param apolloClient - Apollo client for GraphQL queries
   */
  async syncContacts(apolloClient?: any): Promise<boolean> {
    try {
      const hasPermission = await this.hasContactPermission();
      if (!hasPermission) {
        console.log('No contact permission');
        return false;
      }

      // Get all contacts from device
      const contacts = await Contacts.getAll();
      
      if (!contacts || contacts.length === 0) {
        console.log('No contacts found');
        return true; // Return true as sync was successful, just no contacts
      }
      
      // Process and normalize contacts
      const contactMap: ContactMap = {};
      const allPhoneNumbers: string[] = [];
      
      for (const contact of contacts) {
        if (!contact || !contact.phoneNumbers || contact.phoneNumbers.length === 0) {
          continue; // Skip contacts without phone numbers
        }
        
        const name = `${contact.givenName || ''} ${contact.familyName || ''}`.trim() || 
                     contact.displayName || 
                     'Unknown';
        
        const phones: string[] = [];
        const normalizedPhones: string[] = [];
        
        // Process all phone numbers
        contact.phoneNumbers.forEach(phoneObj => {
          const phone = phoneObj.number;
          phones.push(phone);
          allPhoneNumbers.push(phone); // Collect all phone numbers for batch checking
          
          // Try to normalize the phone number
          try {
            const parsed = parsePhoneNumber(phone, 'VE'); // Default to Venezuela
            if (parsed && parsed.isValid()) {
              // Store in E.164 format for consistent matching
              normalizedPhones.push(parsed.format('E.164'));
              // Also store without + for backward compatibility
              normalizedPhones.push(parsed.format('E.164').substring(1));
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
      if (apolloClient && allPhoneNumbers.length > 0) {
        console.log(`[SYNC] Checking ${allPhoneNumbers.length} phone numbers against Confío database...`);
        const startCheck = Date.now();
        const confioUsersMap = await this.checkConfioUsers(allPhoneNumbers, apolloClient);
        console.log(`[SYNC] Checked users in ${Date.now() - startCheck}ms`);
        
        // Update contacts with Confío user information
        confioUsersMap.forEach((userInfo, phoneNumber) => {
          // Find all contacts that match this phone number
          Object.keys(contactMap).forEach(key => {
            const contact = contactMap[key];
            if (contact.phoneNumbers && (contact.phoneNumbers.includes(phoneNumber) || contact.normalizedPhones.includes(phoneNumber))) {
              contact.isOnConfio = true;
              contact.confioUserId = userInfo.userId;
              contact.confioUsername = userInfo.username;
              contact.confioSuiAddress = userInfo.suiAddress;
              
              // Keep the local contact name - don't replace with Confío user's profile name
              // Users should see the names they have saved in their contacts
            }
          });
        });
        
        console.log(`Found ${confioUsersMap.size} Confío users among contacts`);
      }

      // Store in keychain
      const contactsData = JSON.stringify(contactMap);
      await Keychain.setInternetCredentials(
        CONTACTS_KEYCHAIN_SERVICE,
        CONTACTS_KEYCHAIN_KEY,
        contactsData
      );

      // Update cache
      this.contactsCache = contactMap;

      // Create array of unique contacts for faster retrieval
      const uniqueContactsMap = new Map<string, StoredContact>();
      if (contactMap && typeof contactMap === 'object') {
        Object.values(contactMap).forEach(contact => {
          if (contact && contact.name && contact.phoneNumbers && contact.phoneNumbers[0]) {
            const key = `${contact.name}_${contact.phoneNumbers[0]}`;
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
        CONTACTS_KEYCHAIN_SERVICE + '_array',
        CONTACTS_KEYCHAIN_KEY,
        arrayData
      );

      console.log(`Synced ${this.contactsArray.length} unique contacts`);
      return true;
    } catch (error) {
      console.error('Error syncing contacts:', error);
      return false;
    }
  }

  /**
   * Load contacts from keychain
   */
  async loadContactsFromKeychain(): Promise<ContactMap | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(CONTACTS_KEYCHAIN_SERVICE);
      if (credentials && credentials.username === CONTACTS_KEYCHAIN_KEY) {
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
      console.log(`[PERF] getAllContacts returned ${this.contactsArray.length} contacts from memory in ${Date.now() - startTime}ms`);
      return this.contactsArray;
    }

    console.log(`[PERF] getAllContacts - no contacts in memory, returning empty`);
    
    // If no contacts in memory, return empty array immediately
    // and trigger background load
    if (!this.contactsArray) {
      this.loadContactsInBackground();
      return [];
    }

    return this.contactsArray;
  }

  /**
   * Load contacts in background without blocking UI
   */
  private async loadContactsInBackground(): Promise<void> {
    try {
      // Try to load from array format first (faster)
      try {
        const arrayCredentials = await Keychain.getInternetCredentials(CONTACTS_KEYCHAIN_SERVICE + '_array');
        if (arrayCredentials && arrayCredentials.username === CONTACTS_KEYCHAIN_KEY) {
          const contactsArray = JSON.parse(arrayCredentials.password);
          if (Array.isArray(contactsArray)) {
            this.contactsArray = contactsArray;
            return;
          }
        }
      } catch (e) {
        // Array format not found, try old format
      }

      // Fallback to old format
      const credentials = await Keychain.getInternetCredentials(CONTACTS_KEYCHAIN_SERVICE);
      if (!credentials || credentials.username !== CONTACTS_KEYCHAIN_KEY) {
        this.contactsArray = [];
        return;
      }

      const contactsData = JSON.parse(credentials.password);
      
      // Old format: convert map to array
      if (contactsData && typeof contactsData === 'object') {
        const uniqueContacts = new Map<string, StoredContact>();
        
        Object.values(contactsData).forEach((contact: any) => {
          if (contact && contact.name && contact.phoneNumbers && contact.phoneNumbers.length > 0) {
            const key = `${contact.name}_${contact.phoneNumbers[0]}`;
            if (!uniqueContacts.has(key)) {
              uniqueContacts.set(key, contact);
            }
          }
        });
        
        this.contactsArray = Array.from(uniqueContacts.values());
        
        // Save in array format for next time
        const arrayData = JSON.stringify(this.contactsArray);
        await Keychain.setInternetCredentials(
          CONTACTS_KEYCHAIN_SERVICE + '_array',
          CONTACTS_KEYCHAIN_KEY,
          arrayData
        );
      } else {
        this.contactsArray = [];
      }
    } catch (error) {
      console.error('Error loading contacts in background:', error);
      this.contactsArray = [];
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
          const parsed = parsePhoneNumber(phone, 'VE');
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

    // Try cleaned lookup
    const cleaned = phoneNumber.replace(/\D/g, '');
    if (cleaned && this.contactsCache[cleaned]) {
      return this.contactsCache[cleaned];
    }

    // Try normalized lookup
    try {
      const parsed = parsePhoneNumber(phoneNumber, 'VE');
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
        const parsed = parsePhoneNumber(phoneNumber, 'VE');
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
   * Clear cached contacts
   */
  async clearContacts(): Promise<void> {
    try {
      await Keychain.resetInternetCredentials(CONTACTS_KEYCHAIN_SERVICE);
      this.contactsCache = null;
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