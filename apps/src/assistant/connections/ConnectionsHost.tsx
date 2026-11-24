// "WhatsApp, correo y calendario": one state per source, and never a dead end. Mounted
// once inside the assistant, so the sheets it opens sit above the chat.
import React, { useEffect, useState } from 'react';
import { AccessibilityInfo, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import CalendarConnectSheet from '../calendar/CalendarConnectSheet';
import MailSheet from '../mail/MailSheet';
import { closeMailSession, mailSession } from '../mail/session';
import WhatsAppLogo from '../../assets/svg/WhatsApp.svg';
import CalendarMark from '../../components/svg/CalendarMark';
import GmailLogo from '../../components/svg/GmailLogo';
import WhatsAppSheet from '../whatsapp/WhatsAppSheet';
import { whatsAppView } from '../whatsapp/rules';
import { closeWhatsAppSession, whatsAppSession } from '../whatsapp/session';
import { useWhatsApp } from '../whatsapp/useWhatsApp';
import { ANSWER_CONNECTION, type Connections } from './api';
import { gmailView, type Build } from './rules';
import {
  closeConnections, keepTypedEmail, openConnections, takeWhatsAppRequest, typedEmail, useConnectionsOpen,
  useWhatsAppRequested, type Where,
} from './store';
import { useConnections, useViewer } from './useConnections';

type SheetProps = { userId: string; data: Connections; build: Build; refresh: () => void };

export function ConnectionsSheet({ userId, data, build, refresh }: SheetProps) {
  const [email, setEmail] = useState(typedEmail(userId) ?? data.googleEmail ?? data.suggestedEmail ?? '');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ feature: 'gmail' | 'calendar'; text: string } | null>(null);
  // The mail sheet's own open state survives the lock (mail/session.ts).
  const [mailOpen, setMailOpen] = useState(() => build.mail && mailSession(userId).open);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [answer] = useMutation(ANSWER_CONNECTION);

  useEffect(refresh, [refresh]);
  // Only when a place can be given: until then it is a plain yes or no.
  const needsAddress = data.gmail === 'request';

  const respond = async (feature: 'gmail' | 'calendar', wants: boolean) => {
    setBusy(true);
    setMessage(null);
    let said = 'No pude guardar tu respuesta. Inténtalo de nuevo.';
    try {
      const variables = { feature, wants, googleEmail: wants && needsAddress && feature === 'gmail' ? email.trim() : null };
      const { data: saved } = await answer({ variables });
      const result = saved?.answerAssistantMailConnection;
      if (result?.success) {
        if (!wants && feature === 'gmail' && data.gmail === 'invited') {
          // With the card switched off there is nothing left to show them here.
          closeConnections();
        }
        said = wants ? 'Listo, quedaste en la lista.' : 'Listo. Aquí lo encuentras si cambias de idea.';
      } else if (result?.error) {
        said = result.error;
      }
    } catch {
      // said already says it failed.
    } finally {
      setBusy(false);
      setMessage({ feature, text: said });
      AccessibilityInfo.announceForAccessibility?.(said);
      // Also after a refusal: places may have opened or run out meanwhile.
      refresh();
    }
  };

  const button = (source: string, label: string, onPress: () => void, disabled = false) => (
    <Pressable
      style={[styles.button, (busy || disabled) && styles.disabled]}
      disabled={busy || disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${source}`}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
  const decline = (feature: 'gmail' | 'calendar', label: string) => (
    <Pressable
      style={styles.secondary}
      disabled={busy}
      onPress={() => void respond(feature, false)}
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${feature === 'gmail' ? 'Gmail' : 'Calendario'}`}
    >
      <Text style={styles.secondaryText}>{label}</Text>
    </Pressable>
  );
  const result = (feature: 'gmail' | 'calendar') => (message?.feature === feature
    ? <Text style={styles.message} accessibilityLiveRegion="polite">{message.text}</Text>
    : null);
  const badge = (label?: string) => (label ? <Text style={styles.badge}>{label}</Text> : null);

  const view = gmailView(data, build);
  const closeMail = () => {
    closeMailSession(userId);
    setMailOpen(false);
    refresh();
  };

  return (
    <Modal visible animationType="slide" onRequestClose={closeConnections}>
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <View style={styles.header}>
            <Text style={styles.title}>WhatsApp, correo y calendario</Text>
            <Pressable style={styles.close} onPress={closeConnections} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.textFlat} />
            </Pressable>
          </View>
          <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            {/* flex: 1 so it is bounded by the screen and scrolls (the same fix the WhatsApp screen needed on
                device): without it, it grew to its content and the bottom was cut off, unscrollable. */}
            <ScrollView
              style={styles.flex}
              contentContainerStyle={styles.content}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator
            >
              <WhatsAppRow userId={userId} />
              <View style={styles.source}>
                <View style={styles.sourceTitle}>
                  <View style={styles.logoSmall}><GmailLogo size={24} /></View>
                  <Text style={styles.name}>Gmail</Text>
                  {badge(view.badge)}
                </View>
                <Text style={styles.text}>
                  Avisos de facturas, vencimientos y viajes, respuestas sobre tu correo y borradores que tú confirmas
                  antes de enviar.
                </Text>
                <Text style={styles.text}>{view.body}</Text>
                {view.action === 'open'
                  ? button('Gmail', data.gmail === 'invited' ? 'Conectar Gmail' : 'Abrir mi correo', () => {
                      mailSession(userId).open = true;
                      setMailOpen(true);
                    })
                  : null}
                {data.gmail === 'waiting' || data.gmail === 'waiting_full' ? decline('gmail', 'Salir de la lista') : null}
                {data.gmail === 'invited' && data.gmailAnswered ? decline('gmail', 'No quiero el cupo') : null}
                {view.action === 'ask' ? (
                  <>
                    {needsAddress ? (
                      <>
                    <Text style={styles.label}>El Gmail que quieres conectar</Text>
                    <TextInput
                      style={styles.input}
                      value={email}
                      onChangeText={(value) => {
                        setEmail(value);
                        keepTypedEmail(userId, value);
                      }}
                      autoCapitalize="none"
                      autoCorrect={false}
                      keyboardType="email-address"
                      accessibilityLabel="El Gmail que quieres conectar"
                    />
                    <Text style={styles.detail}>
                      Tiene que ser una dirección @gmail.com. La usamos solo para darte acceso: pedirlo no conecta ni
                      lee tu correo.
                    </Text>
                      </>
                    ) : null}
                    {button('Gmail', needsAddress ? 'Pedir un cupo' : 'Sí, avísame', () => void respond('gmail', true), needsAddress && !email.trim())}
                    {decline('gmail', 'Solo miraba')}
                  </>
                ) : null}
                {result('gmail')}
              </View>

              <View style={styles.source}>
                <View style={styles.sourceTitle}>
                  <View style={styles.logoSmall}><CalendarMark size={28} /></View>
                  <Text style={styles.name}>Calendario</Text>
                  {badge(build.calendar ? undefined : data.calendar === 'waiting' ? 'En la lista' : 'Próximamente')}
                </View>
                <Text style={styles.text}>
                  Los calendarios que elijas de tu teléfono (Apple, Google u otros), para que actives avisos de los
                  pagos y viajes que elijas.
                </Text>
                {build.calendar ? (
                  button('Calendario', 'Conectar calendario', () => setCalendarOpen(true))
                ) : data.calendar === 'waiting' ? (
                  <>
                    <Text style={styles.text}>Te avisamos si puedes conectarlo.</Text>
                    {decline('calendar', 'Salir de la lista')}
                  </>
                ) : (
                  <>
                    {button('Calendario', 'Sí, avísame', () => void respond('calendar', true))}
                    {decline('calendar', 'Solo miraba')}
                  </>
                )}
                {result('calendar')}
              </View>

              <Text style={styles.detail}>El correo de iCloud (iMail) todavía no se puede conectar.</Text>
            </ScrollView>
          </KeyboardAvoidingView>
          {mailOpen ? <MailSheet key={userId} userId={userId} onClose={closeMail} /> : null}
          {calendarOpen ? <CalendarConnectSheet key={userId} userId={userId} onClose={() => setCalendarOpen(false)} /> : null}
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}

/** Its own query: an older server without WhatsApp just shows no row. */
const WHATSAPP_PERKS = [
  { icon: 'bell', label: 'Avisos de lo importante' },
  { icon: 'corner-up-left', label: 'Respondes desde aquí' },
  { icon: 'eye-off', label: 'Sin marcar leídos' },
];

const WHATSAPP_TONES: Record<string, { background: string; dot: string; text: string }> = {
  none: { background: colors.mint, dot: colors.successText, text: colors.primaryDeep },
  pairing: { background: colors.warning.background, dot: colors.warning.icon, text: colors.warning.text },
  linked: { background: colors.mint, dot: colors.successText, text: colors.primaryDeep },
  gone: { background: colors.warning.background, dot: colors.warning.icon, text: colors.warning.text },
  failed: { background: colors.error.background, dot: colors.error.icon, text: colors.error.text },
};

function WhatsAppRow({ userId }: { userId: string }) {
  const { link: fresh, refetch } = useWhatsApp(userId, 'cache-and-network');
  // A failed read must not pull the sheet from under them; the open state survives the lock (session.ts).
  const [last, setLast] = useState(fresh);
  useEffect(() => {
    if (fresh) {
      setLast(fresh);
    }
  }, [fresh]);
  const link = fresh ?? last;
  const [open, setOpenState] = useState(() => whatsAppSession(userId).open);
  const setOpen = (value: boolean) => {
    if (value) {
      whatsAppSession(userId).open = true;
    } else {
      closeWhatsAppSession(userId);
    }
    setOpenState(value);
  };
  if (!link) {
    return null;
  }
  const view = whatsAppView(link);
  const tone = WHATSAPP_TONES[link.state] ?? WHATSAPP_TONES.none;
  // Not linked yet (or not any more): what linking gives, at a glance.
  const pitch = link.state === 'none' || link.state === 'failed' || link.state === 'gone';
  return (
    <View style={styles.whatsApp}>
      <View style={styles.whatsAppHead}>
        <View style={styles.logoTile}>
          <WhatsAppLogo width={30} height={30} />
        </View>
        <View style={styles.flex}>
          <Text style={styles.whatsAppName}>WhatsApp</Text>
          {view.badge ? (
            <View style={[styles.state, { backgroundColor: tone.background }]}>
              <View style={[styles.stateDot, { backgroundColor: tone.dot }]} />
              <Text style={[styles.stateText, { color: tone.text }]}>{view.badge}</Text>
            </View>
          ) : (
            <Text style={styles.detail}>Tu propio número, vinculado como un dispositivo</Text>
          )}
        </View>
      </View>
      <Text style={styles.whatsAppBody}>{view.body}</Text>
      {pitch ? (
        <View style={styles.perks}>
          {WHATSAPP_PERKS.map((perk) => (
            <View key={perk.label} style={styles.perk}>
              <View style={styles.perkIcon}><Icon name={perk.icon} size={16} color={colors.successText} /></View>
              <Text style={styles.perkText}>{perk.label}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {view.action ? (
        <Pressable
          style={({ pressed }) => [styles.button, styles.whatsAppButton, pressed && styles.pressed]}
          onPress={() => setOpen(true)}
          accessibilityRole="button"
          accessibilityLabel={`${view.actionLabel}: WhatsApp`}
        >
          <Text style={styles.buttonText}>{view.actionLabel}</Text>
          <Icon name="arrow-right" size={18} color={colors.white} />
        </Pressable>
      ) : null}
      {open ? (
        <WhatsAppSheet
          userId={userId}
          onClose={() => {
            setOpen(false);
            refetch().catch(() => undefined);
          }}
        />
      ) : null}
    </View>
  );
}

function OpenHost({ userId }: { userId: string }) {
  const { connections, build, refetch } = useConnections(userId, 'cache-and-network');
  // A failed or empty refresh must not pull the sheet, and the mail inside it, from under them.
  const [last, setLast] = useState(connections);
  useEffect(() => {
    if (connections) {
      setLast(connections);
    }
  }, [connections]);
  const refresh = React.useCallback(() => {
    refetch().catch(() => undefined);
  }, [refetch]);
  const data = connections ?? last;
  return data ? <ConnectionsSheet userId={userId} data={data} build={build} refresh={refresh} /> : null;
}

export default function ConnectionsHost({ where }: { where: Where }) {
  const userId = useViewer();
  const open = useConnectionsOpen(userId, where);
  // A WhatsApp notice opened (linked, unlinked, important messages): its screen, on Inicio.
  const requested = useWhatsAppRequested();
  useEffect(() => {
    if (requested && userId && where === 'home' && takeWhatsAppRequest()) {
      whatsAppSession(userId).open = true;
      openConnections(userId, 'home');
    }
  }, [requested, userId, where]);
  return userId && open ? <OpenHost key={userId} userId={userId} /> : null;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 20 },
  title: { flex: 1, fontSize: 20, fontWeight: '700', color: colors.textFlat },
  close: { width: 52, height: 52, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40, gap: 16 },
  source: { borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 16, gap: 8 },
  sourceTitle: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  name: { fontSize: 17, fontWeight: '700', color: colors.textFlat },
  badge: {
    fontSize: 12, fontWeight: '600', color: colors.primaryDeep, backgroundColor: colors.mint, borderRadius: 10,
    overflow: 'hidden', paddingHorizontal: 8, paddingVertical: 3,
  },
  text: { fontSize: 14, color: colors.gray600 },
  label: { fontSize: 13, fontWeight: '600', color: colors.textSecondary, marginTop: 4 },
  detail: { fontSize: 13, color: colors.textSecondary },
  message: { fontSize: 14, color: colors.textFlat },
  input: {
    minHeight: 44, borderRadius: 12, backgroundColor: colors.neutralDark, paddingHorizontal: 14, fontSize: 15,
    color: colors.textFlat,
  },
  button: { minHeight: 48, borderRadius: 14, backgroundColor: colors.successText, alignItems: 'center', justifyContent: 'center', padding: 12 },
  disabled: { opacity: 0.45 },
  buttonText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  secondary: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondaryText: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  pressed: { opacity: 0.85 },
  logoSmall: {
    width: 40, height: 40, borderRadius: 12, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: colors.border,
  },
  // WhatsApp leads the sheet: a card of its own, not one more row.
  whatsApp: {
    borderRadius: 20, padding: 16, gap: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primaryMuted,
  },
  whatsAppHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logoTile: {
    width: 48, height: 48, borderRadius: 14, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#064E3B', shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 2,
  },
  whatsAppName: { fontSize: 18, fontWeight: '800', color: colors.textFlat },
  state: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 3, marginTop: 3,
  },
  stateDot: { width: 7, height: 7, borderRadius: 4 },
  stateText: { fontSize: 12, fontWeight: '700' },
  whatsAppBody: { fontSize: 15, color: colors.textFlat, lineHeight: 21 },
  perks: { flexDirection: 'row', gap: 8 },
  perk: { flex: 1, alignItems: 'center', gap: 6, borderRadius: 14, backgroundColor: colors.background, paddingVertical: 10, paddingHorizontal: 4 },
  perkIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.mint, alignItems: 'center', justifyContent: 'center' },
  perkText: { fontSize: 12, fontWeight: '600', color: colors.gray600, textAlign: 'center' },
  whatsAppButton: { flexDirection: 'row', gap: 8, minHeight: 52, borderRadius: 16 },
});
