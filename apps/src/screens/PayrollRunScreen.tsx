import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, TextInput, Alert, ScrollView, Image, Platform, StatusBar } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { GET_PAYROLL_RECIPIENTS, CREATE_PAYROLL_RUN } from '../apollo/queries';
import Icon from 'react-native-vector-icons/Feather';
import { biometricAuthService } from '../services/biometricAuthService';
import LoadingOverlay from '../components/LoadingOverlay';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollRun'>;

type ScheduleOption = 'now' | 'weekly' | 'biweekly' | 'monthly';

const SCHEDULE_OPTIONS = [
  { key: 'now', label: 'Pagar ahora', icon: 'zap', periodSeconds: null },
  { key: 'weekly', label: 'Semanal', icon: 'calendar', periodSeconds: 604800 }, // 7 days
  { key: 'biweekly', label: 'Bisemanal', icon: 'calendar', periodSeconds: 1209600 }, // 14 days
  { key: 'monthly', label: 'Mensual', icon: 'calendar', periodSeconds: 2592000 }, // 30 days
];

export const PayrollRunScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { data, loading, refetch } = useQuery(GET_PAYROLL_RECIPIENTS, { fetchPolicy: 'cache-and-network' });
  const [createRun, { loading: creating }] = useMutation(CREATE_PAYROLL_RUN);
  const recipients = useMemo(() => data?.payrollRecipients || [], [data]);

  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [schedule, setSchedule] = useState<ScheduleOption>('now');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const tokenType = 'cUSD'; // Only cUSD supported for payroll

  const selectedSchedule = SCHEDULE_OPTIONS.find(s => s.key === schedule);

  const handleAmountChange = (id: string, value: string) => {
    setAmounts((prev) => ({ ...prev, [id]: value }));
  };

  const handleSubmit = async () => {
    if (!recipients.length) {
      Alert.alert('Sin destinatarios', 'Agrega destinatarios de nómina primero.');
      return;
    }

    // Build items with netAmount as STRING (backend expects String)
    const items = recipients
      .map((r: any) => {
        const amountStr = amounts[r.id] || '0';
        const parsed = parseFloat(amountStr.replace(',', '.'));
        return {
          recipientAccountId: r.recipientAccount.id,
          netAmount: parsed > 0 ? parsed.toString() : null, // Convert back to string for backend
        };
      })
      .filter((i) => i.netAmount !== null);

    if (!items.length) {
      Alert.alert('Ingresa montos', 'Agrega al menos un monto para pagar.');
      return;
    }

    // Require biometric authentication for creating payroll
    const authMessage = schedule === 'now'
      ? 'Autoriza la creación de nómina'
      : `Autoriza la nómina ${selectedSchedule?.label.toLowerCase()}`;

    let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (!authenticated) {
      const lockout = biometricAuthService.isLockout();
      if (lockout) {
        Alert.alert(
          'Biometría bloqueada',
          'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
          [{ text: 'OK', style: 'default' }],
        );
        return;
      }

      const shouldRetry = await new Promise<boolean>((resolve) => {
        Alert.alert(
          'Autenticación requerida',
          'Debes autenticarte para crear una nómina. Si fallaste varias veces, espera unos segundos y reintenta.',
          [
            { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
            { text: 'Reintentar', onPress: () => resolve(true) }
          ]
        );
      });

      if (shouldRetry) {
        authenticated = await biometricAuthService.authenticate(authMessage, true, true);
        if (!authenticated) {
          Alert.alert('No autenticado', 'No pudimos validar tu identidad. Intenta de nuevo en unos segundos.');
          return;
        }
      } else {
        return;
      }
    }

    try {
      setIsProcessing(true);
      setProcessingMessage('Creando nómina en blockchain…');

      const variables: any = { items, tokenType };

      // Add periodSeconds for recurring schedules
      if (selectedSchedule?.periodSeconds) {
        variables.periodSeconds = selectedSchedule.periodSeconds;
      }

      const res = await createRun({ variables });

      setIsProcessing(false);

      if (res.data?.createPayrollRun?.success) {
        const msg = schedule === 'now'
          ? 'Se guardó la nómina. Puedes proceder a firmar los pagos.'
          : `Nómina ${selectedSchedule?.label.toLowerCase()} creada. Se ejecutará automáticamente.`;
        Alert.alert('Nómina creada', msg, [
          { text: 'OK', onPress: () => navigation.goBack() },
        ]);
        refetch();
      } else {
        Alert.alert('Error', res.data?.createPayrollRun?.errors?.[0] || 'No se pudo crear la nómina');
      }
    } catch (e: any) {
      console.error('Create payroll error:', e);
      setIsProcessing(false);
      Alert.alert('Error', e?.message || 'Ocurrió un error al crear la nómina');
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

      <View style={styles.tokenBadge}>
        <Image source={require('../assets/png/cUSD.png')} style={styles.tokenLogo} />
        <Text style={styles.tokenText}>Pagar en cUSD</Text>
      </View>

      {/* Schedule Selection */}
      <Text style={[styles.label, { marginTop: 16, marginBottom: 8 }]}>Frecuencia de pago</Text>
      <View style={styles.scheduleGrid}>
        {SCHEDULE_OPTIONS.map((option) => {
          const isSelected = schedule === option.key;
          return (
            <TouchableOpacity
              key={option.key}
              style={[styles.scheduleCard, isSelected && styles.scheduleCardSelected]}
              onPress={() => setSchedule(option.key as ScheduleOption)}
              activeOpacity={0.7}
            >
              <Icon
                name={option.icon as any}
                size={20}
                color={isSelected ? '#065f46' : '#6b7280'}
              />
              <Text style={[styles.scheduleText, isSelected && styles.scheduleTextSelected]}>
                {option.label}
              </Text>
              {isSelected && (
                <View style={styles.checkMark}>
                  <Icon name="check" size={12} color="#fff" />
                </View>
              )}
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Recipients List */}
      <Text style={[styles.label, { marginTop: 16 }]}>Destinatarios</Text>
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
                <Text style={styles.amountPrefix}>cUSD</Text>
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
        style={[styles.submitButton, (creating || isProcessing) && styles.submitButtonDisabled]}
        onPress={handleSubmit}
        disabled={creating || isProcessing}
      >
        <Icon name={schedule === 'now' ? 'send' : 'repeat'} size={16} color="#fff" />
        <Text style={styles.submitText}>
          {creating || isProcessing ? 'Guardando...' : schedule === 'now' ? 'Crear nómina' : 'Programar nómina'}
        </Text>
      </TouchableOpacity>

      <LoadingOverlay visible={isProcessing} message={processingMessage} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 16, paddingBottom: 32 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    marginTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 10 : 0
  },
  backButton: { padding: 6 },
  headerTitle: { flex: 1, textAlign: 'center', fontSize: 18, fontWeight: '700', color: '#111827', marginRight: 24 },
  tokenBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: '#ecfdf3',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#a7f3d0',
    alignSelf: 'flex-start',
  },
  tokenLogo: {
    width: 20,
    height: 20,
    resizeMode: 'contain',
  },
  tokenText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#065f46',
  },
  label: {
    fontSize: 13,
    color: '#6b7280',
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  scheduleGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  scheduleCard: {
    flex: 1,
    minWidth: '47%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    backgroundColor: '#fff',
    position: 'relative',
  },
  scheduleCardSelected: {
    borderColor: '#34d399',
    backgroundColor: '#ecfdf3',
  },
  scheduleText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#6b7280',
    flex: 1,
  },
  scheduleTextSelected: {
    color: '#065f46',
  },
  checkMark: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: '#34d399',
    alignItems: 'center',
    justifyContent: 'center',
  },
  recipientRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
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
    marginTop: 20,
    backgroundColor: '#10b981',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  submitButtonDisabled: { opacity: 0.6 },
  submitText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});

export default PayrollRunScreen;
