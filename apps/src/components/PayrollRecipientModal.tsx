import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, TextInput, ActivityIndicator, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation, useApolloClient } from '@apollo/client';
import { CHECK_USERS_BY_PHONES, CHECK_USERS_BY_USERNAMES } from '../apollo/queries';
import { CREATE_PAYROLL_RECIPIENT } from '../apollo/mutations/payroll';
import { countries } from '../utils/countries';
import { useCountrySelection } from '../hooks/useCountrySelection';

type Props = {
  visible: boolean;
  onClose: () => void;
  onChanged?: () => void;
};

export const PayrollRecipientModal: React.FC<Props> = ({ visible, onClose, onChanged }) => {
  const [phone, setPhone] = useState('');
  const [username, setUsername] = useState('');
  const [mode, setMode] = useState<'phone' | 'username'>('phone');
  const [displayName, setDisplayName] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const apolloClient = useApolloClient();

  const { selectedCountry, selectCountry } = useCountrySelection();
  useEffect(() => {
    if (!selectedCountry) {
      const venezuela = countries.find(c => c[2] === 'VE');
      if (venezuela) selectCountry(venezuela);
    }
  }, [selectedCountry, selectCountry]);

  const [createRecipient, { loading: creating }] = useMutation(CREATE_PAYROLL_RECIPIENT);

  const handleAdd = async () => {
    try {
      setLookupLoading(true);
      let match = null;
      let identifierDisplay = '';

      if (mode === 'phone') {
        if (!phone.trim()) {
          Alert.alert('Ingresa teléfono', 'Por favor ingresa el número de teléfono del destinatario', [{ text: 'OK' }]);
          return;
        }
        const fullPhone = `${selectedCountry?.[1] || ''}${phone.replace(/[^0-9]/g, '')}`;
        const res = await apolloClient.query({
          query: CHECK_USERS_BY_PHONES,
          variables: { phoneNumbers: [fullPhone] },
          fetchPolicy: 'network-only',
        });
        match = res.data?.checkUsersByPhones?.[0];
        identifierDisplay = fullPhone;
      } else {
        if (!username.trim()) {
          Alert.alert('Ingresa usuario', 'Por favor ingresa el @usuario de Confío', [{ text: 'OK' }]);
          return;
        }
        const handle = username.trim().replace(/^@/, '');
        const res = await apolloClient.query({
          query: CHECK_USERS_BY_USERNAMES,
          variables: { usernames: [handle] },
          fetchPolicy: 'network-only',
        });
        match = res.data?.checkUsersByUsernames?.[0];
        identifierDisplay = `@${handle}`;
      }

      if (!match || !match.isOnConfio) {
        Alert.alert('No encontrado', 'No encontramos un usuario de Confío con ese dato.', [{ text: 'OK' }]);
        return;
      }
      if (!match.activeAccountId) {
        Alert.alert('Cuenta faltante', 'El usuario no tiene una cuenta activa seleccionable.', [{ text: 'OK' }]);
        return;
      }

      const resCreate = await createRecipient({
        variables: {
          recipientUserId: match.userId,
          recipientAccountId: match.activeAccountId,
          displayName: displayName || match.username || identifierDisplay,
        },
      });
      if (resCreate.data?.createPayrollRecipient?.success) {
        onChanged?.();
        setPhone('');
        setUsername('');
        setDisplayName('');
        onClose();
      } else {
        Alert.alert('Error', resCreate.data?.createPayrollRecipient?.errors?.[0] || 'No se pudo guardar', [{ text: 'OK' }]);
      }
    } catch (e) {
      Alert.alert('Error', 'Ocurrió un error al guardar');
    } finally {
      setLookupLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await deleteRecipient({ variables: { recipientId: id } });
      if (!res.data?.deletePayrollRecipient?.success) {
        Alert.alert('Error', res.data?.deletePayrollRecipient?.errors?.[0] || 'No se pudo eliminar', [{ text: 'OK' }]);
      } else {
        onChanged?.();
      }
    } catch (e) {
      Alert.alert('Error', 'Ocurrió un error al eliminar', [{ text: 'OK' }]);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <TouchableOpacity style={styles.backdrop} onPress={onClose} />
        <View style={styles.card}>
          <View style={styles.header}>
            <Text style={styles.title}>Destinatarios de nómina</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Icon name="x" size={20} color="#666" />
            </TouchableOpacity>
          </View>

          <View style={styles.modeToggle}>
            <TouchableOpacity
              style={[styles.modeButton, mode === 'phone' && styles.modeButtonActive]}
              onPress={() => setMode('phone')}
            >
              <Text style={[styles.modeButtonText, mode === 'phone' && styles.modeButtonTextActive]}>Teléfono</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.modeButton, mode === 'username' && styles.modeButtonActive]}
              onPress={() => setMode('username')}
            >
              <Text style={[styles.modeButtonText, mode === 'username' && styles.modeButtonTextActive]}>@Usuario</Text>
            </TouchableOpacity>
          </View>

          {mode === 'phone' ? (
            <>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>País</Text>
                <TouchableOpacity
                  style={styles.countrySelector}
                  onPress={() => selectCountry(selectedCountry || countries[0])}
                >
                  <View style={styles.countrySelectorContent}>
                    <Text style={styles.flag}>{selectedCountry?.[3] || '🌍'}</Text>
                    <Text style={styles.countryNameSelector}>{selectedCountry?.[0] || 'Seleccionar país'}</Text>
                  </View>
                  <Text style={styles.countryCode}>{selectedCountry?.[1] || '+58'}</Text>
                </TouchableOpacity>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Número de teléfono</Text>
                <View style={styles.phoneInputContainer}>
                  <View style={styles.phoneCodeContainer}>
                    <Text style={styles.phoneCode}>{selectedCountry?.[1] || '+58'}</Text>
                  </View>
                  <TextInput
                    style={styles.phoneInput}
                    placeholder="412 1234567"
                    value={phone}
                    onChangeText={setPhone}
                    keyboardType="phone-pad"
                  />
                </View>
              </View>
            </>
          ) : (
            <View style={styles.inputGroup}>
              <Text style={styles.label}>@usuario</Text>
              <View style={styles.atInputContainer}>
                <Text style={styles.atPrefix}>@</Text>
                <TextInput
                  style={styles.atInput}
                  placeholder="confio_usuario"
                  value={username.replace(/^@/, '')}
                  onChangeText={(text) => setUsername(text.replace(/^@/, ''))}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>
              <Text style={styles.helperText}>Agrega destinatario usando su @usuario de Confío.</Text>
            </View>
          )}

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Nombre a mostrar (opcional)</Text>
            <TextInput
              style={styles.input}
              placeholder="Nombre del destinatario"
              value={displayName}
              onChangeText={setDisplayName}
            />
          </View>

          <TouchableOpacity style={styles.primaryButton} onPress={handleAdd} disabled={creating || lookupLoading}>
            {creating || lookupLoading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>Guardar destinatario</Text>}
          </TouchableOpacity>

          <Text style={styles.helperFootnote}>Agrega destinatarios de nómina sin darles permisos de aprobación.</Text>
        </View>
      </View>
    </Modal>
  );
};

export default PayrollRecipientModal;

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  card: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    maxHeight: '90%',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 12,
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  closeBtn: { backgroundColor: '#f3f4f6', width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 18, fontWeight: '700', color: '#111827', letterSpacing: -0.3 },
  inputGroup: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', color: '#6b7280', marginBottom: 8, letterSpacing: 0.5 },
  input: {
    backgroundColor: '#f8f9fa',
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: '#111827',
  },
  countrySelector: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  countrySelectorContent: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  flag: { fontSize: 24 },
  countryNameSelector: { fontSize: 16, color: '#111827', fontWeight: '600' },
  countryCode: { fontSize: 16, color: '#6b7280', fontWeight: '700' },
  phoneInputContainer: { flexDirection: 'row', gap: 8 },
  phoneCodeContainer: {
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    justifyContent: 'center',
  },
  phoneCode: { fontSize: 16, color: '#111827', fontWeight: '700' },
  phoneInput: {
    flex: 1,
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: '#111827',
  },
  primaryButton: {
    backgroundColor: '#10b981',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 6,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  primaryText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  helperFootnote: { color: '#6b7280', fontSize: 12, marginTop: 12, textAlign: 'center' },
  modeToggle: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 10,
  },
  modeButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    backgroundColor: '#f8f9fa',
    alignItems: 'center',
  },
  modeButtonActive: {
    backgroundColor: '#f5f3ff',
    borderColor: '#c4b5fd',
  },
  modeButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#475569',
  },
  modeButtonTextActive: {
    color: '#6d28d9',
  },
  atInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
  },
  atPrefix: {
    fontSize: 18,
    fontWeight: '700',
    color: '#6d28d9',
  },
  atInput: {
    flex: 1,
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  helperText: {
    marginTop: 8,
    fontSize: 12,
    color: '#6b7280',
  },
});
