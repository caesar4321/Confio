import React, { useEffect } from 'react';
import { ActivityIndicator, BackHandler, Image, Pressable, StyleSheet, View, ViewStyle } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../common/AppText';
import { Header } from '../../navigation/Header';
import { colors } from '../../config/theme';

/**
 * The shared look of the Comprar screens: one frame, one card, one button,
 * one status vocabulary, so every screen of the flow reads as the same place.
 */

/**
 * Screen frame. The shared Header applies the top safe-area inset itself;
 * wrapping it in another top-edge SafeAreaView (as these screens used to)
 * paid the inset twice and pushed every title down.
 */
export const ComprarFrame = ({ title, children, rightAccessory, background = colors.neutral, blocking }: {
  title: string; children: React.ReactNode; rightAccessory?: React.ReactNode; background?: string;
  /** While set, the whole screen (header included) is blocked with this message. */
  blocking?: string | null;
}) => {
  const navigation = useNavigation<any>();
  // No leaving mid-payment: swipe-back and Android back wait for the result.
  useEffect(() => {
    navigation.setOptions?.({ gestureEnabled: !blocking });
    if (!blocking) return undefined;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, [blocking, navigation]);
  return (
    <View style={[styles.frame, { backgroundColor: background }]}>
      <Header navigation={navigation} isHomeScreen={false} title={title} backgroundColor="#fff"
        showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U"
        rightAccessory={rightAccessory} />
      {children}
      {blocking ? <BlockingLayer message={blocking} /> : null}
    </View>
  );
};

/**
 * In-screen blocking layer, deliberately not a native Modal: Confío Face and
 * system alerts present their own modals mid-payment, and presenting one while
 * another native modal is still animating away can leave it unshown on iOS.
 * A plain view needs no dismissal handshake: hiding it is instant.
 */
const BlockingLayer = ({ message }: { message: string }) => (
  <View style={styles.blocking} testID="comprar-blocking" accessibilityViewIsModal>
    <View style={styles.blockingCard}>
      <ActivityIndicator size="large" color={colors.primaryDark} />
      <Text style={styles.blockingTitle}>{message}</Text>
      <Text style={styles.blockingHint}>Por favor no cierres la aplicación</Text>
    </View>
  </View>
);

/** A white card; with `icon` + `title` it gets the section heading. */
export const KitCard = ({ icon, title, right, children, style }: {
  icon?: string; title?: string; right?: React.ReactNode; children?: React.ReactNode; style?: ViewStyle;
}) => (
  <View style={[styles.card, style]}>
    {title ? (
      <View style={styles.cardHead}>
        {icon ? <View style={styles.cardIcon}><Icon name={icon} size={15} color={colors.primaryDeep} /></View> : null}
        <Text style={styles.cardTitle}>{title}</Text>
        {right ? <View style={styles.cardRight}>{right}</View> : null}
      </View>
    ) : null}
    {children}
  </View>
);

/** Label on the left, value on the right; `strong` for a total. */
export const KitRow = ({ label, value, strong, muted }: {
  label: string; value: React.ReactNode; strong?: boolean; muted?: boolean;
}) => (
  <View style={styles.row}>
    <Text style={[styles.rowLabel, muted && styles.mutedText, strong && styles.rowStrongLabel]}>{label}</Text>
    {typeof value === 'string'
      ? <Text style={[styles.rowValue, muted && styles.mutedText, strong && styles.rowStrongValue]}>{value}</Text>
      : value}
  </View>
);

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

export const KitButton = ({ label, onPress, variant = 'primary', disabled, loading, icon, testID }: {
  label: string; onPress: () => void; variant?: ButtonVariant; disabled?: boolean; loading?: boolean;
  icon?: string; testID?: string;
}) => {
  const tone = BUTTON[variant];
  const off = disabled || loading;
  return (
    <Pressable testID={testID} disabled={off} onPress={onPress} accessibilityRole="button"
      accessibilityState={{ disabled: !!off }}
      style={({ pressed }) => [styles.button, tone.box, off && variant !== 'ghost' && styles.buttonOff,
        pressed && !off && styles.buttonPressed]}>
      {loading ? <ActivityIndicator color={tone.text} /> : (
        <View style={styles.buttonInner}>
          {icon ? <Icon name={icon} size={17} color={off && variant !== 'ghost' ? colors.white : tone.text} /> : null}
          <Text style={[styles.buttonText, { color: off && variant !== 'ghost' ? colors.white : tone.text }]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
};

const BUTTON: Record<ButtonVariant, { box: ViewStyle; text: string }> = {
  primary: { box: { backgroundColor: colors.primaryDark }, text: colors.white },
  secondary: { box: { backgroundColor: colors.white, borderWidth: 1, borderColor: colors.border }, text: colors.text.primary },
  danger: { box: { backgroundColor: colors.error.icon }, text: colors.white },
  ghost: { box: { backgroundColor: 'transparent', paddingVertical: 10 }, text: colors.text.secondary },
};

/** Bottom bar that sits above the home indicator. */
export const KitFooter = ({ children }: { children: React.ReactNode }) => {
  const insets = useSafeAreaInsets();
  return <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, 12) + 4 }]}>{children}</View>;
};

// ── order status ────────────────────────────────────────────────────────

type Tone = 'wait' | 'move' | 'done' | 'alert' | 'off';
const TONES: Record<Tone, { bg: string; fg: string }> = {
  wait: { bg: colors.warning.background, fg: colors.warning.text },
  move: { bg: colors.infoLight, fg: '#1D4ED8' },
  done: { bg: colors.primaryLight, fg: colors.primaryDeep },
  alert: { bg: colors.error.background, fg: colors.error.text },
  off: { bg: colors.neutralDark, fg: colors.text.secondary },
};
const STATUS_TONE: Record<string, Tone> = {
  draft: 'off', depositing: 'wait', funded: 'wait', shipped: 'move',
  disputed: 'alert', released: 'done', refunded: 'off', cancelled: 'off',
};

export const StatusPill = ({ status, label }: { status: string; label: string }) => {
  const tone = TONES[STATUS_TONE[status] || 'off'];
  return (
    <View style={[styles.pill, { backgroundColor: tone.bg }]}>
      <View style={[styles.pillDot, { backgroundColor: tone.fg }]} />
      <Text style={[styles.pillText, { color: tone.fg }]} numberOfLines={1}>{label}</Text>
    </View>
  );
};

const STEPS = ['Pagado', 'Enviado', 'Recibido'];
/** How far along the happy path an order is; null off it (disputes, refunds). */
const stepIndex = (status: string): number | null => (
  ({ depositing: 0, funded: 1, shipped: 2, released: 3 } as Record<string, number>)[status] ?? null
);

/** Pagado → Enviado → Recibido, the one picture of where an order is. */
export const OrderProgress = ({ status }: { status: string }) => {
  const at = stepIndex(status);
  if (at === null) return null;
  return (
    <View style={styles.progress} accessibilityLabel={`Progreso: ${STEPS.slice(0, at).join(', ') || 'pagando'}`}>
      {STEPS.map((label, i) => {
        const done = i < at;
        const current = i === at;
        return (
          <React.Fragment key={label}>
            {i > 0 ? <View style={[styles.progressBar, done && styles.progressBarOn]} /> : null}
            <View style={styles.progressStep}>
              <View style={[styles.progressDot, done && styles.progressDotOn, current && styles.progressDotNow]}>
                {done ? <Icon name="check" size={12} color={colors.white} /> : null}
              </View>
              <Text style={[styles.progressLabel, (done || current) && styles.progressLabelOn]}>{label}</Text>
            </View>
          </React.Fragment>
        );
      })}
    </View>
  );
};

export const ProductThumb = ({ uri, size = 56 }: { uri?: string | null; size?: number }) => (
  uri ? <Image source={{ uri }} style={[styles.thumb, { width: size, height: size }]} />
    : (
      <View style={[styles.thumb, styles.thumbEmpty, { width: size, height: size }]}>
        <Icon name="package" size={Math.round(size / 3)} color={colors.text.light} />
      </View>
    )
);

/** Adults-only (alcohol): one notice, worded for whoever reads it. */
export const AdultsOnlyNote = ({ minimumAge, audience }: {
  minimumAge: number;
  audience: 'buyer' | 'seller' | 'listing';
}) => {
  const text = audience === 'seller'
    ? `Solo para mayores de ${minimumAge}: entrégalo únicamente a un adulto que muestre su carnet.`
    : audience === 'listing'
      ? `Esta categoría es solo para mayores de ${minimumAge}: solo podrán comprar adultos con su identidad verificada. Vende bebidas selladas y con etiqueta.`
      : `Solo para mayores de ${minimumAge}. Quien lo reciba debe ser adulto y puede tener que mostrar su carnet.`;
  return (
    <View style={styles.adults} testID="adults-only-note">
      <View style={styles.adultsBadge}><Text style={styles.adultsBadgeText}>+{minimumAge}</Text></View>
      <Text style={styles.adultsText}>{text}</Text>
    </View>
  );
};

/** The protected-payment promise, said the same way everywhere. */
export const TrustNote = ({ children }: { children: React.ReactNode }) => (
  <View style={styles.trust}>
    <Icon name="shield" size={16} color={colors.primaryDeep} />
    <Text style={styles.trustText}>{children}</Text>
  </View>
);

export const kitText = StyleSheet.create({
  body: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
  muted: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  error: { fontSize: 14, color: colors.error.text, textAlign: 'center' },
  link: { fontSize: 14, color: colors.primaryDeep, fontWeight: '600' },
});

const styles = StyleSheet.create({
  frame: { flex: 1 },
  blocking: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center', zIndex: 10, elevation: 10 },
  blockingCard: { backgroundColor: colors.white, borderRadius: 16, padding: 28, alignItems: 'center', width: '80%', maxWidth: 320, gap: 10 },
  blockingTitle: { fontSize: 17, fontWeight: '700', color: colors.textFlat, textAlign: 'center', marginTop: 6 },
  blockingHint: { fontSize: 13, color: colors.text.secondary, textAlign: 'center' },
  card: {
    backgroundColor: colors.white, borderRadius: 16, padding: 16, gap: 10,
    borderWidth: 1, borderColor: colors.borderLight,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  cardIcon: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat, flex: 1 },
  cardRight: { marginLeft: 'auto' },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  rowLabel: { fontSize: 14, color: colors.text.primary, flexShrink: 1 },
  rowValue: { fontSize: 14, fontWeight: '600', color: colors.textFlat },
  rowStrongLabel: { fontSize: 16, fontWeight: '700', color: colors.textFlat },
  rowStrongValue: { fontSize: 18, fontWeight: '700', color: colors.textFlat },
  mutedText: { color: colors.text.secondary, fontWeight: '400', fontSize: 13 },
  button: { borderRadius: 14, paddingVertical: 15, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  buttonInner: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  buttonText: { fontSize: 16, fontWeight: '700' },
  buttonOff: { backgroundColor: '#D1D5DB', borderColor: '#D1D5DB' },
  buttonPressed: { opacity: 0.85 },
  footer: {
    paddingHorizontal: 16, paddingTop: 12, backgroundColor: colors.white,
    borderTopWidth: 1, borderTopColor: colors.borderLight, gap: 8,
  },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, maxWidth: '100%' },
  pillDot: { width: 6, height: 6, borderRadius: 3 },
  pillText: { fontSize: 12, fontWeight: '700' },
  progress: { flexDirection: 'row', alignItems: 'flex-start', paddingTop: 4 },
  progressStep: { alignItems: 'center', gap: 6, width: 64 },
  progressDot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.border, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  progressDotOn: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  progressDotNow: { borderColor: colors.primaryDark },
  progressBar: { flex: 1, height: 2, backgroundColor: colors.border, marginTop: 10 },
  progressBarOn: { backgroundColor: colors.primaryDark },
  progressLabel: { fontSize: 12, color: colors.text.light },
  progressLabelOn: { color: colors.textFlat, fontWeight: '600' },
  thumb: { borderRadius: 12, backgroundColor: colors.neutralDark },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  trust: { flexDirection: 'row', gap: 10, padding: 14, borderRadius: 14, backgroundColor: colors.primaryLight, alignItems: 'flex-start' },
  trustText: { flex: 1, fontSize: 13, color: colors.primaryDeep, lineHeight: 19 },
  adults: { flexDirection: 'row', gap: 10, padding: 14, borderRadius: 14, backgroundColor: colors.warning.background, alignItems: 'center' },
  adultsBadge: { minWidth: 34, height: 24, paddingHorizontal: 6, borderRadius: 12, backgroundColor: colors.warning.text, alignItems: 'center', justifyContent: 'center' },
  adultsBadgeText: { fontSize: 12, fontWeight: '700', color: colors.white },
  adultsText: { flex: 1, fontSize: 13, color: colors.warning.text, lineHeight: 19 },
});
