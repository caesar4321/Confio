import React, { useMemo, useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

const tealGreen = '#1DB587';
const tealLight = '#E8F8F2';

type ReactionMap = Record<string, number>;

type NewsItem = {
  id: number;
  type: 'product' | 'video' | 'news';
  tag: string;
  tagColor: string;
  title: string;
  body: string;
  time: string;
  thumbnail?: boolean;
  reactions: ReactionMap;
};

const initialNewsItems: NewsItem[] = [
  {
    id: 1,
    type: 'product',
    tag: 'Producto',
    tagColor: '#1DB587',
    title: 'Integracion Koywe completada',
    body: 'Ya tenemos on/off-ramp confirmado para Argentina, Colombia, Mexico, Peru y Bolivia. El retiro a cuenta bancaria llega en 2-4 semanas.',
    time: 'Hace 2 horas',
    reactions: { '🔥': 142, '🙌': 89, '😍': 64, '👀': 31 },
  },
  {
    id: 2,
    type: 'video',
    tag: 'Video',
    tagColor: '#FF4444',
    title: 'Por que el Big Mac mas caro de LATAM esta en Argentina?',
    body: 'Nuevo video explicando la paradoja del precio del dolar en Argentina post-CEPO. Miralo en TikTok o YouTube.',
    time: 'Hace 9 horas',
    thumbnail: true,
    reactions: { '🤯': 203, '💡': 117, '🔥': 88 },
  },
  {
    id: 3,
    type: 'product',
    tag: 'KYC',
    tagColor: '#7C3AED',
    title: 'Confio x Didit - verificacion en tiempo real',
    body: 'Demo disponible. Verifica tu identidad en menos de 60 segundos directamente desde la app. Sin papeles, sin esperas.',
    time: 'Ayer',
    reactions: { '😎': 95, '🙌': 72, '🔥': 44 },
  },
  {
    id: 4,
    type: 'news',
    tag: 'Mercado',
    tagColor: '#F59E0B',
    title: 'Venezuela: dolarizacion de facto sin infraestructura',
    body: 'El 60% de los pagos en Caracas ya son en USD, pero el sistema bancario sigue anclado al bolivar. Confio llega cuando el sistema falla.',
    time: 'Hace 2 dias',
    reactions: { '💪': 178, '😢': 43, '👀': 91 },
  },
];

const emojiOptions = ['🔥', '🙌', '😍', '🤯', '💡', '😎', '💪', '👀', '😢', '❤️'];

const tagIcons: Record<NewsItem['type'], string> = {
  product: '🚀',
  video: '▶',
  news: '📊',
};

export default function DiscoverMockUpScreen() {
  const [userReactions, setUserReactions] = useState<Record<number, string | null>>({});
  const [showEmojiPicker, setShowEmojiPicker] = useState<number | null>(null);
  const [reactions, setReactions] = useState<Record<number, ReactionMap>>(
    initialNewsItems.reduce<Record<number, ReactionMap>>((acc, item) => {
      acc[item.id] = { ...item.reactions };
      return acc;
    }, {})
  );

  const handleReact = (itemId: number, emoji: string) => {
    const previousEmoji = userReactions[itemId];
    const nextReactions = { ...(reactions[itemId] || {}) };

    if (previousEmoji) {
      nextReactions[previousEmoji] = Math.max(0, (nextReactions[previousEmoji] || 1) - 1);
      if (nextReactions[previousEmoji] === 0) {
        delete nextReactions[previousEmoji];
      }
    }

    if (previousEmoji !== emoji) {
      nextReactions[emoji] = (nextReactions[emoji] || 0) + 1;
      setUserReactions((prev) => ({ ...prev, [itemId]: emoji }));
    } else {
      setUserReactions((prev) => ({ ...prev, [itemId]: null }));
    }

    setReactions((prev) => ({ ...prev, [itemId]: nextReactions }));
    setShowEmojiPicker(null);
  };

  const topReactionsByItem = useMemo(() => {
    return initialNewsItems.reduce<Record<number, Array<[string, number]>>>((acc, item) => {
      acc[item.id] = Object.entries(reactions[item.id] || {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3);
      return acc;
    }, {});
  }, [reactions]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {initialNewsItems.map((item) => (
        <View key={item.id} style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={[styles.tagPill, { backgroundColor: `${item.tagColor}18` }]}>
              <Text style={[styles.tagText, { color: item.tagColor }]}>
                {tagIcons[item.type]} {item.tag}
              </Text>
            </View>
            <Text style={styles.timeText}>{item.time}</Text>
          </View>

          <Text style={styles.cardTitle}>{item.title}</Text>
          <Text style={styles.cardBody}>{item.body}</Text>

          {item.thumbnail && (
            <View style={styles.thumbnail}>
              <View style={styles.thumbnailPlayButton}>
                <Icon name="play" size={14} color="#111827" />
              </View>
              <Text style={styles.thumbnailLabel}>TikTok · YouTube</Text>
            </View>
          )}

          <View style={styles.reactionRow}>
            {topReactionsByItem[item.id]?.map(([emoji, count]) => {
              const active = userReactions[item.id] === emoji;
              return (
                <Pressable
                  key={emoji}
                  onPress={() => handleReact(item.id, emoji)}
                  style={[styles.reactionButton, active && styles.reactionButtonActive]}
                >
                  <Text style={styles.reactionEmoji}>{emoji}</Text>
                  <Text style={styles.reactionCount}>{count}</Text>
                </Pressable>
              );
            })}

            <Pressable
              onPress={() => setShowEmojiPicker(showEmojiPicker === item.id ? null : item.id)}
              style={styles.addReactionButton}
            >
              <Text style={styles.addReactionText}>+ 😊</Text>
            </Pressable>
          </View>

          {showEmojiPicker === item.id && (
            <View style={styles.emojiPicker}>
              {emojiOptions.map((emoji) => {
                const active = userReactions[item.id] === emoji;
                return (
                  <Pressable
                    key={emoji}
                    onPress={() => handleReact(item.id, emoji)}
                    style={[styles.emojiOption, active && styles.emojiOptionActive]}
                  >
                    <Text style={styles.emojiOptionText}>{emoji}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F4F6F8',
  },
  content: {
    paddingHorizontal: 14,
    paddingTop: 14,
    paddingBottom: 28,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingTop: 14,
    paddingBottom: 10,
    marginBottom: 10,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 1,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tagPill: {
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  tagText: {
    fontSize: 11,
    fontWeight: '700',
  },
  timeText: {
    fontSize: 11,
    color: '#AAAAAA',
  },
  cardTitle: {
    marginBottom: 5,
    fontSize: 14,
    fontWeight: '700',
    lineHeight: 19,
    color: '#111111',
  },
  cardBody: {
    marginBottom: 10,
    fontSize: 13,
    lineHeight: 20,
    color: '#555555',
  },
  thumbnail: {
    height: 80,
    borderRadius: 10,
    marginBottom: 10,
    backgroundColor: '#182235',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  thumbnailPlayButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: 'rgba(255,255,255,0.92)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  thumbnailLabel: {
    position: 'absolute',
    left: 10,
    bottom: 7,
    fontSize: 10,
    fontWeight: '600',
    color: '#FFFFFF',
    opacity: 0.85,
  },
  reactionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 5,
  },
  reactionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderWidth: 1.5,
    borderColor: 'transparent',
  },
  reactionButtonActive: {
    backgroundColor: tealLight,
    borderColor: tealGreen,
  },
  reactionEmoji: {
    fontSize: 13,
  },
  reactionCount: {
    fontSize: 11,
    fontWeight: '600',
    color: '#666666',
  },
  addReactionButton: {
    backgroundColor: '#F4F6F8',
    borderRadius: 20,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  addReactionText: {
    fontSize: 12,
    color: '#888888',
  },
  emojiPicker: {
    marginTop: 8,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#EAEAEA',
    backgroundColor: '#FFFFFF',
    padding: 8,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 16,
    elevation: 2,
  },
  emojiOption: {
    width: 34,
    height: 34,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
  },
  emojiOptionActive: {
    backgroundColor: tealLight,
  },
  emojiOptionText: {
    fontSize: 17,
  },
});
