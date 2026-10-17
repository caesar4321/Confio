import notifee, { AndroidImportance } from '@notifee/react-native';

/** Android channel the server sends every COMMUNITY_* push on. */
export const COMMUNITY_CHANNEL_ID = 'community';

/**
 * Comunidad gets its own channel so members can silence posts, comments and
 * new followers in Android settings without losing money notifications.
 * Android only; creating an existing channel is a no-op.
 */
export const createCommunityChannel = () =>
  notifee.createChannel({
    id: COMMUNITY_CHANNEL_ID,
    name: 'Comunidad',
    description: 'Publicaciones, comentarios y seguidores',
    importance: AndroidImportance.DEFAULT,
  });

/** The channel a locally displayed push belongs on, matching the server's choice. */
export const androidChannelFor = (data?: Record<string, unknown> | null) =>
  String(data?.notification_type || '').startsWith('COMMUNITY_') ? COMMUNITY_CHANNEL_ID : 'default';
