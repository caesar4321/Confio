import React from 'react';
import { Alert, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { colors } from '../config/theme';
import { VerifiedBadge } from './VerifiedBadge';

const OFFICIAL_EXPLAINER =
  'Esta fuente es un canal de Confío o una organización cuya identidad legal y ' +
  'titularidad de la cuenta verificó Confío. Si esa verificación deja de estar vigente, ' +
  'la insignia desaparece.';

type Props = {
  name?: string;
  isOfficial?: boolean;
  avatarUrl?: string | null;
  avatarEmoji?: string | null;
  /** Secondary line: topic and time on cards, date and reading time on detail. */
  meta?: string;
  size?: 'card' | 'detail';
};

/** Initial for a channel with no avatar, skipping leading emoji and symbols. */
// Cased letters and digits only: portable across JS engines, unlike \p{L}.
export const channelInitial = (name: string) =>
  (Array.from(name).find((ch) => ch.toLowerCase() !== ch.toUpperCase() || (ch >= '0' && ch <= '9')) || '·')
    .toUpperCase();

/** Who published a post: avatar, name, the Oficial check, and one line of context. */
export function PostByline({ name, isOfficial = false, avatarUrl, avatarEmoji, meta, size = 'card' }: Props) {
  // Keyed to the URL that failed, so a replaced avatar gets a fresh attempt.
  const [failedUrl, setFailedUrl] = React.useState<string | null>(null);
  if (!name) return null;
  const imageFailed = Boolean(avatarUrl) && failedUrl === avatarUrl;
  const detail = size === 'detail';
  const avatarSize = detail ? 40 : 36;
  const avatarStyle = { width: avatarSize, height: avatarSize, borderRadius: avatarSize / 2 };

  return (
    <View style={styles.row}>
      {avatarUrl && !imageFailed ? (
        <Image
          source={{ uri: avatarUrl }}
          style={[styles.avatarImage, avatarStyle]}
          onError={() => setFailedUrl(avatarUrl)}
          accessibilityIgnoresInvertColors
        />
      ) : (
        <View style={[styles.avatarFallback, avatarStyle]}>
          <Text style={avatarEmoji ? styles.avatarEmoji : styles.avatarInitial}>
            {avatarEmoji || channelInitial(name)}
          </Text>
        </View>
      )}
      <View style={styles.copy}>
        <View style={styles.nameRow}>
          <Text style={[styles.name, detail && styles.nameDetail]} numberOfLines={1}>
            {name}
          </Text>
          {isOfficial && (
            <Pressable
              onPress={() => Alert.alert('Fuente oficial', OFFICIAL_EXPLAINER)}
              hitSlop={10}
              accessibilityRole="button"
              accessibilityLabel="Fuente oficial verificada por Confío. Toca para saber más."
            >
              <VerifiedBadge size={detail ? 17 : 16} />
            </Pressable>
          )}
        </View>
        {meta ? (
          <Text style={styles.meta} numberOfLines={1}>
            {meta}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  avatarImage: {
    backgroundColor: colors.neutralDark,
  },
  avatarFallback: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primarySoft,
  },
  avatarEmoji: {
    fontSize: 18,
  },
  avatarInitial: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.primaryDeep,
  },
  copy: {
    flex: 1,
    minWidth: 0,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  name: {
    flexShrink: 1,
    fontSize: 14,
    fontWeight: '700',
    color: colors.dark,
  },
  nameDetail: {
    fontSize: 15,
  },
  meta: {
    marginTop: 1,
    fontSize: 12,
    color: colors.text.light,
  },
});
