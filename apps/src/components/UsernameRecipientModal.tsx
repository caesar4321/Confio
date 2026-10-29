import React, { useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useLazyQuery } from '@apollo/client';
import { Text, TextInput } from './common/AppText';
import { Button } from './common/Button';
import { colors } from '../config/theme';
import { IdentityStatusLine } from './IdentityStatusLine';

export const SEND_RECIPIENT_BY_USERNAME = gql`
  query SendRecipientByUsername($username: String!) {
    sendRecipientByUsername(username: $username) {
      userId
      username
      displayName
      identityVerified
      receivesByQrOnly
      isSelf
    }
  }
`;

export type UsernameFriend = {
  id: string;
  userId: string;
  name: string;
  avatar: string;
  isOnConfio: true;
  phone: '';
  confioUsername: string;
  confioFirstName: string;
};

/**
 * "Enviar a @usuario": the account is shown with its verified check, and by
 * name (first name and last initial) once the two have paid each other —
 * @usuario is public, so it never reveals a stranger's name
 * (users/name_visibility.py). An account that is paid
 * through Cobrar only (users/direct_receive.py) is named as such and cannot
 * be picked.
 */
export const UsernameRecipientModal = ({
  visible,
  onClose,
  onFound,
}: {
  visible: boolean;
  onClose: () => void;
  onFound: (friend: UsernameFriend) => void;
}) => {
  const [username, setUsername] = useState('');
  // The username the last lookup was for: a result only counts while the
  // input still says the same thing, so editing never leaves an old match
  // selectable.
  const [lookedUp, setLookedUp] = useState('');
  const [lookup, { data, loading, error }] = useLazyQuery(SEND_RECIPIENT_BY_USERNAME, {
    fetchPolicy: 'network-only',
  });
  const cleaned = username.trim().replace(/^@/, '');
  const current = Boolean(lookedUp) && lookedUp.toLowerCase() === cleaned.toLowerCase() && !loading;
  const found = current ? data?.sendRecipientByUsername : null;
  const called = current;

  const search = () => {
    if (!cleaned) return;
    setLookedUp(cleaned);
    lookup({ variables: { username: cleaned } });
  };

  const close = () => {
    setUsername('');
    setLookedUp('');
    onClose();
  };

  const confirm = () => {
    if (!found || found.isSelf || found.receivesByQrOnly
      || String(found.username || '').toLowerCase() !== cleaned.toLowerCase()) return;
    onFound({
      id: String(found.userId),
      userId: String(found.userId),
      name: found.displayName || `@${found.username}`,
      avatar: (found.displayName || found.username || '?').charAt(0).toUpperCase(),
      isOnConfio: true,
      phone: '',
      confioUsername: found.username,
      confioFirstName: found.displayName || '',
    });
    setUsername('');
    setLookedUp('');
  };

  let result: React.ReactNode = null;
  if (error && current) {
    result = <Text style={styles.problem}>{error.message || 'No pudimos buscar ese usuario.'}</Text>;
  } else if (called && !loading && !found) {
    result = <Text style={styles.problem}>No encontramos @{cleaned} en Confío.</Text>;
  } else if (found?.isSelf) {
    result = <Text style={styles.problem}>Ese es tu propio usuario.</Text>;
  } else if (found) {
    result = (
      <View style={styles.found}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(found.displayName || found.username).charAt(0).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.foundName}>{found.displayName}</Text>
          {/* The name shows only once you have paid each other; until then
              the server answers with the @usuario itself. */}
          {String(found.displayName || '').startsWith('@') ? (
            <Text style={styles.foundUser}>Confirma con tu amigo que es su usuario</Text>
          ) : (
            <Text style={styles.foundUser}>@{found.username}</Text>
          )}
          <View style={{ marginTop: 4 }}>
            <IdentityStatusLine verified={Boolean(found.identityVerified)} />
          </View>
          {found.receivesByQrOnly ? (
            <Text style={styles.problem}>Esta cuenta cobra con QR. Pedile su código de Cobrar para pagarle.</Text>
          ) : null}
        </View>
      </View>
    );
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>Enviar a un @usuario</Text>
            <TouchableOpacity onPress={close} accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.text.secondary} />
            </TouchableOpacity>
          </View>
          <View style={styles.inputRow}>
            <Text style={styles.at}>@</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="usuario"
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="search"
              onSubmitEditing={search}
            />
          </View>
          {result}
          {found && !found.isSelf && !found.receivesByQrOnly ? (
            <Button title={`Enviar a ${found.displayName}`} onPress={confirm} />
          ) : (
            <Button title="Buscar" onPress={search} disabled={!cleaned || (current && !found && !error)} loading={loading} />
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, gap: 16 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 18, fontWeight: '700', color: colors.text.primary },
  inputRow: {
    flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: colors.text.light,
    borderRadius: 12, paddingHorizontal: 12,
  },
  at: { fontSize: 18, color: colors.text.secondary, marginRight: 4 },
  input: { flex: 1, fontSize: 18, paddingVertical: 12, color: colors.text.primary },
  found: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarText: { fontSize: 18, fontWeight: '700', color: colors.primaryDark },
  foundName: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
  foundUser: { fontSize: 14, color: colors.text.secondary },
  problem: { fontSize: 14, color: colors.error.text },
});
