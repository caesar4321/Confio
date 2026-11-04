// The link that rides with an investment share card: the sharer's own
// invite link, tagged so the link worker (workers/link-shortener) records
// the click as coming from a share card, and the install referrer / IP
// match carries it to the signup it brings. Without a username (still
// loading), the plain landing page.
import { SHARE_LINKS } from '../config/shareLinks';
import { buildInviteLink } from './inviteLinks';

export type ShareTarget = 'whatsapp' | 'instagram' | 'system' | 'save';
export type ShareProduct = 'stock' | 'crypto' | 'perps';
export type ShareSurface = 'activity' | 'holding' | 'futures';

export function shareCardLink(
  username: string | null | undefined,
  tags: { target: ShareTarget; product: ShareProduct; surface: ShareSurface },
): string {
  if (!username) return SHARE_LINKS.web.landing;
  return buildInviteLink({
    username,
    utm: {
      utm_source: tags.target === 'save' ? 'image' : tags.target,
      utm_medium: 'share_card',
      utm_campaign: tags.product,
      utm_term: tags.surface,
    },
  });
}

/** The text that goes with the image: what happened, then the link and the hashtags. */
export const composeShareMessage = (lead: string, link: string) => `${lead}\n\n${link}\n\n${SHARE_LINKS.hashtags}`;
