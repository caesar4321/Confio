// Dependency-free (the push services import it): a WhatsApp notice opens the WhatsApp screen itself.
import { openWhatsAppFromNotification } from '../connections/store';

/** A notice about the person's WhatsApp (whatsapp_link): linked, unlinked, important messages, link again.
 * Its data as the in-app list sees it, or a push's flattened `data_` keys. */
export function isWhatsAppNotification(raw: unknown): boolean {
  let data: unknown = raw;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      return false;
    }
  }
  if (!data || typeof data !== 'object') {
    return false;
  }
  const d = data as Record<string, unknown>;
  return (d.type ?? d.data_type ?? d.extra_type) === 'whatsapp_link';
}

/** Opens the assistant's WhatsApp screen on Inicio, once the person's assistant is mounted there. */
export function routeWhatsAppNotification(raw: unknown, navigate: () => void): boolean {
  if (!isWhatsAppNotification(raw)) {
    return false;
  }
  navigate();
  openWhatsAppFromNotification();
  return true;
}
