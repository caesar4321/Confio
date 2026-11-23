// Sharing the person's own invitation and @usuario, from wherever it is
// offered (Invitar y ganar, a card in the chat).
import { Linking, Share } from 'react-native';
import { buildInviteLink, buildReferralShareMessage, normalizeInviteUsername } from '../utils/inviteLinks';
import { AnalyticsService } from './analyticsService';

/** Opens WhatsApp with the person's invitation (their link and code); the
 * phone's share sheet where WhatsApp is not there to open. `surface`: where
 * the tap happened, for the share-tap count. */
export async function shareReferralOnWhatsApp(username: string | null | undefined, surface: string): Promise<void> {
  try {
    AnalyticsService.logFunnelEvent('referral_whatsapp_share_tapped', {
      surface,
      referral_code: normalizeInviteUsername(username),
    }, {
      sourceType: 'referral_link',
      channel: 'whatsapp',
    });
  } catch (_e) {
    // never block sharing
  }
  const message = buildReferralShareMessage(username);
  const encoded = encodeURIComponent(message);
  const scheme = `whatsapp://send?text=${encoded}`;
  try {
    await Linking.openURL((await Linking.canOpenURL(scheme)) ? scheme : `https://wa.me/?text=${encoded}`);
  } catch (_error) {
    try {
      await Share.share({ message, title: 'Invitación Confío' });
    } catch (_shareError) {
      // closed without sharing
    }
  }
}

/** What someone needs to send this person money: their @usuario, and a link
 * that works for someone who does not have Confío yet. */
export function ownUsernameMessage(username: string): string {
  const clean = username.replace('@', '');
  return `Mi usuario en Confío es @${clean}. Búscame ahí para enviarme dinero.\n${buildInviteLink({ username: clean, source: 'share' })}`;
}

/** The phone's share sheet with that message. False when there is no @usuario to share. */
export async function shareOwnUsername(username: string | null | undefined): Promise<boolean> {
  if (!username) {
    return false;
  }
  try {
    await Share.share({ message: ownUsernameMessage(username) });
  } catch (_e) {
    // closed without sharing
  }
  return true;
}
