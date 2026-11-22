// "Correo y calendario": one state per source, and never a dead end. Mounted
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
import { ANSWER_CONNECTION, type Connections } from './api';
import { gmailView, type Build } from './rules';
import { closeConnections, keepTypedEmail, typedEmail, useConnectionsOpen, type Where } from './store';
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
            <Text style={styles.title}>Correo y calendario</Text>
            <Pressable style={styles.close} onPress={closeConnections} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={24} color={colors.textFlat} />
            </Pressable>
          </View>
          <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
            <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
              <View style={styles.source}>
                <View style={styles.sourceTitle}>
                  <Icon name="mail" size={18} color={colors.successText} />
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
                  <Icon name="calendar" size={18} color={colors.successText} />
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
});
