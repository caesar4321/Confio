import type { ContentPollData } from '../components/ContentPoll';
import type { DiscoverItem } from '../components/DiscoverFeed';

/** A Descubrir card as the server sends it (discoverFeed, communityMemberPosts). */
export type DiscoverFeedDto = {
  id: string;
  type: 'product' | 'video' | 'news';
  tag: string;
  tagColor: string;
  title: string;
  body: string;
  time: string;
  thumbnail: boolean;
  platformLinks?: Array<{ platform: 'TikTok' | 'Instagram' | 'YouTube'; url: string }> | null;
  imageUrl?: string | null;
  reactionSummary?: Array<{ emoji: string; count: number }> | null;
  viewerReaction?: string | null;
  poll?: ContentPollData | null;
  canReact?: boolean | null;
  sourceName?: string | null;
  isOfficial?: boolean | null;
  sourceAvatarUrl?: string | null;
  sourceAvatarEmoji?: string | null;
};

/** The card shape DiscoverFeed / DiscoverPostCard render. */
export const toDiscoverItem = (item: DiscoverFeedDto): DiscoverItem => ({
  id: Number(item.id),
  type: item.type,
  tag: item.tag,
  tagColor: item.tagColor,
  title: item.title,
  body: item.body,
  time: item.time,
  thumbnail: item.thumbnail,
  platformLinks: item.platformLinks || [],
  imageUrl: item.imageUrl || undefined,
  reactionSummary: item.reactionSummary || [],
  viewerReaction: item.viewerReaction,
  poll: item.poll,
  canReact: item.canReact ?? true,
  sourceName: item.sourceName || undefined,
  isOfficial: Boolean(item.isOfficial),
  sourceAvatarUrl: item.sourceAvatarUrl || null,
  sourceAvatarEmoji: item.sourceAvatarEmoji || null,
});
