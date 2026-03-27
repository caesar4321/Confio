import { apolloClient } from '../apollo/client';
import { TRACK_CONTENT_PLATFORM_CLICK } from '../apollo/mutations';
import { AnalyticsService } from './analyticsService';

type ContentClickSurface = 'CHANNEL' | 'DISCOVER';
type ContentClickPlatform = 'TIKTOK' | 'INSTAGRAM' | 'YOUTUBE';

type TrackContentPlatformClickParams = {
  contentItemId: number | string;
  surface: ContentClickSurface;
  platform: ContentClickPlatform;
  channelId?: string;
  url: string;
};

function getDestinationHost(url: string): string {
  try {
    return new URL(url).host.toLowerCase();
  } catch {
    return 'unknown';
  }
}

export async function trackContentPlatformClick({
  contentItemId,
  surface,
  platform,
  channelId,
  url,
}: TrackContentPlatformClickParams): Promise<void> {
  const contentItemIdString = String(contentItemId);
  const destinationHost = getDestinationHost(url);

  await Promise.allSettled([
    AnalyticsService.logEvent('content_platform_click', {
      content_item_id: contentItemIdString,
      surface: surface.toLowerCase(),
      platform: platform.toLowerCase(),
      channel_id: channelId || '',
      destination_host: destinationHost,
    }),
    apolloClient.mutate({
      mutation: TRACK_CONTENT_PLATFORM_CLICK,
      variables: {
        contentItemId: contentItemIdString,
        platform,
        surface,
      },
    }),
  ]);
}
