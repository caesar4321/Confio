// The call view inside the sheet: the pet listens, thinks and talks; live
// captions underneath; mute and hang up.
import React from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import ConfioIaMascot, { type MascotMood } from './ConfioIaMascot';
import { hangUp, toggleMute, useCall } from './callStore';

const STATUS: Record<string, string> = {
  connecting: 'Conectando…',
  listening: 'Te escucho',
  thinking: 'Pensando…',
  speaking: 'Hablando',
  idle: '',
  ended: '',
};

const MOOD: Record<string, MascotMood> = {
  connecting: 'thinking',
  listening: 'listening',
  thinking: 'thinking',
  speaking: 'talking',
};

export default function VoiceCallPanel({ profile }: { profile: { mascot?: string; mascotColor?: string; customPetUrl?: string | null } | null }) {
  const call = useCall();
  return (
    <View style={styles.wrap}>
      <View style={styles.hero}>
        <ConfioIaMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor} size={140} mood={MOOD[call.state] ?? 'idle'} />
        <Text style={styles.status}>{call.muted ? 'Micrófono apagado' : STATUS[call.state]}</Text>
        {call.minutesLeft !== null ? (
          <Text style={styles.minutes}>Te quedan {call.minutesLeft} min este mes</Text>
        ) : null}
      </View>
      <ScrollView style={styles.captions} contentContainerStyle={styles.captionsContent}>
        {call.captions.map((c, i) => (
          <Text key={`${i}-${c.text.slice(0, 8)}`} style={[styles.caption, c.role === 'user' && styles.captionUser]}>
            {c.text}
          </Text>
        ))}
      </ScrollView>
      <View style={styles.controls}>
        <Pressable
          onPress={toggleMute}
          style={[styles.round, call.muted && styles.roundActive]}
          accessibilityLabel={call.muted ? 'Activar micrófono' : 'Silenciar micrófono'}
        >
          <Icon name={call.muted ? 'mic-off' : 'mic'} size={24} color={call.muted ? '#FFFFFF' : '#111827'} />
        </Pressable>
        <Pressable onPress={hangUp} style={[styles.round, styles.hangUp]} accessibilityLabel="Colgar">
          <Icon name="phone-off" size={24} color="#FFFFFF" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, paddingHorizontal: 20 },
  hero: { alignItems: 'center', paddingTop: 24 },
  status: { fontSize: 18, fontWeight: '600', color: '#111827', marginTop: 12 },
  minutes: { fontSize: 13, color: '#6B7280', marginTop: 4 },
  captions: { flex: 1, marginTop: 16 },
  captionsContent: { gap: 8, paddingBottom: 12 },
  caption: { fontSize: 15, lineHeight: 21, color: '#374151' },
  captionUser: { color: '#047857', textAlign: 'right' },
  controls: { flexDirection: 'row', justifyContent: 'center', gap: 32, paddingVertical: 16 },
  round: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  roundActive: { backgroundColor: '#374151' },
  hangUp: { backgroundColor: '#DC2626' },
});
