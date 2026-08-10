/// <reference types="jest" />

const mockGetInternetCredentials = jest.fn();
const mockSetInternetCredentials = jest.fn();

jest.mock('react-native-keychain', () => ({
  getInternetCredentials: (...args: any[]) => mockGetInternetCredentials(...args),
  setInternetCredentials: (...args: any[]) => mockSetInternetCredentials(...args),
}));

import {
  formatRecipientPhoneForDisplay,
  inferredRecipientDiscoveryChanged,
  isVerifiedInternationalRecipientPhone,
  recipientConfirmationService,
  recipientNeedsConfirmation,
} from '../recipientConfirmationService';

describe('recipientConfirmationService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetInternetCredentials.mockResolvedValue(false);
    mockSetInternetCredentials.mockResolvedValue(true);
  });

  it('remembers the exact sender, device contact, account and matched phone', async () => {
    await recipientConfirmationService.confirm('sender-1', 'contact-1', 'recipient-1', '+573132587634');

    const serialized = mockSetInternetCredentials.mock.calls[0][2];
    mockGetInternetCredentials.mockResolvedValue({
      username: 'confirmed_contact_recipients',
      password: serialized,
    });

    await expect(recipientConfirmationService.isConfirmed(
      'sender-1', 'contact-1', 'recipient-1', '+573132587634',
    )).resolves.toBe(true);
    await expect(recipientConfirmationService.isConfirmed(
      'sender-1', 'contact-1', 'recipient-1', '+584121234567',
    )).resolves.toBe(false);
    await expect(recipientConfirmationService.isConfirmed(
      'sender-2', 'contact-1', 'recipient-1', '+573132587634',
    )).resolves.toBe(false);
  });

  it('requires confirmation for inferred registered users and inferred invitations', () => {
    expect(recipientNeedsConfirmation(true, true, false)).toBe(true);
    expect(recipientNeedsConfirmation(false, false, true)).toBe(true);
    expect(recipientNeedsConfirmation(true, false, true)).toBe(false);
    expect(recipientNeedsConfirmation(false, true, false)).toBe(false);
  });

  it('does not let separators in identifiers create the same confirmation key', async () => {
    await recipientConfirmationService.confirm('sender', 'contact:invite', '+57', '+573132587634');
    const serialized = mockSetInternetCredentials.mock.calls[0][2];
    mockGetInternetCredentials.mockResolvedValue({
      username: 'confirmed_contact_recipients',
      password: serialized,
    });

    await expect(recipientConfirmationService.isConfirmed(
      'sender', 'contact', 'invite:+57', '+573132587634',
    )).resolves.toBe(false);
  });

  it('formats E.164 recipients with real calling-code metadata', () => {
    expect(formatRecipientPhoneForDisplay('+573132587634')).toBe('+57 313 2587634');
    expect(formatRecipientPhoneForDisplay('+5491123456789')).toBe('+54 9 11 2345 6789');
    expect(formatRecipientPhoneForDisplay('313 258 7634')).toBe('313 258 7634');
  });

  it('allows only valid explicit international numbers into a phone-based send', () => {
    expect(isVerifiedInternationalRecipientPhone('+573132587634')).toBe(true);
    expect(isVerifiedInternationalRecipientPhone('3132587634')).toBe(false);
    expect(isVerifiedInternationalRecipientPhone('+999123')).toBe(false);
    expect(isVerifiedInternationalRecipientPhone('0058 412 123 4567')).toBe(false);
  });

  it('detects live discovery changes for registered users and invitations', () => {
    expect(inferredRecipientDiscoveryChanged(true, 'recipient-1', 'recipient-1')).toBe(false);
    expect(inferredRecipientDiscoveryChanged(true, 'recipient-1', 'recipient-2')).toBe(true);
    expect(inferredRecipientDiscoveryChanged(true, 'recipient-1', null)).toBe(true);
    expect(inferredRecipientDiscoveryChanged(false, 'invite:+57', null)).toBe(false);
    expect(inferredRecipientDiscoveryChanged(false, 'invite:+57', 'recipient-1')).toBe(true);
  });
});
