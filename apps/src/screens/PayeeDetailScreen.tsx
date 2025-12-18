import React, { useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert, ScrollView, TextInput, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { useMutation, useQuery } from '@apollo/client';
import { DELETE_PAYROLL_RECIPIENT } from '../apollo/mutations/payroll';
import { GET_PAYROLL_RECIPIENTS, CREATE_PAYROLL_RUN, GET_PAYROLL_RUNS } from '../apollo/queries';

type PayeeDetailNavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayeeDetail'>;
type PayeeDetailRouteProp = RouteProp<MainStackParamList, 'PayeeDetail'>;

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

export const PayeeDetailScreen = () => {
  const navigation = useNavigation<PayeeDetailNavigationProp>();
  const route = useRoute<PayeeDetailRouteProp>();
  const { recipientId, displayName, username, onDeleted, employeeRole, employeePermissions, accountId } = route.params;

  const [deleteRecipient, { loading }] = useMutation(DELETE_PAYROLL_RECIPIENT, {
    refetchQueries: [{ query: GET_PAYROLL_RECIPIENTS }],
  });
  const { data: runsData } = useQuery(GET_PAYROLL_RUNS, { skip: !accountId });
  const [amount, setAmount] = React.useState('');
  const [interval, setInterval] = React.useState<'semanal' | 'quincenal' | 'mensual'>('mensual');
  const [startDate, setStartDate] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [createRun] = useMutation(CREATE_PAYROLL_RUN);

  const handleStartDateChange = (value: string) => {
    const digits = value.replace(/[^0-9]/g, '').slice(0, 8);
    if (digits.length <= 4) {
      setStartDate(digits);
      return;
    }
    if (digits.length <= 6) {
      setStartDate(`${digits.slice(0, 4)}-${digits.slice(4, 6)}`);
      return;
    }
    setStartDate(`${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`);
  };


  const handleRemove = useCallback(() => {
    Alert.alert(
      'Remover destinatario',
      '¿Seguro que quieres remover este destinatario de nómina?',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Remover',
          style: 'destructive',
          onPress: async () => {
            try {
              const res = await deleteRecipient({ variables: { recipientId } });
              if (!res.data?.deletePayrollRecipient?.success) {
                Alert.alert('Error', res.data?.deletePayrollRecipient?.errors?.[0] || 'No se pudo eliminar');
              } else {
                onDeleted?.();
                navigation.goBack();
              }
            } catch (e) {
              Alert.alert('Error', 'Ocurrió un error al eliminar');
            }
          },
        },
      ],
    );
  }, [deleteRecipient, navigation, onDeleted, recipientId]);

  const periodSecondsForInterval = (key: 'semanal' | 'quincenal' | 'mensual') => {
    switch (key) {
      case 'semanal': return 7 * 24 * 60 * 60;
      case 'quincenal': return 14 * 24 * 60 * 60;
      case 'mensual': return 30 * 24 * 60 * 60;
      default: return undefined;
    }
  };

  const scheduledItems = React.useMemo(() => {
    if (!runsData?.payrollRuns || !accountId) return [];
    return runsData.payrollRuns
      .flatMap((run: any) => {
        const matchItems = (run.items || []).filter((it: any) => it.recipientAccount?.id === accountId);
        return matchItems.map((it: any) => ({
          id: it.internalId,
          status: it.status,
          runStatus: run.status,
          token: run.tokenType,
          netAmount: it.netAmount,
          when: run.scheduledAt || run.createdAt,
          scheduledAt: run.scheduledAt,
        }));
      })
      // Show only scheduled items we can manage (exclude completed/cancelled)
      .filter((h: any) => {
        if (!h.scheduledAt) return false;
        const key = (h.status || '').toLowerCase();
        return key !== 'completed' && key !== 'cancelled' && key !== 'failed';
      })
      // Soonest first to manage upcoming schedule
      .sort((a: any, b: any) => (new Date(a.when || '').getTime() - new Date(b.when || '').getTime()));
  }, [runsData, accountId]);

  const statusLabel = (s: string) => {
    const key = (s || '').toLowerCase();
    switch (key) {
      case 'pending': return 'Pendiente';
      case 'prepared':
      case 'ready': return 'Listo';
      case 'submitted': return 'Enviado';
      case 'confirmed':
      case 'completed': return 'Completado';
      case 'cancelled': return 'Cancelado';
      case 'failed': return 'Fallido';
      default: return s || '—';
    }
  };

  const handleCreateRun = async (mode: 'immediate' | 'scheduled') => {
    if (!amount || parseFloat(amount) <= 0) {
      Alert.alert('Monto requerido', 'Ingresa un monto para pagar.');
      return;
    }
    if (!accountId) {
      Alert.alert('Cuenta faltante', 'No se encontró la cuenta del destinatario.');
      return;
    }
    if (mode === 'scheduled') {
      if (!startDate) {
        Alert.alert('Fecha requerida', 'Ingresa la fecha de inicio (AAAA-MM-DD).');
        return;
      }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate)) {
        Alert.alert('Formato inválido', 'Usa el formato AAAA-MM-DD (ej. 2025-01-15).');
        return;
      }
    }

    try {
      setIsSubmitting(true);
      const scheduledAt = mode === 'scheduled' ? `${startDate}T00:00:00Z` : null;
      const periodSeconds = mode === 'scheduled' ? periodSecondsForInterval(interval) : null;
      const res = await createRun({
        variables: {
          tokenType: 'CUSD',
          periodSeconds,
          scheduledAt,
          items: [{ recipientAccountId: accountId, netAmount: amount }],
        },
      });
      const payload = res.data?.createPayrollRun;
      if (!payload?.success) {
        Alert.alert('Error', payload?.errors?.[0] || 'No se pudo crear la nómina.');
        return;
      }
      Alert.alert(
        mode === 'immediate' ? 'Pago creado' : 'Pago programado',
        mode === 'immediate'
          ? 'Se creó un pago inmediato en la nómina.'
          : `Pago programado a partir de ${startDate}.`,
        [{ text: 'OK', onPress: () => navigation.goBack() }],
      );
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'No se pudo crear la nómina.');
    } finally {
      setIsSubmitting(false);
    }
  };


  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Detalle del destinatario"
        backgroundColor="#34d399"
        isLight
        showBackButton
      />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.card}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{(displayName || username || 'D').charAt(0).toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{displayName || 'Destinatario'}</Text>
            {username ? <Text style={styles.subtitle}>@{username}</Text> : null}
            <Text style={styles.meta}>Cuenta guardada para nómina</Text>
          </View>
        </View>

        <View style={styles.infoBox}>
          <Text style={styles.sectionTitle}>Información</Text>
          <View style={styles.infoRow}>
            <Icon name="user" size={16} color="#6b7280" />
            <Text style={styles.infoText}>{displayName || username || 'Destinatario'}</Text>
          </View>
          {username ? (
            <View style={styles.infoRow}>
              <Icon name="at-sign" size={16} color="#6b7280" />
              <Text style={styles.infoText}>@{username}</Text>
            </View>
          ) : null}
          <View style={styles.infoRow}>
            <Icon name="briefcase" size={16} color="#6b7280" />
            <Text style={styles.infoText}>
              {employeeRole ? `Empleado (${getRoleLabel(employeeRole)})` : 'Solo destinatario de nómina'}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Icon name="shield" size={16} color="#6b7280" />
            <Text style={styles.infoText}>
              {employeeRole ? 'Cuenta de empleado; sin permisos de nómina aquí.' : 'Solo recibe pagos de nómina.'}
            </Text>
          </View>
        </View>

        <View style={styles.payrollBox}>
          <Text style={styles.sectionTitle}>Pago de nómina</Text>
          <View style={styles.tokenRow}>
            <Image source={require('../assets/png/cUSD.png')} style={styles.tokenLogo} />
            <Text style={styles.tokenLabel}>cUSD</Text>
          </View>
          <Text style={styles.label}>Monto</Text>
          <View style={styles.amountRow}>
            <Text style={styles.amountPrefix}>cUSD</Text>
            <TextInput
              style={styles.amountInput}
              keyboardType="decimal-pad"
              placeholder="0.00"
              value={amount}
              onChangeText={setAmount}
            />
          </View>

          <Text style={[styles.label, { marginTop: 12 }]}>Pago inmediato</Text>
          <TouchableOpacity
            style={styles.immediateButton}
            disabled={isSubmitting}
            onPress={() => {
              Alert.alert(
                'Confirmar pago inmediato',
                'Se creará un pago único en cUSD para ejecutar ahora.',
                [
                  { text: 'Cancelar', style: 'cancel' },
                  { text: 'Pagar ahora', onPress: () => handleCreateRun('immediate') },
                ]
              );
            }}
          >
            <View style={styles.immediateRow}>
              <Icon name="zap" size={18} color="#fff" />
              <Text style={styles.immediateText}>{isSubmitting ? 'Creando...' : 'Pagar ahora'}</Text>
            </View>
          </TouchableOpacity>

          <Text style={[styles.label, { marginTop: 16 }]}>Frecuencia programada</Text>
          <View style={styles.intervalRow}>
            {[
              { key: 'semanal', label: 'Semanal' },
              { key: 'quincenal', label: 'Quincenal' },
              { key: 'mensual', label: 'Mensual' },
            ].map((opt) => {
              const sel = interval === opt.key;
              return (
                <TouchableOpacity
                  key={opt.key}
                  style={[styles.intervalChip, sel && styles.intervalChipSelected]}
                  onPress={() => setInterval(opt.key as any)}
                >
                  <Text style={[styles.intervalText, sel && styles.intervalTextSelected]}>{opt.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={[styles.label, { marginTop: 12 }]}>Fecha de inicio</Text>
          <TextInput
            style={styles.dateInput}
            placeholder="AAAA-MM-DD"
            value={startDate}
            onChangeText={handleStartDateChange}
            keyboardType="number-pad"
            maxLength={10}
            autoCapitalize="none"
          />

          <TouchableOpacity
            style={styles.scheduleButton}
            disabled={isSubmitting}
            onPress={() => {
              Alert.alert(
                'Confirmar pago',
                'Programaremos este pago en cUSD con la frecuencia seleccionada.',
                [
                  { text: 'Cancelar', style: 'cancel' },
                  { text: 'Continuar', onPress: () => handleCreateRun('scheduled') },
                ]
              );
            }}
          >
            <Text style={styles.scheduleText}>{isSubmitting ? 'Guardando...' : 'Programar pago'}</Text>
          </TouchableOpacity>

          <View style={styles.historyBox}>
            <View style={styles.historyHeader}>
              <Text style={styles.sectionTitle}>Programaciones activas</Text>
              <Text style={styles.historyCount}>{scheduledItems.length} reg.</Text>
            </View>
            {scheduledItems.length === 0 ? (
              <Text style={styles.historyEmpty}>No hay pagos programados próximamente.</Text>
            ) : (
              scheduledItems.map((h: any) => (
                <View key={h.id} style={styles.historyCard}>
                  <View style={styles.historyRow}>
                    <View>
                      <Text style={styles.historyAmount}>cUSD {h.netAmount}</Text>
                      <Text style={styles.historyDate}>{new Date(h.when).toLocaleDateString()}</Text>
                    </View>
                    <View style={styles.historyBadges}>
                      <View style={[styles.badge, styles.badgeSecondary]}>
                        <Text style={styles.badgeText}>Programado</Text>
                      </View>
                      <View style={[styles.badge, styles.badgeMuted]}>
                        <Text style={styles.badgeText}>{statusLabel(h.status)}</Text>
                      </View>
                    </View>
                  </View>
                  <View style={styles.historyMetaRow}>
                    <Text style={styles.historyMeta}>Estado corrida: {statusLabel(h.runStatus)}</Text>
                    <Text style={styles.historyMeta}>Monto neto programado</Text>
                  </View>
                </View>
              ))
            )}
            <TouchableOpacity
              style={styles.fullHistoryButton}
              onPress={() => navigation.navigate('PayrollHistory', { accountId, displayName, username } as any)}
            >
              <Text style={styles.fullHistoryText}>Ver historial de pagos</Text>
              <Icon name="chevron-right" size={16} color="#047857" />
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.actions}>
          <TouchableOpacity style={[styles.actionButton, styles.dangerButton]} onPress={handleRemove}>
            <Icon name="trash-2" size={18} color="#b91c1c" />
            <Text style={[styles.actionText, { color: '#b91c1c' }]}>{loading ? 'Removiendo...' : 'Remover destinatario'}</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 20, gap: 20, paddingTop: 12 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: '#ecfdf3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  avatarText: { fontSize: 20, fontWeight: '700', color: '#065f46' },
  title: { fontSize: 18, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 14, color: '#6b7280', marginTop: 2 },
  meta: { fontSize: 12, color: '#9ca3af', marginTop: 4 },
  infoBox: {
    backgroundColor: '#f9fafb',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    padding: 14,
    gap: 8,
  },
  sectionTitle: { fontSize: 14, fontWeight: '700', color: '#111827' },
  infoRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  infoText: { fontSize: 14, color: '#111827', flex: 1 },
  permsBox: {
    marginTop: 8,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderRadius: 10,
    overflow: 'hidden',
  },
  permRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  permKey: { fontSize: 13, color: '#374151', flex: 1 },
  permValue: { fontSize: 13, fontWeight: '700', minWidth: 30, textAlign: 'right' },
  payrollBox: {
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    padding: 14,
    gap: 10,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  tokenRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tokenLogo: { width: 24, height: 24, resizeMode: 'contain' },
  tokenLabel: { fontSize: 14, fontWeight: '700', color: '#111827' },
  label: { fontSize: 13, color: '#6b7280', fontWeight: '600', letterSpacing: 0.4 },
  amountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 10,
    gap: 8,
  },
  amountPrefix: { fontSize: 14, fontWeight: '700', color: '#6b7280' },
  amountInput: { flex: 1, fontSize: 16, fontWeight: '700', color: '#111827' },
  intervalRow: { flexDirection: 'row', gap: 8, marginTop: 6 },
  intervalChip: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    backgroundColor: '#f9fafb',
  },
  intervalChipSelected: { borderColor: '#34d399', backgroundColor: '#ecfdf3' },
  intervalText: { fontSize: 14, fontWeight: '600', color: '#111827' },
  intervalTextSelected: { color: '#065f46' },
  dateInput: {
    marginTop: 6,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    fontWeight: '600',
    color: '#111827',
  },
  immediateButton: {
    marginTop: 6,
    backgroundColor: '#10b981',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    alignItems: 'center',
  },
  immediateRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  immediateText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  scheduleButton: {
    marginTop: 10,
    backgroundColor: '#10b981',
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
  },
  scheduleText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  actions: { gap: 12 },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    alignSelf: 'flex-start',
    minWidth: 0,
  },
  actionText: { fontSize: 15, fontWeight: '700', color: '#111827' },
  dangerButton: { borderColor: '#fecdd3', backgroundColor: '#fef2f2' },
  historyBox: {
    marginTop: 12,
    padding: 0,
    gap: 10,
  },
  historyHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  historyCount: { fontSize: 12, color: '#6b7280' },
  historyEmpty: { fontSize: 13, color: '#9ca3af' },
  historyRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  historyCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    padding: 12,
    marginTop: 6,
  },
  historyAmount: { fontSize: 14, fontWeight: '700', color: '#111827' },
  historyDate: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  historyBadges: { flexDirection: 'row', gap: 6 },
  historyMetaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  historyMeta: { fontSize: 12, color: '#6b7280' },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10,
  },
  badgeText: { fontSize: 11, fontWeight: '700', color: '#111827' },
  badgeSecondary: { backgroundColor: '#e0f2fe' },
  badgeMuted: { backgroundColor: '#f3f4f6' },
  fullHistoryButton: {
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
  },
  fullHistoryText: { color: '#047857', fontWeight: '700' },
});

export default PayeeDetailScreen;
