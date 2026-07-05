import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, TextInput, Alert, ScrollView, Image, Platform, StatusBar } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { GET_PAYROLL_RECIPIENTS, CREATE_PAYROLL_RUN } from '../apollo/queries';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { biometricAuthService } from '../services/biometricAuthService';
import LoadingOverlay from '../components/LoadingOverlay';
import { APP_LAYOUT } from '../config/layout';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { EmptyState } from '../components/EmptyState';

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
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
  const [schedule, setSchedule] = useState<ScheduleOption>('now');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const tokenType = 'cUSD'; // Only cUSD supported for payroll

  const selectedSchedule = SCHEDULE_OPTIONS.find(s => s.key === schedule);

  // Running total — typing amounts without seeing the sum invites mistakes.
  const { totalAmount, payeeCount } = useMemo(() => {
    let total = 0;
    let count = 0;
    recipients.forEach((r: any) => {
      const parsed = parseFloat((amounts[r.id] || '').replace(',', '.'));
      if (isFinite(parsed) && parsed > 0) {
        total += parsed;
        count += 1;
      }
    });
    return { totalAmount: total, payeeCount: count };
  }, [recipients, amounts]);

  const handleAmountChange = (id: string, value: string) => {
    setAmounts((prev) => ({ ...prev, [id]: value }));
  };

  const handleSubmit = async () => {
    if (!recipients.length) {
      setBanner({ variant: 'error', message: 'Agrega destinatarios de nómina primero.' });
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
      setBanner({ variant: 'error', message: 'Ingresa al menos un monto para pagar.' });
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
          [{ text: 'Entendido', style: 'default' }],
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
          { text: 'Entendido', onPress: () => navigation.goBack() },
        ]);
        refetch();
      } else {
        setBanner({ variant: 'error', message: res.data?.createPayrollRun?.errors?.[0] || 'No se pudo crear la nómina' });
      }
    } catch (e: any) {
      setIsProcessing(false);
      setBanner({ variant: 'error', message: e?.message || 'Ocurrió un error al crear la nómina' });
    }
  };

  return (
    <View style={styles.container}>
    <Header
      navigation={navigation as any}
      title="Nueva nómina"
      backgroundColor={colors.white}
      showBackButton
    />
    <ScrollView contentContainerStyle={styles.content}>
      {banner && (
        <InlineBanner
          message={banner.message}
          variant={banner.variant}
          onDismiss={dismissBanner}
          style={{ marginTop: 8 }}
        />
      )}

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
                color={isSelected ? colors.primaryDark : colors.text.secondary}
              />
              <Text style={[styles.scheduleText, isSelected && styles.scheduleTextSelected]}>
                {option.label}
              </Text>
              {isSelected && (
                <View style={styles.checkMark}>
                  <Icon name="check" size={12} color={colors.white} />
                </View>
              )}
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Recipients List */}
      <Text style={[styles.label, { marginTop: 16 }]}>Destinatarios</Text>
      {!loading && recipients.length === 0 && (
        <EmptyState
          icon="users"
          title="Sin destinatarios"
          subtitle="Agrega a las personas que recibirán la nómina."
          actionLabel="Agregar destinatarios"
          onAction={() => navigation.navigate('PayrollRecipientsManage')}
        />
      )}
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

      {payeeCount > 0 && (
        <View style={styles.totalRow}>
          <Text style={styles.totalLabel}>
            Total · {payeeCount} {payeeCount === 1 ? 'persona' : 'personas'}
          </Text>
          <Text style={styles.totalValue}>{totalAmount.toFixed(2)} cUSD</Text>
        </View>
      )}

      <Button
        title={schedule === 'now' ? 'Crear nómina' : 'Programar nómina'}
        onPress={handleSubmit}
        loading={creating || isProcessing}
        icon={<Icon name={schedule === 'now' ? 'send' : 'repeat'} size={16} color={colors.white} />}
        style={{ marginTop: 20 }}
        textStyle={{ fontWeight: '700' }}
      />

      <LoadingOverlay visible={isProcessing} message={processingMessage} />
    </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.white },
  content: { padding: 16, paddingBottom: 32 },
  tokenBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: colors.primarySoft,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.primaryLight,
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
    color: colors.primaryDark,
  },
  label: {
    fontSize: 13,
    color: colors.text.secondary,
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
    borderColor: colors.border,
    backgroundColor: colors.white,
    position: 'relative',
  },
  scheduleCardSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  scheduleText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.secondary,
    flex: 1,
  },
  scheduleTextSelected: {
    color: colors.primaryDark,
  },
  checkMark: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  totalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 16,
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    borderWidth: 1,
    borderColor: colors.primaryLight,
  },
  totalLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  totalValue: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  recipientRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  recipientInfo: { flex: 1, marginRight: 10 },
  recipientName: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  recipientMeta: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  amountInputWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 6,
    minWidth: 140,
  },
  amountPrefix: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginRight: 6 },
  amountInput: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.text.primary },
});

export default PayrollRunScreen;
