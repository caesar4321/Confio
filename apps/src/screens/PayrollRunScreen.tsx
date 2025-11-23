import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, TextInput, Alert, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { GET_PAYROLL_RECIPIENTS, CREATE_PAYROLL_RUN } from '../apollo/queries';
import Icon from 'react-native-vector-icons/Feather';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollRun'>;

export const PayrollRunScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { data, loading, refetch } = useQuery(GET_PAYROLL_RECIPIENTS, { fetchPolicy: 'cache-and-network' });
  const [createRun, { loading: creating }] = useMutation(CREATE_PAYROLL_RUN);
  const recipients = useMemo(() => data?.payrollRecipients || [], [data]);

  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [tokenType, setTokenType] = useState<'CUSD' | 'USDC'>('CUSD');

  const handleAmountChange = (id: string, value: string) => {
    setAmounts((prev) => ({ ...prev, [id]: value }));
  };

  const handleSubmit = async () => {
    if (!recipients.length) {
      Alert.alert('Sin destinatarios', 'Agrega destinatarios de nómina primero.');
      return;
    }
    const items = recipients
      .map((r: any) => ({
        recipientAccountId: r.recipientAccount.id,
        netAmount: parseFloat(amounts[r.id] || '0'),
      }))
      .filter((i) => i.netAmount > 0);

    if (!items.length) {
      Alert.alert('Ingresa montos', 'Agrega al menos un monto para pagar.');
      return;
    }

    try {
      const res = await createRun({ variables: { items, tokenType } });
      if (res.data?.createPayrollRun?.success) {
        Alert.alert('Nómina creada', 'Se guardó la nómina. Puedes proceder a firmar los pagos.', [
          { text: 'OK', onPress: () => navigation.goBack() },
        ]);
        refetch();
      } else {
        Alert.alert('Error', res.data?.createPayrollRun?.errors?.[0] || 'No se pudo crear la nómina');
      }
    } catch (e) {
      Alert.alert('Error', 'Ocurrió un error al crear la nómina');
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={22} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Nueva nómina</Text>
      </View>

      <View style={styles.tokenRow}>
        <Text style={styles.label}>Token</Text>
        <View style={styles.tokenChips}>
          {['CUSD', 'USDC'].map((tok) => {
            const sel = tokenType === tok;
            return (
              <TouchableOpacity
                key={tok}
                style={[styles.tokenChip, sel && styles.tokenChipSelected]}
                onPress={() => setTokenType(tok as 'CUSD' | 'USDC')}
              >
                <Text style={[styles.tokenChipText, sel && styles.tokenChipTextSelected]}>{tok}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </View>

      <Text style={[styles.label, { marginTop: 10 }]}>Destinatarios</Text>
      <FlatList
        data={recipients}
        keyExtractor={(item: any) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => {
          const name =
            item.displayName ||
            `${item.recipientUser?.firstName || ''} ${item.recipientUser?.lastName || ''}`.trim() ||
            item.recipientUser?.username ||
            'Destinatario';
          return (
            <View style={styles.recipientRow}>
              <View style={styles.recipientInfo}>
                <Text style={styles.recipientName}>{name}</Text>
                {item.recipientUser?.username ? (
                  <Text style={styles.recipientMeta}>@{item.recipientUser.username}</Text>
                ) : null}
              </View>
              <View style={styles.amountInputWrap}>
                <Text style={styles.amountPrefix}>{tokenType}</Text>
                <TextInput
                  style={styles.amountInput}
                  keyboardType="decimal-pad"
                  placeholder="0.00"
                  value={amounts[item.id] || ''}
                  onChangeText={(t) => handleAmountChange(item.id, t)}
                />
              </View>
            </View>
          );
        }}
      />

      <TouchableOpacity
        style={[styles.submitButton, creating && styles.submitButtonDisabled]}
        onPress={handleSubmit}
        disabled={creating}
      >
        <Text style={styles.submitText}>{creating ? 'Guardando...' : 'Crear nómina'}</Text>
      </TouchableOpacity>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 16 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  backButton: { padding: 6 },
  headerTitle: { flex: 1, textAlign: 'center', fontSize: 18, fontWeight: '700', color: '#111827', marginRight: 24 },
  tokenRow: { marginBottom: 12 },
  label: { fontSize: 13, color: '#6b7280', fontWeight: '600', letterSpacing: 0.5 },
  tokenChips: { flexDirection: 'row', gap: 8, marginTop: 8 },
  tokenChip: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    backgroundColor: '#f8f9fa',
  },
  tokenChipSelected: { borderColor: '#34d399', backgroundColor: '#ecfdf3' },
  tokenChipText: { fontSize: 14, fontWeight: '700', color: '#374151' },
  tokenChipTextSelected: { color: '#065f46' },
  recipientRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  recipientInfo: { flex: 1, marginRight: 10 },
  recipientName: { fontSize: 15, fontWeight: '700', color: '#111827' },
  recipientMeta: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  amountInputWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 6,
    minWidth: 140,
  },
  amountPrefix: { fontSize: 13, fontWeight: '700', color: '#6b7280', marginRight: 6 },
  amountInput: { flex: 1, fontSize: 15, fontWeight: '600', color: '#111827' },
  submitButton: {
    marginTop: 16,
    backgroundColor: '#10b981',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  submitButtonDisabled: { opacity: 0.6 },
  submitText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});

export default PayrollRunScreen;
