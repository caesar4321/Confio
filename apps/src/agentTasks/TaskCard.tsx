// The general card (server: agent_tasks/cards.py): whatever the agent asks the person, composed by the server
// from a small, fixed set of blocks: an icon, a title, a picture, labelled lines, a total, one short notice and
// one or two buttons. A new job (a flight, a table, an appointment) needs no new drawing here. An unknown icon is
// drawn as a generic one, an unknown screen's button is left out, and a card version this build does not know is
// not drawn at all (the older drawing and the task's message stay).
import React, { useState } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { colors } from '../config/theme';
import { AGENT_CARD_VERSION, AgentCard, AgentCardAction } from './api';

const ICONS: Record<string, string> = {
  bag: 'shopping-bag', package: 'package', calendar: 'calendar', bed: 'moon', bus: 'truck', plane: 'send',
  table: 'coffee', user: 'user', help: 'help-circle', bell: 'bell',
};

// The screens a button may open, with this build's own parameters: the server only names one.
export const CARD_SCREENS: Record<string, Record<string, unknown>> = {
  SmartAccountOffer: { door: 'chip', trigger: 'agent_purchase' },
};

const https = (uri: string) => (/^https:\/\//.test(uri) ? uri : '');

export function Photo({ uri, size }: { uri: string; size: number }) {
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size };
  if (!https(uri) || failed) {
    return <View style={[styles.photo, styles.photoEmpty, box]}><Icon name="package" size={size / 3} color="#9CA3AF" /></View>;
  }
  return <Image source={{ uri }} style={[styles.photo, box]} resizeMode="contain" onError={() => setFailed(true)} />;
}

/** A card this build can draw: a version it knows. */
export const drawable = (card: AgentCard | null | undefined): card is AgentCard =>
  !!card && typeof card.version === 'number' && card.version >= 1 && card.version <= AGENT_CARD_VERSION;

export function TaskCard({ card, tapping, onAnswer, onOpen }: {
  card: AgentCard;
  tapping: string | null;
  onAnswer: (action: AgentCardAction) => void;
  onOpen?: (screen: string, params?: Record<string, unknown>) => void;
}) {
  // A button that opens a screen this build does not have, or with nowhere to open it, is left out.
  const actions = (card.actions ?? []).filter((one) => !one.screen || (onOpen && CARD_SCREENS[one.screen]));
  const busy = tapping !== null;
  return (
    <View style={styles.box}>
      <View style={styles.top}>
        {https(card.image) ? <Photo uri={card.image} size={72} /> : (
          <View style={styles.icon} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"><Icon name={ICONS[card.icon] ?? 'info'} size={20} color={colors.primaryDark} /></View>
        )}
        <View style={styles.body}>
          {card.title ? <Text style={styles.title} numberOfLines={4}>{card.title}</Text> : null}
          {(card.lines ?? []).map((line, index) => (
            line.label ? (
              <View key={`${index}:${line.label}`} style={styles.line}>
                <Text style={styles.lineLabel}>{line.label}</Text>
                <Text style={styles.lineValue}>{line.value}</Text>
              </View>
            ) : <Text key={`${index}:${line.value}`} style={styles.lineAlone}>{line.value}</Text>
          ))}
          {card.total ? (
            <>
              <View style={styles.line}>
                <Text style={styles.totalLabel}>{card.total.label}</Text>
                <Text style={styles.total}>{card.total.value}</Text>
              </View>
              {card.total.note ? <Text style={styles.lineLabel}>{card.total.note}</Text> : null}
            </>
          ) : null}
        </View>
      </View>
      {card.notice ? <Text style={styles.notice}>{card.notice}</Text> : null}
      {card.actions?.length && !actions.length ? (
        <Text style={styles.notice}>Actualiza Confío para confirmar esto aquí.</Text>
      ) : null}
      {actions.length ? (
        <View style={styles.actions}>
          {actions.map((one) => {
            const press = () => {
              if (one.screen) {
                onOpen?.(one.screen, CARD_SCREENS[one.screen]);
              } else {
                onAnswer(one);
              }
            };
            return one.style === 'link' ? (
              <Pressable key={one.id} onPress={press} accessibilityRole="button" accessibilityLabel={one.label}
                style={styles.link} disabled={busy}>
                {tapping === `card:${one.id}` ? <ActivityIndicator color={colors.primaryDark} />
                  : <Text style={styles.linkText}>{one.label}</Text>}
              </Pressable>
            ) : (
              <Button key={one.id} title={one.label} loading={tapping === `card:${one.id}`} disabled={busy && tapping !== `card:${one.id}`}
                onPress={press} />
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 10 },
  top: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  icon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryLight },
  body: { flex: 1, gap: 4 },
  title: { fontSize: 15, lineHeight: 20, fontWeight: '600', color: colors.text.primary },
  line: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  lineLabel: { fontSize: 13, color: '#6B7280' },
  lineValue: { flexShrink: 1, fontSize: 13, color: '#6B7280', textAlign: 'right', fontVariant: ['tabular-nums'] },
  lineAlone: { fontSize: 14, color: colors.text.primary },
  totalLabel: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  total: { fontSize: 18, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  notice: { fontSize: 13, color: '#6B7280' },
  actions: { gap: 4 },
  photo: { borderRadius: 10, backgroundColor: '#FFFFFF', alignSelf: 'center' },
  photoEmpty: { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.neutralDark },
  link: { alignSelf: 'center', minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  linkText: { fontSize: 14, color: colors.text.secondary, textDecorationLine: 'underline' },
});
