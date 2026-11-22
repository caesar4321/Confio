// Shared building blocks of the Cuenta inteligente screens. They reuse the
// app's primitives (the shared Header, AppText, SkeletonLoader, Feather icons,
// theme tokens) and add only what these screens repeat: a screen scaffold with
// its loading / error states, cards, single-button rows, the pinned action
// bar, the calm notice and the acceptance row.
//
// Accessibility rules every piece follows: a tappable element is at least
// 44pt tall and has a label; a row is ONE accessible button; text wraps
// instead of truncating, and amounts shrink to fit rather than cut.
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../common/AppText';
import { SkeletonLoader } from '../SkeletonLoader';
import { Header } from '../../navigation/Header';
import { SA, HIT, cardShadow } from './tokens';

// ------------------------------------------------------------- help sheet

export interface HelpContent {
  title: string;
  paragraphs: string[];
}

/** A bottom sheet. Closes on the backdrop, the hardware back and its button. */
/**
 * The keyboard's height while it is up, 0 otherwise. A sheet lives in a
 * status-bar-translucent Modal, which Android's window resize does not reach,
 * so the sheet lifts itself above the keyboard.
 */
export function useKeyboardHeight(): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const show = Keyboard.addListener(showEvent, (e) => setHeight(e?.endCoordinates?.height ?? 0));
    const hide = Keyboard.addListener(hideEvent, () => setHeight(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  return height;
}

export function Sheet({
  visible, onClose, title, children, dismissable = true, testID,
}: {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  /** false while something is in flight: the sheet cannot be closed under it. */
  dismissable?: boolean;
  testID?: string;
}) {
  const insets = useSafeAreaInsets();
  const keyboard = useKeyboardHeight();
  const close = () => {
    if (dismissable) {
      onClose();
    }
  };
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close} statusBarTranslucent>
      <View style={styles.sheetRoot} testID={testID}>
        <Pressable
          style={styles.sheetBackdrop}
          onPress={close}
          accessibilityRole="button"
          accessibilityLabel="Cerrar"
          disabled={!dismissable}
        />
        <View
          style={[
            styles.sheet,
            keyboard > 0
              ? { marginBottom: keyboard, paddingBottom: 16 }
              : { paddingBottom: Math.max(insets.bottom, 16) + 8 },
          ]}
        >
          <View style={styles.sheetHandle} />
          <ScrollView bounces={false} contentContainerStyle={styles.sheetContent} keyboardShouldPersistTaps="handled">
            {title ? <Text style={styles.sheetTitle} accessibilityRole="header">{title}</Text> : null}
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** The "¿Cómo funciona?" entry: a help circle in the header, never a list row. */
export function HelpButton({ help, onDark }: { help: HelpContent; onDark?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        style={styles.helpButton}
        hitSlop={6}
        accessibilityRole="button"
        accessibilityLabel="¿Cómo funciona?"
      >
        <Icon name="help-circle" size={22} color={onDark ? SA.onDeep : SA.muted} />
      </Pressable>
      <Sheet visible={open} onClose={() => setOpen(false)} title={help.title}>
        {help.paragraphs.map((p) => (
          <Text key={p} style={styles.helpParagraph}>{p}</Text>
        ))}
        <ActionButton label="Entendido" onPress={() => setOpen(false)} style={styles.sheetButton} />
      </Sheet>
    </>
  );
}

// ---------------------------------------------------------------- screen

/**
 * The scaffold of every stack screen here: the app's shared Header (title,
 * back, help circle), a scrolling body and an optional pinned action bar.
 * `tone="deep"` continues the account's emerald field under the header.
 */
export function SmartScreen({
  title, help, tone = 'plain', children, footer, onRefresh, refreshing = false,
  scroll = true, onBack, showBack = true, isHome = false, onProfilePress, avatar, testID,
}: {
  title: string;
  help?: HelpContent;
  tone?: 'plain' | 'deep';
  children: React.ReactNode;
  /** Pinned under the content: the primary action is always one tap away. */
  footer?: React.ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  /** false when the body is its own scroller (a FlatList). */
  scroll?: boolean;
  onBack?: () => void;
  showBack?: boolean;
  /** The account's home as a main tab: the header shows the account avatar. */
  isHome?: boolean;
  onProfilePress?: () => void;
  avatar?: string;
  testID?: string;
}) {
  const navigation = useNavigation<any>();
  const insets = useSafeAreaInsets();
  const deep = tone === 'deep';
  return (
    <View style={styles.screen} testID={testID}>
      <StatusBar barStyle={deep ? 'light-content' : 'dark-content'} backgroundColor={deep ? SA.deep : SA.card} />
      <Header
        navigation={navigation}
        title={title}
        backgroundColor={deep ? SA.deep : SA.card}
        isLight={deep}
        showBackButton={showBack && !isHome}
        onBackPress={onBack}
        isHomeScreen={false}
        unreadNotifications={0}
        currentAccountAvatar={avatar || 'C'}
        rightAccessory={(help || (isHome && onProfilePress)) ? (
          <View style={styles.headerRight}>
            {help ? <HelpButton help={help} onDark={deep} /> : null}
            {isHome && onProfilePress ? (
              <Pressable
                onPress={onProfilePress}
                style={styles.avatar}
                hitSlop={4}
                accessibilityRole="button"
                accessibilityLabel="Perfil y cuentas"
              >
                <Text style={styles.avatarText}>{avatar || 'C'}</Text>
              </Pressable>
            ) : null}
          </View>
        ) : undefined}
      />
      {scroll ? (
        <ScrollView
          style={styles.flex}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          refreshControl={onRefresh ? (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={SA.deep} colors={[SA.deep]} />
          ) : undefined}
        >
          {children}
        </ScrollView>
      ) : (
        <View style={styles.flex}>{children}</View>
      )}
      {footer ? (
        <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, 12) }]}>{footer}</View>
      ) : null}
    </View>
  );
}

// ----------------------------------------------------------------- cards

export function Card({ children, style, flat }: {
  children: React.ReactNode; style?: StyleProp<ViewStyle>; flat?: boolean;
}) {
  return <View style={[styles.card, !flat && cardShadow, style]}>{children}</View>;
}

export function SectionTitle({ children, action }: {
  children: string; action?: { label: string; onPress: () => void; accessibilityLabel?: string };
}) {
  return (
    <View style={styles.sectionRow}>
      <Text style={styles.sectionTitle} accessibilityRole="header">{children}</Text>
      {action ? (
        <Pressable
          onPress={action.onPress}
          style={styles.sectionAction}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel={action.accessibilityLabel || action.label}
        >
          <Text style={styles.sectionActionText}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** A round icon cell, the size of the wallet marks on Inicio. */
export function IconDisc({ icon, tone = 'mint', size = 44 }: {
  icon: string; tone?: 'mint' | 'deep' | 'neutral' | 'notice'; size?: number;
}) {
  const bg = tone === 'deep' ? SA.deep : tone === 'neutral' ? '#F3F4F6' : tone === 'notice' ? SA.noticeBg : SA.mint;
  const fg = tone === 'deep' ? SA.onDeep : tone === 'neutral' ? SA.muted : tone === 'notice' ? SA.noticeText : SA.deep;
  return (
    <View
      style={[styles.disc, { width: size, height: size, borderRadius: size / 2, backgroundColor: bg }]}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Icon name={icon} size={Math.round(size * 0.45)} color={fg} />
    </View>
  );
}

/**
 * One row, one button. The right side is MY money (the big number); anything
 * about the market or the asset is the small line under the title.
 */
export function Row({
  left, title, subtitle, note, value, valueNote, onPress, chevron, divider, accessibilityLabel, selected, testID,
}: {
  left?: React.ReactNode;
  title: string;
  subtitle?: string;
  /** A third, quieter line (a reason, a status). */
  note?: string;
  value?: string;
  valueNote?: string;
  onPress?: () => void;
  chevron?: boolean;
  divider?: boolean;
  accessibilityLabel?: string;
  selected?: boolean;
  testID?: string;
}) {
  const label = accessibilityLabel
    || [title, subtitle, note, value, valueNote].filter(Boolean).join('. ');
  const body = (
    <>
      {left ? <View style={styles.rowLeft}>{left}</View> : null}
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{title}</Text>
        {subtitle ? <Text style={styles.rowSubtitle}>{subtitle}</Text> : null}
        {note ? <Text style={styles.rowNote}>{note}</Text> : null}
      </View>
      {value || valueNote ? (
        <View style={styles.rowValueBox}>
          {value ? (
            <Text style={styles.rowValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>{value}</Text>
          ) : null}
          {valueNote ? <Text style={styles.rowValueNote}>{valueNote}</Text> : null}
        </View>
      ) : null}
      {selected !== undefined ? (
        <Icon
          name={selected ? 'check-circle' : 'circle'}
          size={22}
          color={selected ? SA.deep : SA.faint}
          style={styles.rowTrailingIcon}
        />
      ) : null}
      {chevron && onPress ? (
        <Icon name="chevron-right" size={20} color={SA.faint} style={styles.rowTrailingIcon} />
      ) : null}
    </>
  );
  if (!onPress) {
    return (
      <View style={[styles.row, divider && styles.rowDivider]} accessible accessibilityLabel={label} testID={testID}>
        {body}
      </View>
    );
  }
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.row, divider && styles.rowDivider, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={selected === undefined ? undefined : { selected }}
      testID={testID}
    >
      {body}
    </Pressable>
  );
}

// --------------------------------------------------------------- actions

export function ActionButton({
  label, onPress, variant = 'primary', busy, disabled, style, accessibilityLabel, icon, testID,
}: {
  label: string;
  onPress: () => void;
  /** primary: the account's deep emerald. quiet: text only. danger: a calm outlined red. */
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger' | 'onDeep';
  busy?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
  icon?: string;
  testID?: string;
}) {
  const inactive = !!busy || !!disabled;
  const v = buttonVariants[variant];
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      style={({ pressed }) => [
        styles.button, v.box, pressed && v.pressed, disabled && styles.buttonDisabled, style,
      ]}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || label}
      accessibilityState={{ disabled: inactive, busy: !!busy }}
      testID={testID}
    >
      {busy ? <ActivityIndicator color={v.fg} /> : (
        <>
          {icon ? <Icon name={icon} size={18} color={v.fg} style={styles.buttonIcon} /> : null}
          <Text style={[styles.buttonText, { color: v.fg }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

const buttonVariants = {
  primary: { box: { backgroundColor: SA.deep }, pressed: { backgroundColor: SA.deepPressed }, fg: SA.onDeep },
  secondary: {
    box: { backgroundColor: SA.card, borderWidth: 1, borderColor: SA.line },
    pressed: { backgroundColor: '#F3F4F6' },
    fg: SA.text,
  },
  quiet: { box: { backgroundColor: 'transparent' }, pressed: { opacity: 0.6 }, fg: SA.muted },
  danger: {
    box: { backgroundColor: SA.card, borderWidth: 1, borderColor: '#FECACA' },
    pressed: { backgroundColor: '#FEF2F2' },
    fg: SA.errorText,
  },
  onDeep: {
    box: { backgroundColor: 'rgba(255,255,255,0.14)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.28)' },
    pressed: { backgroundColor: 'rgba(255,255,255,0.24)' },
    fg: SA.onDeep,
  },
} as const;

// --------------------------------------------------------------- notices

/** One calm block: what is true and, if needed, what to do. Never an alarm. */
export function Notice({ icon = 'info', title, body, tone = 'mint', onPress, actionLabel, style, testID }: {
  icon?: string;
  title?: string;
  body: string;
  tone?: 'mint' | 'notice' | 'neutral';
  onPress?: () => void;
  actionLabel?: string;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  const bg = tone === 'notice' ? SA.noticeBg : tone === 'neutral' ? '#F3F4F6' : SA.mint;
  const border = tone === 'notice' ? SA.noticeLine : tone === 'neutral' ? SA.line : SA.mintLine;
  const fg = tone === 'notice' ? SA.noticeText : tone === 'neutral' ? SA.text : SA.deep;
  const content = (
    <>
      <Icon name={icon} size={18} color={fg} style={styles.noticeIcon} />
      <View style={styles.flexShrink}>
        {title ? <Text style={[styles.noticeTitle, { color: fg }]}>{title}</Text> : null}
        <Text style={[styles.noticeBody, { color: fg }]}>{body}</Text>
        {actionLabel && onPress ? <Text style={[styles.noticeAction, { color: fg }]}>{actionLabel}</Text> : null}
      </View>
      {onPress ? <Icon name="chevron-right" size={18} color={fg} style={styles.rowTrailingIcon} /> : null}
    </>
  );
  const box = [styles.notice, { backgroundColor: bg, borderColor: border }, style];
  if (!onPress) {
    return <View style={box} accessible accessibilityLabel={[title, body].filter(Boolean).join('. ')} testID={testID}>{content}</View>;
  }
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [box, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={[title, body, actionLabel].filter(Boolean).join('. ')}
      testID={testID}
    >
      {content}
    </Pressable>
  );
}

/**
 * An explicit acceptance. The whole row is the checkbox (44pt and up), the
 * text is the sentence being accepted, and `highlight` marks it when the
 * user tried to continue without it.
 */
export function AcceptRow({ checked, onToggle, label, highlight, testID }: {
  checked: boolean; onToggle: () => void; label: string; highlight?: boolean; testID?: string;
}) {
  return (
    <Pressable
      onPress={onToggle}
      style={({ pressed }) => [styles.accept, checked && styles.acceptOn, highlight && !checked && styles.acceptMissing, pressed && styles.pressed]}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={label}
      testID={testID}
    >
      <View style={[styles.checkbox, checked && styles.checkboxOn]}>
        {checked ? <Icon name="check" size={16} color={SA.onDeep} /> : null}
      </View>
      <Text style={styles.acceptText}>{label}</Text>
    </Pressable>
  );
}

/** A numbered list of statements to read before accepting: calm, never fine print. */
export function NumberedList({ items }: { items: string[] }) {
  return (
    <View>
      {items.map((item, i) => (
        <View key={`${i}-${item.slice(0, 12)}`} style={styles.numbered} accessible accessibilityLabel={`${i + 1}. ${item}`}>
          <View style={styles.numberDisc}><Text style={styles.numberText}>{i + 1}</Text></View>
          <Text style={styles.numberedText}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

/** Label on the left, value on the right; wraps to two lines when tight. */
export function Fact({ label, value, divider }: { label: string; value: string; divider?: boolean }) {
  return (
    <View style={[styles.fact, divider && styles.rowDivider]} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text style={styles.factLabel}>{label}</Text>
      <Text style={styles.factValue}>{value}</Text>
    </View>
  );
}

/** A small choice chip (frequency, window, plan). */
export function Chip({ label, selected, onPress, accessibilityLabel }: {
  label: string; selected: boolean; onPress: () => void; accessibilityLabel?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.chip, selected && styles.chipOn, pressed && styles.pressed]}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={accessibilityLabel || label}
      hitSlop={2}
    >
      <Text style={[styles.chipText, selected && styles.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------- states

/** Could not load: one sentence and an inline retry. Nothing is implied about the money. */
export function LoadError({ onRetry, message, busy }: { onRetry: () => void; message?: string; busy?: boolean }) {
  return (
    <View style={styles.stateBox} accessibilityLiveRegion="polite">
      <IconDisc icon="wifi-off" tone="neutral" size={56} />
      <Text style={styles.stateTitle}>No pudimos cargar esto</Text>
      <Text style={styles.stateBody}>{message || 'Tu dinero no cambió. Revisa tu conexión e inténtalo de nuevo.'}</Text>
      <ActionButton label="Reintentar" onPress={onRetry} busy={busy} variant="secondary" style={styles.stateButton} />
    </View>
  );
}

export function Empty({ icon, title, body, actionLabel, onAction }: {
  icon: string; title: string; body?: string; actionLabel?: string; onAction?: () => void;
}) {
  return (
    <View style={styles.stateBox}>
      <IconDisc icon={icon} tone="mint" size={56} />
      <Text style={styles.stateTitle}>{title}</Text>
      {body ? <Text style={styles.stateBody}>{body}</Text> : null}
      {actionLabel && onAction ? (
        <ActionButton label={actionLabel} onPress={onAction} style={styles.stateButton} />
      ) : null}
    </View>
  );
}

/** Row-shaped placeholders in the app's shimmer style. */
export function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <View accessibilityLabel="Cargando" accessible testID="smart-skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <View key={i} style={styles.skeletonRow}>
          <SkeletonLoader width={44} height={44} borderRadius={22} />
          <View style={styles.skeletonText}>
            <SkeletonLoader width={140} height={16} borderRadius={8} />
            <SkeletonLoader width={96} height={12} borderRadius={6} style={styles.skeletonGap} />
          </View>
          <SkeletonLoader width={72} height={18} borderRadius={9} />
        </View>
      ))}
    </View>
  );
}

export function ScreenSkeleton() {
  return (
    <View style={styles.pad}>
      <Card><RowsSkeleton rows={2} /></Card>
      <Card style={styles.cardGap}><RowsSkeleton rows={3} /></Card>
    </View>
  );
}

export const kitStyles = StyleSheet.create({
  pad: { paddingHorizontal: 16, paddingTop: 16 },
  gap: { marginTop: 12 },
  gapLarge: { marginTop: 24 },
  lead: { fontSize: 16, lineHeight: 23, color: SA.text },
  body: { fontSize: 15, lineHeight: 22, color: SA.muted },
  small: { fontSize: 13, lineHeight: 19, color: SA.muted },
  errorText: { fontSize: 14, lineHeight: 20, color: SA.errorText, marginBottom: 8, textAlign: 'center' },
  center: { textAlign: 'center' },
});

const styles = StyleSheet.create({
  flex: { flex: 1 },
  flexShrink: { flex: 1, flexShrink: 1 },
  screen: { flex: 1, backgroundColor: SA.page },
  scrollContent: { paddingBottom: 32 },
  pad: { paddingHorizontal: 16, paddingTop: 16 },
  pressed: { opacity: 0.7 },
  headerRight: { flexDirection: 'row', alignItems: 'center' },
  helpButton: { width: HIT, height: HIT, alignItems: 'center', justifyContent: 'center' },
  avatar: {
    width: 36, height: 36, borderRadius: 18, backgroundColor: SA.card,
    alignItems: 'center', justifyContent: 'center', marginLeft: 4,
  },
  avatarText: { fontSize: 16, fontWeight: '700', color: SA.deep },
  footer: {
    paddingHorizontal: 16, paddingTop: 12, backgroundColor: SA.card,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line,
  },
  card: { backgroundColor: SA.card, borderRadius: 20, paddingHorizontal: 16 },
  cardGap: { marginTop: 16 },
  sectionRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap',
    marginTop: 28, marginBottom: 12, paddingHorizontal: 4,
  },
  sectionTitle: { fontSize: 20, fontWeight: '700', color: SA.text, flexShrink: 1 },
  sectionAction: { minHeight: HIT, justifyContent: 'center', paddingLeft: 12 },
  sectionActionText: { fontSize: 15, fontWeight: '600', color: SA.mintText },
  disc: { alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', minHeight: 64, paddingVertical: 12 },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: SA.line },
  rowLeft: { marginRight: 14 },
  rowText: { flex: 1, flexShrink: 1 },
  rowTitle: { fontSize: 16, fontWeight: '600', color: SA.text },
  rowSubtitle: { fontSize: 14, color: SA.muted, marginTop: 2, lineHeight: 19 },
  rowNote: { fontSize: 13, color: SA.muted, marginTop: 4, lineHeight: 18 },
  rowValueBox: { alignItems: 'flex-end', marginLeft: 12, maxWidth: '46%' },
  rowValue: { fontSize: 17, fontWeight: '700', color: SA.text },
  rowValueNote: { fontSize: 13, color: SA.muted, marginTop: 2, textAlign: 'right' },
  rowTrailingIcon: { marginLeft: 8 },
  button: {
    minHeight: 54, borderRadius: 16, paddingHorizontal: 18, paddingVertical: 12,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
  },
  buttonDisabled: { opacity: 0.45 },
  buttonIcon: { marginRight: 8 },
  buttonText: { fontSize: 17, fontWeight: '700', textAlign: 'center', flexShrink: 1 },
  notice: {
    flexDirection: 'row', alignItems: 'flex-start', borderRadius: 16, borderWidth: 1, padding: 14,
  },
  noticeIcon: { marginRight: 10, marginTop: 1 },
  noticeTitle: { fontSize: 15, fontWeight: '700', marginBottom: 2 },
  noticeBody: { fontSize: 14, lineHeight: 20 },
  noticeAction: { fontSize: 14, fontWeight: '700', marginTop: 6 },
  accept: {
    flexDirection: 'row', alignItems: 'center', minHeight: 56, borderRadius: 16, borderWidth: 1.5,
    borderColor: SA.line, backgroundColor: SA.card, paddingHorizontal: 14, paddingVertical: 12,
  },
  acceptOn: { borderColor: SA.deep, backgroundColor: SA.mint },
  acceptMissing: { borderColor: SA.noticeText, backgroundColor: SA.noticeBg },
  checkbox: {
    width: 24, height: 24, borderRadius: 7, borderWidth: 2, borderColor: SA.faint,
    alignItems: 'center', justifyContent: 'center', marginRight: 12, backgroundColor: SA.card,
  },
  checkboxOn: { backgroundColor: SA.deep, borderColor: SA.deep },
  acceptText: { flex: 1, fontSize: 15, lineHeight: 21, fontWeight: '600', color: SA.text },
  numbered: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 10 },
  numberDisc: {
    width: 24, height: 24, borderRadius: 12, backgroundColor: SA.mint,
    alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1,
  },
  numberText: { fontSize: 13, fontWeight: '700', color: SA.deep },
  numberedText: { flex: 1, fontSize: 15, lineHeight: 22, color: SA.text },
  fact: {
    flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between',
    paddingVertical: 14,
  },
  factLabel: { fontSize: 15, color: SA.muted, marginRight: 12 },
  factValue: { fontSize: 15, fontWeight: '600', color: SA.text, flexShrink: 1, textAlign: 'right' },
  chip: {
    minHeight: HIT, paddingHorizontal: 16, borderRadius: 22, borderWidth: 1, borderColor: SA.line,
    backgroundColor: SA.card, alignItems: 'center', justifyContent: 'center', marginRight: 8, marginBottom: 8,
  },
  chipOn: { backgroundColor: SA.deep, borderColor: SA.deep },
  chipText: { fontSize: 15, fontWeight: '600', color: SA.text },
  chipTextOn: { color: SA.onDeep },
  stateBox: { alignItems: 'center', paddingHorizontal: 32, paddingVertical: 48 },
  stateTitle: { fontSize: 18, fontWeight: '700', color: SA.text, marginTop: 16, textAlign: 'center' },
  stateBody: { fontSize: 15, lineHeight: 22, color: SA.muted, marginTop: 6, textAlign: 'center' },
  stateButton: { marginTop: 20, alignSelf: 'stretch' },
  skeletonRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14 },
  skeletonText: { flex: 1, marginLeft: 14 },
  skeletonGap: { marginTop: 8 },
  sheetRoot: { flex: 1, justifyContent: 'flex-end' },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    backgroundColor: SA.card, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingTop: 10, maxHeight: '88%',
  },
  sheetHandle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: SA.line, marginBottom: 8 },
  sheetContent: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 8 },
  sheetTitle: { fontSize: 20, fontWeight: '700', color: SA.text, marginBottom: 12 },
  sheetButton: { marginTop: 16 },
  helpParagraph: { fontSize: 15, lineHeight: 23, color: SA.text, marginBottom: 12 },
});
