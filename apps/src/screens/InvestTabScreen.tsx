import React, { useCallback, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { useFocusEffect, useIsFocused, useNavigation } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { InvestScreen } from './InvestScreen';
import { DiscoverScreen } from './DiscoverScreen';
import { CommunityPreviewCard } from '../components/CommunityPreviewCard';
import { markCommunitySeen, refreshCommunityPeek, useCommunityPeek } from '../services/communityPeek';

export type InvestSegment = 'invest' | 'community';

const SEGMENTS: { key: InvestSegment; label: string }[] = [
  { key: 'invest', label: 'Invertir' },
  { key: 'community', label: 'Comunidad' },
];

/**
 * The second tab: Invertir and Comunidad side by side. Comunidad — what
 * members share about Recargar, Retirar, acciones, crypto, Bitcoin, oro — sits
 * next to the products it talks about. Confío News and Julian's posts are not
 * here: they live in the assistant bubble's channels.
 *
 * Both panes stay mounted so switching keeps each one's scroll position.
 *
 * Comunidad must not sit dormant one tap away: a preview card at the top of
 * Invertir shows the latest member posts, the segment carries a "Nuevo" /
 * count pill, and the Invertir tab icon a badge (BottomTabNavigator).
 */
export const InvestTabScreen = ({ route }: { route?: { params?: { segment?: InvestSegment } } }) => {
  const navigation = useNavigation<any>();
  const [segment, setSegment] = useState<InvestSegment>(route?.params?.segment ?? 'invest');
  const requested = route?.params?.segment;
  const peek = useCommunityPeek();
  const isFocused = useIsFocused();
  // A deep link (or the assistant) can ask for a segment while mounted.
  React.useEffect(() => {
    if (requested) setSegment(requested);
  }, [requested]);
  useFocusEffect(useCallback(() => { void refreshCommunityPeek(); }, []));
  // Looking at Comunidad is what clears the badges — only while it is
  // actually on screen (this tab focused AND the segment selected).
  React.useEffect(() => {
    if (isFocused && segment === 'community' && peek.loaded) void markCommunitySeen();
  }, [isFocused, segment, peek.loaded, peek.items]);
  const pill = peek.unread > 0 ? (peek.unread >= 10 ? '9+' : String(peek.unread))
    : peek.neverOpened ? 'Nuevo' : null;

  return (
    <View style={styles.screen}>
      <View style={styles.segmentBar}>
        <View style={styles.segmentTrack} accessibilityRole="tablist">
          {SEGMENTS.map(({ key, label }) => {
            const selected = key === segment;
            return (
              <Pressable
                key={key}
                onPress={() => setSegment(key)}
                style={[styles.segment, selected && styles.segmentSelected]}
                accessibilityRole="tab"
                accessibilityState={{ selected }}
              >
                <View style={styles.segmentLabel}>
                  <Text style={[styles.segmentText, selected && styles.segmentTextSelected]}>{label}</Text>
                  {key === 'community' && pill && !selected ? (
                    <View style={styles.pill}><Text style={styles.pillText}>{pill}</Text></View>
                  ) : null}
                </View>
              </Pressable>
            );
          })}
        </View>
      </View>
      <View style={[styles.pane, segment !== 'invest' && styles.hidden]}>
        <InvestScreen
          topAccessory={(
            <CommunityPreviewCard
              onOpen={() => setSegment('community')}
              onCompose={() => navigation.navigate('CommunityCompose')}
            />
          )}
        />
      </View>
      <View style={[styles.pane, segment !== 'community' && styles.hidden]}>
        <DiscoverScreen sections={['community']} />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  segmentBar: {
    backgroundColor: colors.heroField,
    paddingHorizontal: 16,
    paddingBottom: 10,
  },
  segmentTrack: {
    flexDirection: 'row',
    backgroundColor: 'rgba(6, 78, 59, 0.14)',
    borderRadius: 999,
    padding: 3,
  },
  segment: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 8,
    borderRadius: 999,
  },
  segmentSelected: { backgroundColor: colors.white },
  segmentLabel: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  pill: { backgroundColor: colors.secondary, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1 },
  pillText: { fontSize: 11, fontWeight: '700', color: colors.white },
  segmentText: { fontSize: 14, fontWeight: '600', color: colors.onHeroField },
  segmentTextSelected: { color: colors.textFlat },
  pane: { flex: 1 },
  hidden: { display: 'none' },
});

export default InvestTabScreen;
