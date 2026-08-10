import * as Keychain from 'react-native-keychain';
import { parsePhoneNumberFromString } from 'libphonenumber-js';
import { hasUsableInternetCredentials } from '../utils/keychainInternetCredentials';

const SERVICE = 'com.confio.confirmed_contact_recipients';
const USERNAME = 'confirmed_contact_recipients';
const MAX_CONFIRMATIONS = 500;

type ConfirmationStore = Record<string, string>;

export const formatRecipientPhoneForDisplay = (phone: string): string => {
  const trimmed = phone.trim();
  if (!trimmed.startsWith('+')) return phone;
  try {
    return parsePhoneNumberFromString(trimmed)?.formatInternational() || phone;
  } catch {
    return phone;
  }
};

export const isVerifiedInternationalRecipientPhone = (phone: string): boolean => {
  const trimmed = phone.trim();
  if (!trimmed.startsWith('+')) return false;
  try {
    return Boolean(parsePhoneNumberFromString(trimmed)?.isValid());
  } catch {
    return false;
  }
};

export const recipientNeedsConfirmation = (
  isOnConfio: boolean,
  confioMatchWasInferred?: boolean,
  phoneWasInferred?: boolean,
): boolean => isOnConfio ? Boolean(confioMatchWasInferred) : Boolean(phoneWasInferred);

export const inferredRecipientDiscoveryChanged = (
  isOnConfio: boolean,
  expectedRecipientUserId: string,
  liveRecipientUserId?: string | null,
): boolean => isOnConfio
  ? !liveRecipientUserId || String(liveRecipientUserId) !== String(expectedRecipientUserId)
  : Boolean(liveRecipientUserId);

const confirmationKey = (
  senderUserId: string,
  contactRecordId: string,
  recipientUserId: string,
) => JSON.stringify([senderUserId, contactRecordId, recipientUserId]);

const readStore = async (): Promise<ConfirmationStore> => {
  try {
    const credentials = await Keychain.getInternetCredentials(SERVICE);
    if (!hasUsableInternetCredentials(credentials) || credentials.username !== USERNAME) return {};
    const parsed = JSON.parse(credentials.password);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};

export const recipientConfirmationService = {
  async isConfirmed(
    senderUserId: string,
    contactRecordId: string,
    recipientUserId: string,
    matchedPhone: string,
  ): Promise<boolean> {
    const store = await readStore();
    return store[confirmationKey(senderUserId, contactRecordId, recipientUserId)] === matchedPhone;
  },

  async confirm(
    senderUserId: string,
    contactRecordId: string,
    recipientUserId: string,
    matchedPhone: string,
  ): Promise<void> {
    const store = await readStore();
    const key = confirmationKey(senderUserId, contactRecordId, recipientUserId);
    const next = { ...store, [key]: matchedPhone };
    const entries = Object.entries(next);
    const bounded = entries.length > MAX_CONFIRMATIONS
      ? Object.fromEntries(entries.slice(entries.length - MAX_CONFIRMATIONS))
      : next;
    try {
      await Keychain.setInternetCredentials(SERVICE, USERNAME, JSON.stringify(bounded));
    } catch {
      // Confirmation still applies to this send. If secure storage is
      // unavailable, the user will simply be asked again next time.
    }
  },
};
