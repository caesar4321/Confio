// Pick one person who is on Confío: from the address book matches the app
// already keeps, or by @usuario. Used for a send rule's payee and for the
// beneficiary. The server resolves the person; this client sends only a
// handle (a username, or the matched phone for a contact without one) and
// never an address.
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { Text, TextInput } from '../common/AppText';
import { contactService } from '../../services/contactService';
import {
  formatRecipientPhoneForDisplay, recipientConfirmationService, recipientNeedsConfirmation,
} from '../../services/recipientConfirmationService';
import { useAuth } from '../../contexts/AuthContext';
import { ActionButton, Empty, RowsSkeleton } from './kit';
import { SA, HIT } from './tokens';

export interface PickedPerson {
  /** What the server resolves: a Confío username or the contact's matched phone. */
  handle: string;
  name: string;
}

interface Entry extends PickedPerson {
  id: string;
  subtitle: string;
  /** The Confío match came from a number saved without a country code. */
  inferred: boolean;
  /** For the wrong-recipient guard (same record as SendToFriend). */
  contactName: string;
  contactRecordId: string;
  recipientUserId: string;
  matchedPhone: string;
  confioUsername: string;
}

/**
 * The wrong-recipient guard of SendToFriend, for a payee or a beneficiary: a
 * match inferred from a number saved without a country code is confirmed by
 * the person (once per contact and account, remembered on the device) before
 * it can be picked. Resolves true when the pick may go ahead.
 */
export async function confirmPickedEntry(
  entry: Pick<Entry, 'inferred' | 'contactName' | 'contactRecordId' | 'recipientUserId' | 'matchedPhone' | 'confioUsername' | 'name'>,
  senderId: string,
  alert: typeof Alert.alert = Alert.alert,
): Promise<boolean> {
  if (!recipientNeedsConfirmation(true, entry.inferred)) {
    return true;
  }
  if (!senderId || !entry.recipientUserId || !entry.matchedPhone) {
    alert(
      'No pudimos verificar a esta persona',
      'Faltan datos de la cuenta Confío vinculada a este contacto. Actualiza tus contactos o escribe su @usuario.',
    );
    return false;
  }
  if (await recipientConfirmationService.isConfirmed(
    senderId, entry.contactRecordId, entry.recipientUserId, entry.matchedPhone,
  )) {
    return true;
  }
  return new Promise<boolean>((resolve) => {
    const usernameLine = entry.confioUsername ? `\nUsuario: @${entry.confioUsername}` : '';
    alert(
      'Confirma a la persona',
      `${entry.contactName} está guardado sin código de país. Confío interpretó el número como ${formatRecipientPhoneForDisplay(entry.matchedPhone)}.\n\nCuenta encontrada: ${entry.name}${usernameLine}\n\nConfirma que el país y el número son correctos antes de elegirla.`,
      [
        { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
        {
          text: 'Sí, es la persona correcta',
          onPress: async () => {
            await recipientConfirmationService.confirm(
              senderId, entry.contactRecordId, entry.recipientUserId, entry.matchedPhone,
            );
            resolve(true);
          },
        },
      ],
      { cancelable: false },
    );
  });
}

const ROW_HEIGHT = 68;

export function ConfioContactPicker({ visible, title, onClose, onPick }: {
  visible: boolean;
  title: string;
  onClose: () => void;
  onPick: (person: PickedPerson) => void;
}) {
  const insets = useSafeAreaInsets();
  const { userProfile } = useAuth();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!visible) {
      return;
    }
    let cancelled = false;
    setQuery('');
    (async () => {
      let list: Entry[] = [];
      try {
        const contacts = await contactService.getAllContacts();
        list = (contacts || [])
          .filter((c: any) => c?.isOnConfio && (c.confioUsername || c.confioMatchedPhone))
          .map((c: any, i: number) => {
            const name = [c.confioFirstName, c.confioLastName].filter(Boolean).join(' ').trim() || c.name || 'Contacto';
            return {
              id: String(c.confioUserId || `${c.id}_${i}`),
              handle: c.confioUsername ? String(c.confioUsername) : String(c.confioMatchedPhone),
              name,
              subtitle: c.confioUsername ? `@${c.confioUsername}` : 'En tus contactos',
              inferred: !!c.confioMatchWasInferred,
              contactName: String(c.name || name),
              contactRecordId: String(c.id || c.name || name),
              recipientUserId: c.confioUserId ? String(c.confioUserId) : '',
              matchedPhone: c.confioMatchedPhone ? String(c.confioMatchedPhone) : '',
              confioUsername: c.confioUsername ? String(c.confioUsername) : '',
            };
          });
      } catch {
        list = [];
      }
      if (!cancelled) {
        setEntries(list);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const pickEntry = async (item: Entry) => {
    if (await confirmPickedEntry(item, String(userProfile?.id || ''))) {
      onPick({ handle: item.handle, name: item.name });
    }
  };

  const typedUsername = /^@?[A-Za-z0-9_.]{3,}$/.test(query.trim()) ? query.trim().replace(/^@/, '') : '';
  const filtered = useMemo(() => {
    const q = query.trim().replace(/^@/, '').toLowerCase();
    const all = entries ?? [];
    return q ? all.filter((e) => e.name.toLowerCase().includes(q) || e.handle.toLowerCase().includes(q)) : all;
  }, [entries, query]);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={[styles.root, { paddingTop: insets.top }]}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <Pressable
            onPress={onClose}
            style={styles.close}
            hitSlop={6}
            accessibilityRole="button"
            accessibilityLabel="Cerrar"
          >
            <Icon name="x" size={24} color={SA.text} />
          </Pressable>
          <Text style={styles.title} accessibilityRole="header">{title}</Text>
        </View>
        <View style={styles.search}>
          <Icon name="search" size={18} color={SA.muted} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Nombre o @usuario"
            placeholderTextColor={SA.faint}
            autoCapitalize="none"
            autoCorrect={false}
            style={styles.input}
            accessibilityLabel="Buscar por nombre o usuario"
          />
        </View>
        {typedUsername ? (
          <ActionButton
            label={`Usar @${typedUsername}`}
            variant="secondary"
            onPress={() => onPick({ handle: typedUsername, name: `@${typedUsername}` })}
            style={styles.useTyped}
          />
        ) : null}
        {entries === null ? (
          <View style={styles.pad}><RowsSkeleton rows={4} /></View>
        ) : (
          <FlatList
            data={filtered}
            keyExtractor={(item) => item.id}
            keyboardShouldPersistTaps="handled"
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            getItemLayout={(_, index) => ({ length: ROW_HEIGHT, offset: ROW_HEIGHT * index, index })}
            contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
            ListEmptyComponent={(
              <Empty
                icon="users"
                title={query ? 'Nadie con ese nombre' : 'Aún no vemos contactos en Confío'}
                body="Escribe su @usuario para elegir a esa persona."
              />
            )}
            renderItem={({ item }) => (
              <Pressable
                onPress={() => { void pickEntry(item); }}
                style={({ pressed }) => [styles.row, pressed && styles.pressed]}
                accessibilityRole="button"
                accessibilityLabel={`${item.name}, ${item.subtitle}`}
              >
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{item.name.charAt(0).toUpperCase()}</Text>
                </View>
                <View style={styles.rowText}>
                  <Text style={styles.rowName} numberOfLines={1}>{item.name}</Text>
                  <Text style={styles.rowSub} numberOfLines={1}>{item.subtitle}</Text>
                </View>
                <Icon name="chevron-right" size={20} color={SA.faint} />
              </Pressable>
            )}
          />
        )}
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: SA.card },
  pad: { paddingHorizontal: 16 },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, minHeight: 56 },
  close: { width: HIT, height: HIT, alignItems: 'center', justifyContent: 'center' },
  title: { flex: 1, fontSize: 20, fontWeight: '700', color: SA.text, marginLeft: 4 },
  search: {
    flexDirection: 'row', alignItems: 'center', marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 14,
    minHeight: 48, borderRadius: 14, backgroundColor: SA.page, borderWidth: 1, borderColor: SA.line,
  },
  input: { flex: 1, marginLeft: 10, fontSize: 16, color: SA.text, paddingVertical: 10 },
  useTyped: { marginHorizontal: 16, marginBottom: 8, minHeight: 48 },
  row: { height: ROW_HEIGHT, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16 },
  pressed: { opacity: 0.7 },
  avatar: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: SA.mint,
    alignItems: 'center', justifyContent: 'center', marginRight: 14,
  },
  avatarText: { fontSize: 17, fontWeight: '700', color: SA.deep },
  rowText: { flex: 1 },
  rowName: { fontSize: 16, fontWeight: '600', color: SA.text },
  rowSub: { fontSize: 14, color: SA.muted, marginTop: 2 },
});
