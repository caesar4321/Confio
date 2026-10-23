import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Linking, Platform, Pressable, Share, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { ContactPermissionModal } from '../components/ContactPermissionModal';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { CREATE_TEAM_INVITE, INVITE_CONTACTS_TO_TEAM } from '../apollo/mutations';
import { useAuth } from '../contexts/AuthContext';
import { ContactSyncProgress, contactService, hasDefaultPhoneRegion } from '../services/contactService';
import { MainStackParamList } from '../types/navigation';
import { buildTeamInviteLink, buildTeamInviteMessage } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'TeamInvite'>['route'];

// The phone is what the server matches (it never takes an account id).
type Friend = { userId: string; name: string; phone: string };

const PER_SEND = 10;

/**
 * Friend invites: share the team link (WhatsApp, anywhere) or notify
 * contacts who already use Confío. The friend still needs a verified,
 * public profile to join; the captain's link skips approval.
 */
export const TeamInviteScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { teamId, teamName } = route.params;
  const { userProfile } = useAuth() as any;
  const [token, setToken] = useState<string | null>(null);
  const [friends, setFriends] = useState<Friend[] | null>(null);
  // Contacts were never synced on this phone (Enviar is where that used to happen): offer it here.
  const [neverSynced, setNeverSynced] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [progress, setProgress] = useState<ContactSyncProgress | null>(null);
  const [askPermission, setAskPermission] = useState(false);
  const apolloClient = useApolloClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [createInvite] = useMutation(CREATE_TEAM_INVITE);
  const [inviteContacts, { loading: sending }] = useMutation(INVITE_CONTACTS_TO_TEAM);
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);

  useEffect(() => {
    createInvite({ variables: { teamId } })
      .then(({ data }) => {
        const result = data?.createTeamInvite;
        if (!live.current) return;
        if (result?.success && result.token) setToken(result.token);
        else {
          Alert.alert('No pudimos crear tu invitación', result?.error || 'Inténtalo de nuevo.');
          navigation.goBack();
        }
      })
      .catch(() => {
        if (!live.current) return;
        Alert.alert('No pudimos crear tu invitación', 'Revisa tu conexión e inténtalo de nuevo.');
        navigation.goBack();
      });
    void loadFriends();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  const loadFriends = useCallback(async () => {
    // A cold contact cache answers [] while it loads from the keychain: ask again for a few seconds.
    let all = await contactService.getAllContacts().catch(() => []);
    for (let attempt = 0; attempt < 8 && all.length === 0 && live.current; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      all = await contactService.getAllContacts().catch(() => []);
    }
    if (!live.current) return;
    const seen = new Set<string>();
    const onConfio: Friend[] = [];
    for (const c of all) {
      const id = c.confioUserId;
      const phone = c.confioMatchedPhone || c.normalizedPhones?.[0];
      if (!c.isOnConfio || !id || !phone || seen.has(id) || String(id) === String(userProfile?.id)) continue;
      seen.add(id);
      onConfio.push({ userId: String(id), name: c.name, phone });
    }
    onConfio.sort((a, b) => a.name.localeCompare(b.name));
    setNeverSynced(all.length === 0);
    setFriends(onConfio);
  }, [userProfile?.id]);

  /** The same sync Enviar runs: device contacts matched against Confío by phone. */
  const sync = async () => {
    if (!hasDefaultPhoneRegion()) {
      Alert.alert('País del teléfono no disponible', 'Espera a que termine de cargar tu perfil e inténtalo de nuevo.');
      return;
    }
    setSyncing(true);
    setProgress(null);
    let ok = false;
    try {
      ok = await contactService.syncContacts(apolloClient, (p) => { if (live.current) setProgress(p); });
    } catch {
      ok = false;
    } finally {
      if (live.current) {
        setSyncing(false);
        setProgress(null);
      }
    }
    await loadFriends();
    // A failed search is not "none of your contacts use Confío": say so.
    if (!ok && live.current) {
      Alert.alert('No pudimos revisar tus contactos', 'Revisa tu conexión e inténtalo de nuevo, o comparte el enlace por WhatsApp.');
    }
  };

  const findFriends = async () => {
    if (syncing) return;
    const granted = await contactService.hasContactPermission();
    // iOS also needs the explicit consent to check the numbers with Confío.
    if (!granted || (Platform.OS === 'ios' && !(await contactService.hasUploadConsent()))) {
      setAskPermission(true);
      return;
    }
    await sync();
  };

  const allowContacts = async () => {
    setAskPermission(false);
    if (Platform.OS === 'ios') await contactService.setUploadConsent(true);
    const granted = await contactService.requestContactPermission();
    if (!granted) {
      await contactService.storePermissionStatus('denied');
      Alert.alert('Sin acceso a tus contactos', 'Puedes activarlo en Ajustes o compartir el enlace por WhatsApp.', [
        { text: 'Ahora no', style: 'cancel' },
        { text: 'Abrir Ajustes', onPress: () => { Linking.openSettings().catch(() => {}); } },
      ]);
      return;
    }
    await contactService.storePermissionStatus('granted');
    await sync();
  };

  const link = useMemo(
    () => (token ? buildTeamInviteLink(token) : null),
    [token],
  );

  const share = async () => {
    if (!link) return;
    try {
      await Share.share({ message: buildTeamInviteMessage(teamName, link) });
    } catch {
      // Dismissed.
    }
  };

  const toggle = (userId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(userId)) next.delete(userId);
      else if (next.size < PER_SEND) next.add(userId);
      return next;
    });
  };

  const send = async () => {
    if (!selected.size || sending) return;
    try {
      const phones = (friends ?? []).filter((f) => selected.has(f.userId)).map((f) => f.phone);
      const { data } = await inviteContacts({ variables: { teamId, phones } });
      const result = data?.inviteContactsToTeam;
      if (!result?.success) {
        Alert.alert('No pudimos enviar las invitaciones', result?.error || 'Inténtalo de nuevo.');
        return;
      }
      setSelected(new Set());
      Alert.alert('Invitaciones enviadas', 'Les avisamos en Confío. Si ya están en el equipo o los invitaron esta semana, no les llega otra.');
    } catch {
      Alert.alert('No pudimos enviar las invitaciones', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const header = (
    <View>
      <View style={styles.card}>
        <Text style={styles.title}>Comparte el enlace de {teamName}</Text>
        <Text style={styles.body}>
          Por WhatsApp o donde quieras. Si tu amigo aún no tiene Confío, el enlace lo lleva a descargarla.
        </Text>
        <Pressable style={[styles.primary, !link && styles.disabled]} disabled={!link} onPress={() => { void share(); }}
          accessibilityRole="button">
          {link ? <Icon name="share-2" size={18} color={colors.white} /> : <ActivityIndicator color={colors.white} />}
          <Text style={styles.primaryText}>Compartir enlace</Text>
        </Pressable>
        <Text style={styles.note}>
          Al invitar, tu amigo verá tu nombre de usuario de Comunidad y tu rentabilidad, como cualquier miembro del equipo.
        </Text>
      </View>
      <Text style={styles.section}>Tus contactos en Confío</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      <Header title="Invitar a un amigo" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <FlatList
        data={friends ?? []}
        keyExtractor={(f) => f.userId}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        initialNumToRender={20}
        maxToRenderPerBatch={20}
        windowSize={11}
        renderItem={({ item }) => {
          const on = selected.has(item.userId);
          return (
            <Pressable style={styles.row} onPress={() => toggle(item.userId)} accessibilityRole="checkbox"
              accessibilityState={{ checked: on }}>
              <View style={styles.initial}><Text style={styles.initialText}>{item.name.slice(0, 1).toUpperCase()}</Text></View>
              <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
              <Icon name={on ? 'check-circle' : 'circle'} size={22} color={on ? colors.primaryDark : colors.border} />
            </Pressable>
          );
        }}
        ListEmptyComponent={friends === null || syncing ? (
          <View style={styles.syncing}>
            <ActivityIndicator color={colors.primary} />
            {syncing ? (
              <Text style={styles.hint}>
                {progress?.phase === 'matching' && progress.total > 0
                  ? `Buscando a tus amigos en Confío… ${Math.round((progress.processed / progress.total) * 100)}%`
                  : 'Leyendo tus contactos…'}
              </Text>
            ) : null}
          </View>
        ) : neverSynced ? (
          <View style={styles.findCard}>
            <Text style={styles.title}>¿Quiénes de tus contactos ya usan Confío?</Text>
            <Text style={styles.body}>
              Revisamos los números de tu agenda para mostrarte a tus amigos en Confío. No le avisamos a nadie hasta que tú lo elijas.
            </Text>
            <Pressable style={styles.primary} onPress={() => { void findFriends(); }} accessibilityRole="button">
              <Icon name="users" size={18} color={colors.white} />
              <Text style={styles.primaryText}>Buscar en mis contactos</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.syncing}>
            <Text style={styles.empty}>Ninguno de tus contactos usa Confío todavía. Comparte el enlace.</Text>
            <Pressable onPress={() => { void findFriends(); }} hitSlop={8} accessibilityRole="button">
              <Text style={styles.link}>Volver a buscar</Text>
            </Pressable>
          </View>
        )}
      />
      <ContactPermissionModal
        visible={askPermission}
        onAllow={() => { void allowContacts(); }}
        onDeny={() => setAskPermission(false)}
        onClose={() => setAskPermission(false)}
      />
      {selected.size > 0 ? (
        <View style={styles.footer}>
          <Pressable style={[styles.primary, sending && styles.disabled]} disabled={sending} onPress={() => { void send(); }}
            accessibilityRole="button">
            <Text style={styles.primaryText}>
              Invitar {selected.size === 1 ? 'a 1 contacto' : `a ${selected.size} contactos`}
            </Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
};

export default TeamInviteScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  list: { paddingBottom: 100, flexGrow: 1 },
  loading: { marginTop: 32 },
  card: { margin: 16, padding: 16, gap: 10, borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 17, fontWeight: '700', color: colors.dark },
  body: { fontSize: 14, color: colors.textSecondary },
  note: { fontSize: 12, color: colors.textSecondary },
  primary: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 12, borderRadius: 24,
    backgroundColor: colors.primaryDark,
  },
  primaryText: { fontSize: 15, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.5 },
  section: { paddingHorizontal: 16, paddingBottom: 6, fontSize: 13, fontWeight: '700', color: colors.textSecondary, textTransform: 'uppercase' },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.borderLight,
  },
  initial: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryLight },
  initialText: { fontSize: 15, fontWeight: '700', color: colors.primaryDark },
  name: { flex: 1, fontSize: 15, color: colors.dark },
  syncing: { alignItems: 'center', gap: 10, padding: 24 },
  hint: { fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
  link: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  findCard: { marginHorizontal: 16, padding: 16, gap: 10, borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  empty: { padding: 24, fontSize: 14, color: colors.textSecondary, textAlign: 'center' },
  footer: { position: 'absolute', left: 16, right: 16, bottom: 24 },
});
