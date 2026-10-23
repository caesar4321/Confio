import React from 'react';
import { Image, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { useCommunityPeek } from '../services/communityPeek';

type Props = {
  onOpen: () => void;
  onCompose: () => void;
};

/**
 * Comunidad, surfaced where people already are: the top of Invertir. The two
 * latest member posts and a way in — or, while the feed is empty, an
 * invitation to be first. What members share about recargas, retiros,
 * acciones, cripto y oro sits next to the products it talks about.
 */
export const CommunityPreviewCard = ({ onOpen, onCompose }: Props) => {
  const peek = useCommunityPeek();
  if (!peek.loaded) return null;
  const latest = peek.items.slice(0, 2);

  if (latest.length === 0) {
    return (
      <Pressable style={styles.card} onPress={onCompose} accessibilityRole="button">
        <View style={styles.headerRow}>
          <Icon name="users" size={16} color={colors.primaryDark} />
          <Text style={styles.title}>Comunidad</Text>
        </View>
        <Text style={styles.empty}>¿Cómo usas tus dólares? Cuéntale a la comunidad y sé de los primeros en publicar.</Text>
        <Text style={styles.link}>Publicar</Text>
      </Pressable>
    );
  }

  return (
    <Pressable style={styles.card} onPress={onOpen} accessibilityRole="button"
      accessibilityLabel="Abrir Comunidad">
      <View style={styles.headerRow}>
        <Icon name="users" size={16} color={colors.primaryDark} />
        <Text style={styles.title}>Comunidad</Text>
        {peek.unread > 0 ? (
          <View style={styles.pill}><Text style={styles.pillText}>{peek.unread >= 10 ? '9+' : peek.unread} nuevas</Text></View>
        ) : peek.neverOpened ? (
          <View style={styles.pill}><Text style={styles.pillText}>Nuevo</Text></View>
        ) : null}
        <View style={{ flex: 1 }} />
        <Text style={styles.link}>Ver todo</Text>
      </View>
      <Text style={styles.subtitle}>Lo que comparten otros miembros sobre su dinero</Text>
      {latest.map((item) => (
        <View key={item.id} style={styles.post}>
          {item.sourceAvatarUrl ? (
            <Image source={{ uri: item.sourceAvatarUrl }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarEmpty]}>
              <Text style={styles.avatarEmoji}>{item.sourceAvatarEmoji || '🙂'}</Text>
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.author} numberOfLines={1}>
              {item.sourceName || 'Miembro'} <Text style={styles.time}>· {item.time}</Text>
            </Text>
            <Text style={styles.snippet} numberOfLines={2}>{item.body || item.title}</Text>
          </View>
        </View>
      ))}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  card: { backgroundColor: colors.white, borderRadius: 16, padding: 14, gap: 8, borderWidth: 1, borderColor: '#EEF2F0' },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  title: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  subtitle: { fontSize: 12, color: colors.text.secondary },
  pill: { backgroundColor: colors.primaryLight, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { fontSize: 11, fontWeight: '700', color: colors.onHeroField },
  link: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  post: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingTop: 4 },
  avatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.neutralDark },
  avatarEmpty: { alignItems: 'center', justifyContent: 'center' },
  avatarEmoji: { fontSize: 16 },
  author: { fontSize: 13, fontWeight: '600', color: colors.textFlat },
  time: { fontWeight: '400', color: colors.text.secondary },
  snippet: { fontSize: 13, color: colors.text.primary, lineHeight: 18 },
  empty: { fontSize: 13, color: colors.text.primary, lineHeight: 19 },
});
