import { contactService } from '../services/contactService';
import { formatPhoneForDisplay } from '../hooks/useContactName';

export function getPreferredDisplayName(phone?: string | null, fallback?: string | null): { name: string; fromContacts: boolean } {
  try {
    if (phone) {
      const c = contactService.getContactByPhoneSync(phone);
      if (c && c.name) {
        return { name: c.name, fromContacts: true };
      }
    }
  } catch {}
  return { name: (fallback || phone || 'Desconocido'), fromContacts: false };
}

export function getPreferredSecondaryLine(opts: {
  phone?: string | null;
  address?: string | null;
  isExternal?: boolean;
}): string {
  const { phone, address, isExternal } = opts;
  if (phone && String(phone).trim()) return formatPhoneForDisplay(String(phone));
  if (isExternal && address) {
    const full = String(address);
    if (full.length > 40) return `${full.substring(0, 10)}...${full.substring(full.length - 6)}`;
    return full;
  }
  return '';
}
