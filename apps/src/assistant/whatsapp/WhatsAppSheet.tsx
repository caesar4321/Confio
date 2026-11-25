// The person's own WhatsApp: consent, the pairing code, what matters, and replies they approve one by one.
// Every message leaves only from "Enviar" on a card that shows the exact text and where it goes.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, Animated, Image, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, View,
} from 'react-native';
import { useApolloClient, type DocumentNode } from '@apollo/client';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';

import WhatsAppLogo from '../../assets/svg/WhatsApp.svg';

import { Text, TextInput } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { ACCEPT_WHATSAPP_CONSENT, REFRESH_WHATSAPP, START_WHATSAPP_LINK, UNLINK_WHATSAPP, WHATSAPP_CONSENT_VERSION } from './api';
import {
  CONSENT_DATA, CONSENT_POINTS, PAIRING_STEPS, checkedAgo, codeForCopy, consentText, validPhone,
} from './rules';
import { forgetWhatsAppSession } from './session';
import { useWhatsApp } from './useWhatsApp';
import { CountryFlag } from '../../components/CountryFlag';
import { RampCountryPicker } from '../../components/ramps/RampCountryPicker';
import { internationalPhone, splitPhone } from '../../components/ramps/RampPhoneField';
import type { Country } from '../../utils/countries';

const CONFIO_ICON = require('../../assets/png/AppStoreIcon.png');
const FAILED = 'No pude completar eso con tu WhatsApp. Inténtalo de nuevo.';

type Props = { userId: string; onClose: () => void };

export default function WhatsAppSheet({ userId, onClose }: Props) {
  const client = useApolloClient();
  const { link, refetch } = useWhatsApp(userId, 'network-only', true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  // Typed by the person (sign-up proves no phone): a country, then the number. The last linked number (or the
  // account's) only fills it in to start with.
  const suggested = link?.suggestedPhone ?? '';
  const start = useMemo(() => (suggested ? splitPhone(suggested) : { country: undefined, number: '' }), [suggested]);
  const [typed, setTyped] = useState<{ country?: Country; number: string } | null>(null);
  const [picking, setPicking] = useState(false);
  const country = (typed ?? start).country;
  const number = (typed ?? start).number;
  const shownPhone = internationalPhone(country, number);
  const typeNumber = (value: string) => {
    // A pasted or autofilled "+58 414…" carries its own country: the chip follows it.
    setTyped(value.trim().startsWith('+') && value.replace(/\D/g, '').length > 6
      ? splitPhone(`+${value.replace(/\D/g, '')}`, country ? String(country[2]) : null)
      : { country, number: value });
  };
  const open = useRef(true);
  useEffect(() => () => {
    open.current = false;
  }, []);

  const run = useCallback(async (mutation: DocumentNode, field: string, variables?: Record<string, unknown>,
    onRefused?: (code: string) => void, timeoutMs?: number) => {
    setBusy(true);
    setMessage(null);
    // A mutation has no timeout of its own on the phone: one that must settle is given up on after timeoutMs.
    const abort = timeoutMs ? new AbortController() : null;
    const timer = abort ? setTimeout(() => abort.abort(), timeoutMs) : null;
    try {
      const { data } = await client.mutate<any>({
        mutation, variables, fetchPolicy: 'no-cache', context: abort ? { fetchOptions: { signal: abort.signal } } : undefined,
      });
      const result = data?.[field];
      if (result && !result.success && result.errorCode !== 'busy') {
        onRefused?.(String(result.errorCode || ''));  // a real answer, not "already on its way"
      }
      if (!result?.success && open.current) {
        setMessage(result?.error || FAILED);
      }
      return result?.success ? result : null;
    } catch {
      if (open.current) {
        setMessage(FAILED);
      }
      return null;
    } finally {
      if (timer) {
        clearTimeout(timer);
      }
      if (open.current) {
        setBusy(false);
      }
      refetch().catch(() => undefined);
    }
  }, [client, refetch]);

  // Opening asks for a fresh read of the chat list (the server decides if it is due).
  const linked = link?.state === 'linked';
  useEffect(() => {
    if (linked) {
      client.mutate({ mutation: REFRESH_WHATSAPP, fetchPolicy: 'no-cache' }).catch(() => undefined);
    }
  }, [linked, client]);

  const unlinkNow = async () => {
    if (await run(UNLINK_WHATSAPP, 'unlinkWhatsApp')) {
      forgetWhatsAppSession(userId);  // nothing of this WhatsApp is carried into a next one
    }
  };
  const startLink = () => void run(START_WHATSAPP_LINK, 'startWhatsAppLink', {
    phone: shownPhone, consentVersion: WHATSAPP_CONSENT_VERSION,
    // The picked country tells +1 countries apart: the server routes the link through that country.
    country: country ? String(country[2]) : null,
  });
  const unlink = () => {
    Alert.alert(
      '¿Desvincular tu WhatsApp?',
      'Cerramos la sesión de Confío en tu WhatsApp y borramos lo que guardamos de él.',
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Desvincular', style: 'destructive', onPress: () => void unlinkNow() },
      ],
    );
  };
  const outdatedApp = !!link && link.consentVersion > WHATSAPP_CONSENT_VERSION;
  // The number is asked only to link (not while reviewing a change of what we do).
  const linking = !!link && link.state !== 'pairing' && link.state !== 'linked';
  const phoneReady = validPhone(shownPhone);

  // What anyone reads before linking: three points and what is read, then the number.
  const consent = () => (outdatedApp ? (
    <Text style={styles.text}>Actualiza la app para ver lo que cambió y seguir usando WhatsApp en Confío.</Text>
  ) : (
    <>
      <View style={styles.list}>
        {CONSENT_POINTS.map((point, index) => (
          <View key={point.text} style={[styles.listRow, index > 0 && styles.listDivider]}>
            <View style={styles.tile}>
              <Icon name={point.icon} size={18} color={colors.successText} />
            </View>
            <Text style={styles.listText}>{point.text}</Text>
          </View>
        ))}
      </View>
      {linking ? (
        <View style={styles.field}>
          <Text style={styles.fieldLabel}>Tu número de WhatsApp</Text>
          <View style={styles.phoneRow}>
            <Pressable
              style={[styles.countryChip, !country && styles.countryChipEmpty]}
              onPress={() => setPicking(true)}
              accessibilityRole="button"
              accessibilityLabel={country ? `País ${country[0]}, código ${country[1]}. Cambiar` : 'Elegir país'}
            >
              {country ? <CountryFlag iso={String(country[2])} size={22} /> : <Icon name="globe" size={18} color={colors.successText} />}
              <Text style={styles.countryCode}>{country ? String(country[1]) : 'País'}</Text>
              <Icon name="chevron-down" size={14} color={colors.successText} />
            </Pressable>
            <View style={[styles.phoneBox, phoneReady && styles.phoneBoxReady]}>
              <TextInput
                style={styles.phone}
                value={number}
                onChangeText={typeNumber}
                placeholder="Número"
                placeholderTextColor={colors.muted}
                keyboardType="phone-pad"
                autoComplete="tel"
                textContentType="telephoneNumber"
                maxLength={18}
                accessibilityLabel="Tu número de WhatsApp, con el código de país"
              />
              {phoneReady ? <Icon name="check-circle" size={20} color={colors.successText} /> : null}
            </View>
          </View>
          <Text style={styles.hint}>
            {!country ? 'Elige el país de tu número de WhatsApp.' : phoneReady ? `Vincularemos ${shownPhone}` : 'El número sin el código de país.'}
          </Text>
          <RampCountryPicker
            visible={picking}
            selected={country ? String(country[2]) : null}
            title="País de tu WhatsApp"
            showCallingCode
            onPick={(picked) => setTyped({ country: picked, number })}
            onClose={() => setPicking(false)}
          />
        </View>
      ) : null}
      <View style={styles.notes}>
        <View style={styles.note}>
          <Icon name="lock" size={15} color={colors.gray600} />
          <Text style={styles.noteText}>{CONSENT_DATA}</Text>
        </View>
      </View>
      <Pressable
        style={styles.more}
        onPress={() => setDetails(!details)}
        accessibilityRole="button"
        accessibilityState={{ expanded: details }}
      >
        <Text style={styles.moreText}>{details ? 'Ocultar detalles' : 'Cómo funciona'}</Text>
        <Icon name={details ? 'chevron-up' : 'chevron-down'} size={16} color={colors.successText} />
      </Pressable>
      {details ? (
        <View style={styles.details}>
          {consentText().map((line, index) => (
            <View key={line} style={styles.detailRow}>
              <Text style={styles.detailNumber}>{index + 1}</Text>
              <Text style={styles.detail}>{line}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </>
  ));

  let hero: Hero = { title: 'WhatsApp', chip: null };
  let content: React.ReactNode = <ActivityIndicator color={colors.successText} style={styles.loading} />;
  let footer: React.ReactNode = null;
  if (link) {
    if (link.state === 'pairing') {
      const code = link.code;
      hero = { title: code ? 'Escribe el código en WhatsApp' : 'Pidiendo tu código', chip: 'Paso 2 de 2' };
      content = code ? (
        <>
          <View style={styles.codeCard}>
            <Text style={styles.codeLabel}>Tu código</Text>
            <View
              style={styles.cells}
              accessible
              accessibilityLabel={`Código ${codeForCopy(code).split('').join(' ')}`}
            >
              {codeForCopy(code).split('').map((char, index) => (
                <React.Fragment key={`${index}-${char}`}>
                  {index === 4 ? <Text style={styles.dash}>-</Text> : null}
                  <View style={styles.cell}><Text style={styles.cellText} maxFontSizeMultiplier={1.3}>{char}</Text></View>
                </React.Fragment>
              ))}
            </View>
            <View style={styles.row}>
              <Pill
                label={copied === code ? 'Copiado' : 'Copiar código'}
                icon={copied === code ? 'check' : 'copy'}
                filled
                onPress={() => {
                  Clipboard.setString(codeForCopy(code));
                  setCopied(code);  // a new code shows "Copiar código" again
                }}
              />
              <Pill label="Abrir WhatsApp" logo onPress={() => void Linking.openURL('whatsapp://').catch(() => undefined)} />
            </View>
          </View>
          <View style={styles.timeline}>
            {PAIRING_STEPS.map((step, index) => (
              <View key={step} style={styles.timelineRow}>
                <View style={styles.timelineRail}>
                  <View style={styles.stepNumber}><Text style={styles.stepNumberText}>{index + 1}</Text></View>
                  {index < PAIRING_STEPS.length - 1 ? <View style={styles.railLine} /> : null}
                </View>
                <Text style={styles.stepText}>{step}</Text>
              </View>
            ))}
          </View>
          <View style={styles.waiting}>
            <Pulse />
            <Text style={styles.waitingText}>Esperando que lo escribas. El código se renueva solo.</Text>
          </View>
        </>
      ) : (
        <View style={styles.preparing}>
          <ActivityIndicator size="large" color={colors.successText} />
          <Text style={styles.emptyTitle}>Abriendo WhatsApp para ti</Text>
          <Text style={styles.text}>Tarda unos 30 segundos.</Text>
        </View>
      );
      footer = <Secondary label="Cancelar" onPress={() => void unlinkNow()} disabled={busy} />;
    } else if (link.state === 'linked' && link.consentOutdated) {
      hero = { title: 'Revisa lo que cambió', chip: 'En pausa' };
      content = consent();
      footer = outdatedApp ? null : (
        <Action label="Aceptar y seguir" onPress={() => void run(ACCEPT_WHATSAPP_CONSENT, 'acceptWhatsAppConsent', {
          consentVersion: WHATSAPP_CONSENT_VERSION,
        })} disabled={busy} />
      );
    } else if (link.state === 'linked') {
      const checked = checkedAgo(link.lastSyncAt, Date.now());
      hero = { title: 'WhatsApp vinculado', chip: link.phoneHint ? `Activo · terminado en ${link.phoneHint}` : 'Activo', live: true };
      // What arrives is told in the Confío IA conversation, and answered there (whatsapp_link/chat.py): this screen
      // only manages the link.
      content = (
        <>
          <View style={styles.list}>
            {LINKED_POINTS.map((point, index) => (
              <View key={point.text} style={[styles.listRow, index > 0 && styles.listDivider]}>
                <View style={styles.tile}>
                  <Icon name={point.icon} size={18} color={colors.successText} />
                </View>
                <Text style={styles.listText}>{point.text}</Text>
              </View>
            ))}
          </View>
          {checked ? <Text style={styles.checked}>{checked}</Text> : null}
          <Pressable style={styles.unlink} onPress={unlink} disabled={busy} accessibilityRole="button" accessibilityLabel="Desvincular WhatsApp">
            <Icon name="link-2" size={15} color={colors.error.icon} />
            <Text style={styles.unlinkText}>Desvincular WhatsApp</Text>
          </Pressable>
        </>
      );
      footer = <Action label="Ir a mi conversación" onPress={onClose} />;
    } else {
      const again = link.state !== 'none';
      hero = {
        title: link.state === 'gone' ? 'Vincúlalo otra vez' : 'Tu WhatsApp, en Confío',
        chip: 'Paso 1 de 2',
      };
      content = (
        <>
          {link.reasonMessage ? (
            <View style={styles.alert}>
              <Icon name="alert-circle" size={16} color={colors.error.icon} />
              <Text style={styles.alertText}>{link.reasonMessage}</Text>
            </View>
          ) : null}
          {consent()}
        </>
      );
      footer = outdatedApp ? null : (
        <>
          <Action
            label={again ? 'Vincular otra vez' : 'Vincular WhatsApp'}
            onPress={startLink}
            disabled={busy || !phoneReady}
          />
          <Text style={styles.fine}>Al vincular aceptas cómo funciona. Lo desvinculas cuando quieras.</Text>
        </>
      );
    }
  }

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaProvider>
        <View style={styles.screen}>
          <BrandField hero={hero} onClose={onClose} />
          <KeyboardAvoidingView style={styles.sheet} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            {/* flex: 1 so it shrinks to what the pinned footer leaves, and scrolls: without it, it grew to its
                content and pushed the footer and the rest off the bottom (seen on device). */}
            <ScrollView
              style={styles.flex}
              contentContainerStyle={styles.content}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator
            >
              {content}
              {message ? (
                <View style={styles.alert} accessibilityLiveRegion="polite">
                  <Icon name="alert-circle" size={16} color={colors.error.icon} />
                  <Text style={styles.alertText}>{message}</Text>
                </View>
              ) : null}
            </ScrollView>
            {footer ? (
              <SafeAreaView edges={['bottom']} style={styles.footer}>{footer}</SafeAreaView>
            ) : null}
          </KeyboardAvoidingView>
        </View>
      </SafeAreaProvider>
    </Modal>
  );
}

type Hero = { title: string; chip: string | null; live?: boolean };

/** The brand field every Confío setup screen opens with: Confío and WhatsApp, linked. */
function BrandField({ hero, onClose }: { hero: Hero; onClose: () => void }) {
  return (
    <View style={styles.brandField}>
      <Svg style={StyleSheet.absoluteFill}>
        <Defs>
          <SvgLinearGradient id="waField" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={colors.heroField} />
            <Stop offset="1" stopColor={colors.heroFieldDark} />
          </SvgLinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#waField)" />
        <Circle cx="92%" cy="6%" r="120" stroke={colors.white} strokeWidth="28" strokeOpacity="0.10" fill="none" />
        <Circle cx="4%" cy="96%" r="70" stroke={colors.white} strokeWidth="18" strokeOpacity="0.08" fill="none" />
      </Svg>
      <SafeAreaView edges={['top']}>
        {/* Absolute children sit against the padding box: inside this plain view, below the notch. */}
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
              <View style={styles.logoTile}>
                <WhatsAppLogo width={36} height={36} />
              </View>
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

/** A soft beat next to "esperando": the screen is alive while the person is in WhatsApp. */
function Pulse() {
  const scale = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(scale, { toValue: 1, duration: 1400, useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [scale]);
  return (
    <View style={styles.pulse}>
      <Animated.View
        style={[styles.pulseRing, {
          opacity: scale.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] }),
          transform: [{ scale: scale.interpolate({ inputRange: [0, 1], outputRange: [1, 2.4] }) }],
        }]}
      />
      <View style={styles.pulseDot} />
    </View>
  );
}

function Action({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable
      style={({ pressed }) => [styles.button, pressed && styles.pressed, disabled && styles.disabled]}
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

function Pill({ label, icon, logo = false, filled = false, onPress, disabled = false, a11y }: {
  label: string; icon?: string; logo?: boolean; filled?: boolean; onPress: () => void; disabled?: boolean; a11y?: string;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.pill, filled && styles.pillFilled, pressed && styles.pressed, disabled && styles.disabled]}
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11y ?? label}
      accessibilityState={{ disabled }}
    >
      {logo ? <WhatsAppLogo width={18} height={18} /> : null}
      {icon ? <Icon name={icon} size={16} color={filled ? colors.white : colors.primaryDeep} /> : null}
      <Text style={[styles.pillText, filled && styles.pillTextFilled]}>{label}</Text>
    </Pressable>
  );
}

function Secondary({ label, onPress, disabled = false, a11y }: {
  label: string; onPress: () => void; disabled?: boolean; a11y?: string;
}) {
  return (
    <Pressable
      style={styles.secondary}
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11y ?? label}
      accessibilityState={{ disabled }}
    >
      <Text style={styles.secondaryText}>{label}</Text>
    </Pressable>
  );
}

const LINKED_POINTS = [
  { icon: 'message-circle', text: 'Te aviso de lo importante en nuestra conversación.' },
  { icon: 'corner-up-left', text: 'Ahí mismo respondes: nada sale sin tu OK.' },
  { icon: 'eye-off', text: 'No marco nada como leído ni apareces «en línea».' },
];

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.heroFieldDark },
  flex: { flex: 1 },
  loading: { marginTop: 40 },

  // No padding on the field itself: Yoga sizes the absolute gradient against the padding box, and any padding
  // here leaves a hard strip of flat colour under it (seen on device). The room under the chip lives inside.
  brandField: { overflow: 'hidden' },
  fieldInner: { paddingBottom: 44 },
  // Over the field, not above it: the field stays short on small phones (iPhone SE).
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
  // Text on the field is deep emerald, >= 19 bold (theme.ts: white is 1.9:1 there).
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

  field: { gap: 6 },
  fieldLabel: { fontSize: 14, fontWeight: '700', color: colors.textFlat },
  phoneRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  countryChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 56, paddingHorizontal: 12, borderRadius: 16,
    backgroundColor: colors.mint, borderWidth: 1.5, borderColor: colors.primaryMuted,
  },
  countryChipEmpty: { borderColor: colors.successText },
  countryCode: { fontSize: 17, fontWeight: '700', color: colors.primaryDeep },
  phoneBox: {
    flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 56, borderRadius: 16, borderWidth: 1.5,
    borderColor: colors.border, backgroundColor: colors.background, paddingHorizontal: 14,
  },
  phoneBoxReady: { borderColor: colors.successText },
  phone: { flex: 1, fontSize: 20, fontWeight: '600', color: colors.textFlat, letterSpacing: 0.5, paddingVertical: 10 },
  hint: { fontSize: 12, color: colors.textSecondary },

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

  codeCard: {
    borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, padding: 16, gap: 14,
  },
  codeLabel: { fontSize: 13, fontWeight: '700', color: colors.textSecondary, textAlign: 'center', textTransform: 'uppercase', letterSpacing: 1 },
  cells: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 5 },
  // Shrinks on small screens (8 cells + a dash must fit 280 dp), never past 28.
  cell: {
    flexShrink: 1, flexBasis: 36, minWidth: 28, maxWidth: 36, height: 50, borderRadius: 10, borderWidth: 1.5,
    borderColor: colors.primaryMuted, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center',
  },
  cellText: { fontSize: 24, fontWeight: '800', color: colors.primaryDeep },
  dash: { fontSize: 22, fontWeight: '700', color: colors.textSecondary },
  timeline: { paddingHorizontal: 4 },
  timelineRow: { flexDirection: 'row', gap: 12 },
  timelineRail: { alignItems: 'center', width: 26 },
  railLine: { flex: 1, width: 2, minHeight: 14, backgroundColor: colors.primaryMuted, marginVertical: 2 },
  stepNumber: { width: 26, height: 26, borderRadius: 13, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center' },
  stepNumberText: { color: colors.white, fontSize: 13, fontWeight: '800' },
  stepText: { flex: 1, fontSize: 15, color: colors.textFlat, paddingTop: 3, paddingBottom: 14, lineHeight: 20 },
  waiting: {
    flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 14, backgroundColor: colors.mint, padding: 14,
  },
  waitingText: { flex: 1, fontSize: 14, fontWeight: '600', color: colors.primaryDeep },
  pulse: { width: 14, height: 14, alignItems: 'center', justifyContent: 'center' },
  pulseRing: { position: 'absolute', width: 14, height: 14, borderRadius: 7, backgroundColor: colors.successText },
  pulseDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.successText },
  preparing: { alignItems: 'center', gap: 10, paddingVertical: 32 },

  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  section: { fontSize: 18, fontWeight: '800', color: colors.textFlat },
  count: { minWidth: 22, height: 22, borderRadius: 11, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  countText: { color: colors.white, fontSize: 12, fontWeight: '800' },
  checked: { fontSize: 12, color: colors.textSecondary },
  card: {
    borderRadius: 20, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, padding: 14, gap: 10,
    shadowColor: '#111827', shadowOpacity: 0.05, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 1,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.white, fontSize: 17, fontWeight: '800' },
  chat: { fontSize: 16, fontWeight: '700', color: colors.textFlat },
  kindRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  kind: { fontSize: 12, fontWeight: '600', color: colors.primaryDeep },
  time: { fontSize: 12, color: colors.textSecondary },
  bubble: { alignSelf: 'flex-start', maxWidth: '92%', backgroundColor: colors.neutralDark, borderRadius: 14, borderTopLeftRadius: 4, paddingHorizontal: 12, paddingVertical: 8 },
  bubbleText: { fontSize: 15, color: colors.textFlat, lineHeight: 20 },
  summary: { fontSize: 13, color: colors.textSecondary },
  row: { flexDirection: 'row', gap: 10 },
  empty: { alignItems: 'center', gap: 8, paddingVertical: 28 },
  emptyIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center', marginBottom: 4 },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: colors.textFlat },
  unlink: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, minHeight: 48, marginTop: 8 },
  unlinkText: { color: colors.error.icon, fontSize: 14, fontWeight: '700' },

  compose: { gap: 8 },
  input: {
    minHeight: 96, borderRadius: 16, borderWidth: 1.5, borderColor: colors.border, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 15, color: colors.textFlat, textAlignVertical: 'top',
  },
  approval: { borderRadius: 18, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primaryMuted, padding: 14, gap: 10 },
  approvalHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  approvalHeading: { flex: 1, fontSize: 13, fontWeight: '700', color: colors.textSecondary },
  outgoing: {
    alignSelf: 'flex-end', maxWidth: '92%', backgroundColor: '#D9FDD3', borderRadius: 14, borderTopRightRadius: 4,
    paddingHorizontal: 12, paddingVertical: 8, flexDirection: 'row', alignItems: 'flex-end', gap: 6,
  },
  sent: { flexShrink: 1, fontSize: 15, color: colors.textFlat, lineHeight: 20 },
  tick: { marginBottom: 2 },

  text: { fontSize: 14, color: colors.gray600, textAlign: 'center' },
  alert: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: colors.error.background, borderRadius: 14, padding: 12 },
  alertText: { flex: 1, fontSize: 14, color: colors.error.text },
  button: { minHeight: 52, borderRadius: 16, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', padding: 12 },
  pressed: { opacity: 0.85 },
  disabled: { opacity: 0.45 },
  buttonText: { color: colors.white, fontSize: 16, fontWeight: '800' },
  pill: {
    flex: 1, flexDirection: 'row', gap: 6, minHeight: 44, borderRadius: 999, borderWidth: 1.5, borderColor: colors.primaryMuted,
    backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12,
  },
  pillFilled: { backgroundColor: colors.successText, borderColor: colors.successText },
  pillText: { color: colors.primaryDeep, fontSize: 14, fontWeight: '700' },
  pillTextFilled: { color: colors.white },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondaryText: { color: colors.successText, fontSize: 15, fontWeight: '700' },
});
