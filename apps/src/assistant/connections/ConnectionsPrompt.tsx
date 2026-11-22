// How people find out: a card on the assistant's opening, a chip that stays,
// and one of them again when they ask about mail or calendar themselves.
import React, { useEffect } from 'react';
import { AppState, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { cardText, mentionsConnections, promptKind, unanswered } from './rules';
import { openConnections, readSnooze, snooze, useKnownSnooze, type Where } from './store';
import { useConnections, useViewer } from './useConnections';

type Props = {
  where: Where;
  /** The opening (chips) is showing. */
  starters: boolean;
  /** Only what was said in this opening: the thread is forever. */
  messages?: { role: string; body: string }[];
};

// This remounts with every turn of the chat, so it decides before asking the server anything.
export default function ConnectionsPrompt({ where, starters, messages }: Props) {
  return starters || (messages && mentionsConnections(messages)) ? <Viewer where={where} starters={starters} /> : null;
}

function Viewer({ where, starters }: { where: Where; starters: boolean }) {
  const userId = useViewer();
  return userId ? <Prompt key={userId} userId={userId} where={where} starters={starters} /> : null;
}

function Prompt({ userId, where, starters }: { userId: string; where: Where; starters: boolean }) {
  const { connections, build, refetch } = useConnections(userId, starters ? 'cache-and-network' : 'cache-first');
  // undefined until read: the card must not flash for someone who said "Ahora no".
  const until = useKnownSnooze(userId);
  const snoozeMatters = starters && !!connections && unanswered(connections);

  useEffect(() => {
    if (snoozeMatters && until === undefined) {
      void readSnooze(userId);
    }
  }, [snoozeMatters, until, userId]);

  // Inicio stays mounted: a place given meanwhile shows on coming back to the app.
  const shows = starters && !!connections;
  useEffect(() => {
    if (!shows) {
      return undefined;
    }
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        refetch().catch(() => undefined);
      }
    });
    return () => subscription?.remove();
  }, [shows, refetch]);

  if (!connections || (snoozeMatters && until === undefined)) {
    return null;
  }
  const kind = promptKind({ data: connections, build, starters, snoozedUntil: until ?? 0, now: Date.now() });
  const open = () => openConnections(userId, where);
  if (kind === 'chip') {
    return (
      <Pressable style={styles.chip} onPress={open} accessibilityRole="button">
        <Icon name="mail" size={14} color={colors.successText} />
        <Text style={styles.chipText}>Correo y calendario</Text>
      </Pressable>
    );
  }
  const ready = connections.gmail === 'invited' || connections.gmail === 'reconnect';
  const { title, body, cta } = cardText(connections);
  return (
    <View style={styles.card}>
      <View style={styles.titleRow}>
        <Icon name="mail" size={16} color={colors.successText} />
        <Text style={styles.title}>{title}</Text>
      </View>
      <Text style={styles.body}>{body}</Text>
      <View style={styles.actions}>
        <Pressable style={styles.primary} onPress={open} accessibilityRole="button">
          <Text style={styles.primaryText}>{cta}</Text>
        </Pressable>
        {ready ? null : (
          <Pressable style={styles.later} onPress={() => void snooze(userId)} accessibilityRole="button">
            <Text style={styles.laterText}>Ahora no</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { width: '100%', backgroundColor: colors.mint, borderRadius: 16, padding: 14, gap: 6 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.primaryDeep },
  body: { fontSize: 14, color: colors.primaryDeep },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 4 },
  primary: { minHeight: 44, borderRadius: 12, backgroundColor: colors.successText, justifyContent: 'center', paddingHorizontal: 14 },
  primaryText: { color: colors.white, fontSize: 14, fontWeight: '700' },
  later: { minHeight: 44, justifyContent: 'center' },
  laterText: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, borderRadius: 22, borderWidth: 1,
    borderColor: colors.primaryMuted, paddingHorizontal: 12, paddingVertical: 6,
  },
  chipText: { fontSize: 13, color: colors.successText, fontWeight: '600' },
});
