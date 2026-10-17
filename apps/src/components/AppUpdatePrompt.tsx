import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, AppState, Modal, ScrollView, StyleSheet, TouchableOpacity, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { AppUpdatePolicy, fetchAppUpdatePolicy, openAppStore } from '../services/appUpdate';

// Re-ask on foreground at most this often, so a release published while the
// app sits in the background still reaches users without a cold start.
const RECHECK_AFTER_MS = 30 * 60 * 1000;

/**
 * Suggests the update when the store has a newer version than this one
 * (AppVersionPolicy, set per platform in the admin). Always a pop-up the
 * user can put off — never a screen that blocks the app — and put off
 * once per launch per version.
 */
export const AppUpdatePrompt: React.FC = () => {
  const [policy, setPolicy] = useState<AppUpdatePolicy | null>(null);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const lastCheckRef = useRef(0);

  const check = useCallback(async () => {
    lastCheckRef.current = Date.now();
    const next = await fetchAppUpdatePolicy();
    if (next) setPolicy(next);
  }, []);

  useEffect(() => {
    check();
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active' && Date.now() - lastCheckRef.current > RECHECK_AFTER_MS) check();
    });
    return () => subscription.remove();
  }, [check]);

  if (policy?.status !== 'update_available' || dismissedVersion === policy.latestVersion) return null;
  const dismiss = () => setDismissedVersion(policy.latestVersion);

  return (
    <UpdateSheet
      latestVersion={policy.latestVersion}
      highlights={highlightsFrom(policy.message)}
      onUpdate={() => { dismiss(); openAppStore(); }}
      onLater={dismiss}
    />
  );
};

// Shown when the admin leaves the message blank: true of every release,
// and the last line answers the fear that updating could touch the money.
const DEFAULT_HIGHLIGHTS: Highlight[] = [
  { icon: 'star', title: 'Lo más nuevo de Confío', body: 'Las funciones más recientes, apenas salen.' },
  { icon: 'zap', title: 'Más rápida y estable', body: 'Mejoras y correcciones para que todo fluya mejor.' },
  { icon: 'shield', title: 'Tu dinero sigue igual', body: 'Tu cuenta y tu saldo se quedan tal cual al actualizar.' },
];

type Highlight = { icon: string; title: string; body?: string };

// The admin message is the release's "Novedades", one per line; the
// reassurance line always closes the list.
const highlightsFrom = (message: string): Highlight[] => {
  const lines = message.split('\n').map(line => line.replace(/^[-•*]\s*/, '').trim()).filter(Boolean);
  if (!lines.length) return DEFAULT_HIGHLIGHTS;
  return [
    ...lines.slice(0, 4).map(title => ({ icon: 'check', title })),
    DEFAULT_HIGHLIGHTS[DEFAULT_HIGHLIGHTS.length - 1],
  ];
};

const UpdateSheet: React.FC<{
  latestVersion: string;
  highlights: Highlight[];
  onUpdate: () => void;
  onLater: () => void;
}> = ({ latestVersion, highlights, onUpdate, onLater }) => {
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  // The sheet always stops below the status bar / notch with the backdrop
  // showing above it; short phones (iPhone SE: 667pt) get a tighter layout,
  // and whatever still doesn't fit scrolls while the buttons stay put.
  const maxHeight = height - insets.top - TOP_GAP;
  const compact = height < COMPACT_BELOW;
  const slide = useRef(new Animated.Value(height)).current;
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, useNativeDriver: true, damping: 18, stiffness: 160 }),
      Animated.timing(fade, { toValue: 1, duration: 220, useNativeDriver: true }),
    ]).start();
  }, [slide, fade]);

  return (
    <Modal transparent visible animationType="none" statusBarTranslucent onRequestClose={onLater}>
      <Animated.View style={[styles.overlay, { opacity: fade }]}>
        <TouchableOpacity style={StyleSheet.absoluteFillObject} activeOpacity={1} onPress={onLater}
          accessibilityLabel="Cerrar" />
        <Animated.View style={[styles.sheet, { maxHeight, paddingBottom: Math.max(insets.bottom, 12) + 8,
          transform: [{ translateY: slide }] }]}>
          <View style={[styles.hero, compact && styles.heroCompact]}>
            <Svg style={StyleSheet.absoluteFillObject} width="100%" height="100%">
              <Defs>
                <LinearGradient id="appUpdateHero" x1="0%" y1="0%" x2="100%" y2="100%">
                  <Stop offset="0%" stopColor={HERO_TOP} />
                  <Stop offset="100%" stopColor={HERO_BOTTOM} />
                </LinearGradient>
              </Defs>
              <Rect x="0" y="0" width="100%" height="100%" fill="url(#appUpdateHero)" />
              <Circle cx="12%" cy="18%" r="46" fill="#FFFFFF" opacity={0.5} />
              <Circle cx="92%" cy="88%" r="70" fill="#FFFFFF" opacity={0.55} />
            </Svg>
            <View style={styles.handle} />
            <View style={[styles.badge, compact && styles.badgeCompact]}>
              <Icon name="gift" size={compact ? 28 : 34} color={ACCENT} />
            </View>
            {latestVersion ? (
              <View style={[styles.versionChip, compact && styles.versionChipCompact]}>
                <Icon name="star" size={12} color={ACCENT_TEXT} />
                <Text style={styles.versionText}>Versión {latestVersion}</Text>
              </View>
            ) : null}
          </View>

          <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, compact && styles.contentCompact]}
            bounces={false} showsVerticalScrollIndicator={false}>
            <Text style={[styles.title, compact && styles.titleCompact]}>¡Confío se puso todavía mejor!</Text>
            <Text style={[styles.subtitle, compact && styles.subtitleCompact]}>
              Hay una nueva versión esperándote. Actualizar tarda menos de un minuto.
            </Text>

            <View style={[styles.highlights, compact && styles.highlightsCompact]}>
              {highlights.map((item, index) => (
                <View key={index} style={[styles.highlight, compact && styles.highlightCompact]}>
                  <View style={styles.highlightIcon}>
                    <Icon name={item.icon} size={18} color={ACCENT_TEXT} />
                  </View>
                  <View style={styles.highlightText}>
                    <Text style={styles.highlightTitle}>{item.title}</Text>
                    {item.body ? <Text style={styles.highlightBody}>{item.body}</Text> : null}
                  </View>
                </View>
              ))}
            </View>
          </ScrollView>

          <View style={styles.footer}>
            <TouchableOpacity style={styles.primaryButton} onPress={onUpdate} activeOpacity={0.85}
              accessibilityRole="button">
              <Text style={styles.primaryText}>Actualizar ahora</Text>
              <Icon name="arrow-right" size={18} color="#FFFFFF" />
            </TouchableOpacity>
            <TouchableOpacity style={styles.secondaryButton} onPress={onLater} accessibilityRole="button">
              <Text style={styles.secondaryText}>Más tarde</Text>
            </TouchableOpacity>
          </View>
        </Animated.View>
      </Animated.View>
    </Modal>
  );
};

const TOP_GAP = 24;
const COMPACT_BELOW = 740;
// A light mint field (emerald-100 → emerald-50): an invitation, not an alert.
const HERO_TOP = colors.primaryLight;
const HERO_BOTTOM = '#ECFDF5';
const ACCENT = colors.primaryDark;
const ACCENT_TEXT = '#047857';

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(17, 24, 39, 0.4)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    overflow: 'hidden',
  },
  hero: { height: 168, alignItems: 'center', justifyContent: 'center' },
  heroCompact: { height: 124 },
  handle: {
    position: 'absolute',
    top: 10,
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(4, 120, 87, 0.18)',
  },
  badge: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
    elevation: 8,
  },
  versionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 14,
    paddingVertical: 5,
    paddingHorizontal: 12,
    borderRadius: 999,
    backgroundColor: colors.white,
  },
  badgeCompact: { width: 60, height: 60, borderRadius: 30 },
  versionChipCompact: { marginTop: 10 },
  versionText: { color: ACCENT_TEXT, fontSize: 13, fontWeight: '600' },
  scroll: { flexGrow: 0, flexShrink: 1 },
  content: { paddingHorizontal: 24, paddingTop: 22 },
  contentCompact: { paddingTop: 16 },
  footer: { paddingHorizontal: 24, paddingTop: 4 },
  title: { fontSize: 24, fontWeight: '700', color: colors.dark, textAlign: 'center', marginBottom: 8 },
  titleCompact: { fontSize: 21, marginBottom: 6 },
  subtitleCompact: { fontSize: 14, lineHeight: 20, marginBottom: 14 },
  subtitle: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.textSecondary,
    textAlign: 'center',
    marginBottom: 22,
  },
  highlights: {
    backgroundColor: colors.neutral,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 14,
    marginBottom: 22,
  },
  highlightsCompact: { marginBottom: 14, paddingVertical: 2 },
  highlight: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10 },
  highlightCompact: { paddingVertical: 7 },
  highlightIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  highlightText: { flex: 1 },
  highlightTitle: { fontSize: 15, fontWeight: '600', color: colors.dark },
  highlightBody: { fontSize: 13, lineHeight: 18, color: colors.textSecondary, marginTop: 2 },
  primaryButton: {
    flexDirection: 'row',
    gap: 8,
    backgroundColor: ACCENT,
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: ACCENT,
    shadowOpacity: 0.25,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  primaryText: { color: colors.white, fontSize: 16, fontWeight: '700' },
  secondaryButton: { paddingVertical: 14, alignItems: 'center', marginTop: 4 },
  secondaryText: { color: colors.textSecondary, fontSize: 15, fontWeight: '600' },
});
