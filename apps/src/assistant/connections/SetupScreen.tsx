// The setup screen every connection opens with (Gmail, Calendario), in WhatsApp's design: Confío and the other
// app linked on the brand field, a sheet with what it does, and one action pinned at the bottom.
import React, { useState } from 'react';
import { Image, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';

const CONFIO_ICON = require('../../assets/png/AppStoreIcon.png');

export type Hero = { title: string; chip?: string | null; live?: boolean };
export type Point = { icon: string; text: string };

type Props = {
  logo: React.ReactNode;
  hero: Hero;
  onClose: () => void;
  footer?: React.ReactNode;
  message?: string | null;
  children: React.ReactNode;
};

export default function SetupScreen({ logo, hero, onClose, footer, message, children }: Props) {
  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <View style={styles.screen}>
          <BrandField logo={logo} hero={hero} onClose={onClose} />
          <KeyboardAvoidingView style={styles.sheet} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            {/* flex: 1 so it shrinks to what the pinned footer leaves, and scrolls. */}
            <ScrollView style={styles.flex} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
              {children}
              {message ? <Alert text={message} /> : null}
            </ScrollView>
            {footer ? <SafeAreaView edges={['bottom']} style={styles.footer}>{footer}</SafeAreaView> : null}
          </KeyboardAvoidingView>
        </View>
      </SafeAreaProvider>
    </Modal>
  );
}

function BrandField({ logo, hero, onClose }: { logo: React.ReactNode; hero: Hero; onClose: () => void }) {
  return (
    <View style={styles.brandField}>
      <Svg style={StyleSheet.absoluteFill}>
        <Defs>
          <SvgLinearGradient id="setupField" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={colors.heroField} />
            <Stop offset="1" stopColor={colors.heroFieldDark} />
          </SvgLinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#setupField)" />
        <Circle cx="92%" cy="6%" r="120" stroke={colors.white} strokeWidth="28" strokeOpacity="0.10" fill="none" />
        <Circle cx="4%" cy="96%" r="70" stroke={colors.white} strokeWidth="18" strokeOpacity="0.08" fill="none" />
      </Svg>
      <SafeAreaView edges={['top']}>
        <View style={styles.fieldInner}>
          <View style={styles.fieldTop}>
            <Pressable style={styles.close} onPress={onClose} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.onHeroField} />
            </Pressable>
          </View>
          <View style={styles.fieldContent}>
            <View style={styles.logos}>
              <View style={styles.logoTile}>
                <Image source={CONFIO_ICON} style={styles.confioLogo} accessibilityIgnoresInvertColors />
              </View>
              <View style={styles.linkDots}>
                <View style={styles.linkDot} />
                <View style={styles.linkBadge}><Icon name="link-2" size={14} color={colors.primaryDeep} /></View>
                <View style={styles.linkDot} />
              </View>
              <View style={styles.logoTile}>{logo}</View>
            </View>
            <Text style={styles.fieldTitle} accessibilityRole="header">{hero.title}</Text>
            {hero.chip ? (
              <View style={styles.chip}>
                {hero.live ? <View style={styles.liveDot} /> : null}
                <Text style={styles.chipText}>{hero.chip}</Text>
              </View>
            ) : null}
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

/** What it does, in three or four short points on mint tiles. */
export function Points({ points }: { points: Point[] }) {
  return (
    <View style={styles.list}>
      {points.map((point, index) => (
        <View key={point.text} style={[styles.listRow, index > 0 && styles.listDivider]}>
          <View style={styles.tile}><Icon name={point.icon} size={18} color={colors.successText} /></View>
          <Text style={styles.listText}>{point.text}</Text>
        </View>
      ))}
    </View>
  );
}

/** What is read and kept, and the one risk worth naming. */
export function Notes({ data, risk }: { data: string; risk?: string }) {
  return (
    <View style={styles.notes}>
      <View style={styles.note}>
        <Icon name="lock" size={15} color={colors.gray600} />
        <Text style={styles.noteText}>{data}</Text>
      </View>
      {risk ? (
        <View style={[styles.note, styles.noteDivider]}>
          <Icon name="alert-triangle" size={15} color={colors.warning.icon} />
          <Text style={styles.noteText}>{risk}</Text>
        </View>
      ) : null}
    </View>
  );
}

/** The full consent, numbered, behind "Cómo funciona". */
export function Details({ lines }: { lines: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable style={styles.more} onPress={() => setOpen(!open)} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        <Text style={styles.moreText}>{open ? 'Ocultar detalles' : 'Cómo funciona'}</Text>
        <Icon name={open ? 'chevron-up' : 'chevron-down'} size={16} color={colors.successText} />
      </Pressable>
      {open ? (
        <View style={styles.details}>
          {lines.map((line, index) => (
            <View key={line} style={styles.detailRow}>
              <Text style={styles.detailNumber}>{index + 1}</Text>
              <Text style={styles.detail}>{line}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </>
  );
}

export function Alert({ text }: { text: string }) {
  return (
    <View style={styles.alert} accessibilityLiveRegion="polite">
      <Icon name="alert-circle" size={16} color={colors.error.icon} />
      <Text style={styles.alertText}>{text}</Text>
    </View>
  );
}

export function Action({ label, onPress, disabled = false, busy = false }: {
  label: string; onPress: () => void; disabled?: boolean; busy?: boolean;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.button, pressed && styles.pressed, (disabled || busy) && styles.disabled]}
      disabled={disabled || busy}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled: disabled || busy, busy }}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

export function Fine({ text }: { text: string }) {
  return <Text style={styles.fine}>{text}</Text>;
}

/** Unlink / disconnect: red, small, below the points. */
export function Danger({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable style={styles.unlink} onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={label}>
      <Icon name="link-2" size={15} color={colors.error.icon} />
      <Text style={styles.unlinkText}>{label}</Text>
    </Pressable>
  );
}

export function Secondary({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable style={styles.secondary} disabled={disabled} onPress={onPress} accessibilityRole="button" accessibilityState={{ disabled }}>
      <Text style={styles.secondaryText}>{label}</Text>
    </Pressable>
  );
}

export const setupStyles = StyleSheet.create({
  text: { fontSize: 14, color: colors.gray600, lineHeight: 20 },
  section: { fontSize: 18, fontWeight: '800', color: colors.textFlat },
  hint: { fontSize: 12, color: colors.textSecondary },
  card: { borderRadius: 18, backgroundColor: colors.surface, paddingHorizontal: 14 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  mint: { backgroundColor: colors.mint },
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.heroFieldDark },
  flex: { flex: 1 },
  brandField: { overflow: 'hidden' },
  fieldInner: { paddingBottom: 44 },
  fieldTop: { position: 'absolute', top: 0, right: 8, zIndex: 1 },
  close: {
    width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.22)', margin: 4,
  },
  fieldContent: { alignItems: 'center', paddingHorizontal: 56, paddingTop: 20, gap: 10 },
  logos: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  logoTile: {
    width: 58, height: 58, borderRadius: 18, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#064E3B', shadowOpacity: 0.18, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 4,
  },
  confioLogo: { width: 42, height: 42, borderRadius: 11 },
  linkDots: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  linkDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: 'rgba(255, 255, 255, 0.7)' },
  linkBadge: { width: 30, height: 30, borderRadius: 15, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  fieldTitle: { fontSize: 22, fontWeight: '800', color: colors.onHeroField, textAlign: 'center' },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.white, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 5,
  },
  chipText: { fontSize: 13, fontWeight: '700', color: colors.primaryDeep },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.successText },
  sheet: {
    flex: 1, backgroundColor: colors.background, borderTopLeftRadius: 28, borderTopRightRadius: 28, marginTop: -28,
    overflow: 'hidden',
  },
  content: { padding: 20, paddingTop: 24, paddingBottom: 32, gap: 16 },
  footer: {
    paddingHorizontal: 20, paddingTop: 12, paddingBottom: 12, gap: 8, borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border, backgroundColor: colors.background,
  },
  list: { borderRadius: 18, backgroundColor: colors.surface, paddingHorizontal: 14 },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  listDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  tile: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center' },
  listText: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat, lineHeight: 20 },
  notes: { borderRadius: 16, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 14 },
  note: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 12 },
  noteDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  noteText: { flex: 1, fontSize: 13, color: colors.gray600, lineHeight: 18 },
  more: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'center', minHeight: 44 },
  moreText: { color: colors.successText, fontSize: 14, fontWeight: '700' },
  details: { gap: 12, borderRadius: 16, backgroundColor: colors.surface, padding: 14 },
  detailRow: { flexDirection: 'row', gap: 10 },
  detailNumber: { width: 18, fontSize: 13, fontWeight: '800', color: colors.successText },
  detail: { flex: 1, fontSize: 13, color: colors.textSecondary, lineHeight: 18 },
  fine: { fontSize: 12, color: colors.textSecondary, textAlign: 'center' },
  alert: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: colors.error.background, borderRadius: 14, padding: 12 },
  alertText: { flex: 1, fontSize: 14, color: colors.error.text },
  button: { minHeight: 52, borderRadius: 16, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', padding: 12 },
  pressed: { opacity: 0.85 },
  disabled: { opacity: 0.45 },
  buttonText: { color: colors.white, fontSize: 16, fontWeight: '800' },
  unlink: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, minHeight: 48, marginTop: 8 },
  unlinkText: { color: colors.error.icon, fontSize: 14, fontWeight: '700' },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondaryText: { color: colors.successText, fontSize: 15, fontWeight: '700' },
});
