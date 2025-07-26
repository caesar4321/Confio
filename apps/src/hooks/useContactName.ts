import { useState, useEffect, useCallback } from 'react';
import { contactService } from '../services/contactService';

interface ContactInfo {
  displayName: string;
  isFromContacts: boolean;
  originalName?: string;
}

/**
 * Hook to get contact name from local contacts
 * Falls back to the provided name if no contact is found
 */
export function useContactName(
  phoneNumber?: string | null,
  fallbackName?: string | null
): ContactInfo {
  const [contactInfo, setContactInfo] = useState<ContactInfo>({
    displayName: fallbackName || phoneNumber || 'Unknown',
    isFromContacts: false,
  });

  useEffect(() => {
    const loadContactName = async () => {
      if (!phoneNumber) {
        setContactInfo({
          displayName: fallbackName || 'Unknown',
          isFromContacts: false,
        });
        return;
      }

      try {
        const contact = await contactService.getContactByPhone(phoneNumber);
        
        if (contact) {
          setContactInfo({
            displayName: contact.name,
            isFromContacts: true,
            originalName: fallbackName || phoneNumber,
          });
        } else {
          setContactInfo({
            displayName: fallbackName || phoneNumber,
            isFromContacts: false,
          });
        }
      } catch (error) {
        console.error('Error loading contact name:', error);
        setContactInfo({
          displayName: fallbackName || phoneNumber,
          isFromContacts: false,
        });
      }
    };

    loadContactName();
  }, [phoneNumber, fallbackName]);

  return contactInfo;
}

/**
 * Hook to manage multiple contact names (useful for lists)
 */
export function useContactNames() {
  const [contactCache, setContactCache] = useState<Map<string, ContactInfo>>(new Map());
  const [isLoading, setIsLoading] = useState(false);

  const getContactName = useCallback(
    async (phoneNumber?: string | null, fallbackName?: string | null): Promise<ContactInfo> => {
      if (!phoneNumber) {
        return {
          displayName: fallbackName || 'Unknown',
          isFromContacts: false,
        };
      }

      // Check cache first
      const cached = contactCache.get(phoneNumber);
      if (cached) {
        return cached;
      }

      try {
        const contact = await contactService.getContactByPhone(phoneNumber);
        
        const info: ContactInfo = contact
          ? {
              displayName: contact.name,
              isFromContacts: true,
              originalName: fallbackName || phoneNumber,
            }
          : {
              displayName: fallbackName || phoneNumber,
              isFromContacts: false,
            };

        // Update cache
        setContactCache(prev => new Map(prev).set(phoneNumber, info));
        
        return info;
      } catch (error) {
        console.error('Error getting contact name:', error);
        return {
          displayName: fallbackName || phoneNumber,
          isFromContacts: false,
        };
      }
    },
    [contactCache]
  );

  const preloadContacts = useCallback(
    async (phoneNumbers: Array<{ phone?: string | null; fallbackName?: string | null }>) => {
      setIsLoading(true);
      
      try {
        const promises = phoneNumbers.map(({ phone, fallbackName }) =>
          getContactName(phone, fallbackName)
        );
        
        await Promise.all(promises);
      } catch (error) {
        console.error('Error preloading contacts:', error);
      } finally {
        setIsLoading(false);
      }
    },
    [getContactName]
  );

  const clearCache = useCallback(() => {
    setContactCache(new Map());
  }, []);

  return {
    getContactName,
    preloadContacts,
    clearCache,
    isLoading,
    contactCache,
  };
}

/**
 * Format phone number for display
 */
export function formatPhoneForDisplay(phone: string): string {
  // Remove any non-digit characters
  const cleaned = phone.replace(/\D/g, '');
  
  // Format based on length and country
  if (cleaned.startsWith('58') && cleaned.length === 12) {
    // Venezuelan number: +58 412-345-6789
    return `+${cleaned.slice(0, 2)} ${cleaned.slice(2, 5)}-${cleaned.slice(5, 8)}-${cleaned.slice(8)}`;
  } else if (cleaned.startsWith('1') && cleaned.length === 11) {
    // US/Canada: +1 234-567-8901
    return `+${cleaned.slice(0, 1)} ${cleaned.slice(1, 4)}-${cleaned.slice(4, 7)}-${cleaned.slice(7)}`;
  } else if (cleaned.length === 10) {
    // Generic 10-digit: 234-567-8901
    return `${cleaned.slice(0, 3)}-${cleaned.slice(3, 6)}-${cleaned.slice(6)}`;
  } else if (cleaned.length > 10) {
    // International with country code
    const countryCodeLength = cleaned.length - 10;
    return `+${cleaned.slice(0, countryCodeLength)} ${cleaned.slice(countryCodeLength)}`;
  }
  
  // Return as-is if no pattern matches
  return phone;
}