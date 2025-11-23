import React, { useMemo, useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, Alert, SafeAreaView, ActivityIndicator } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { GET_CURRENT_BUSINESS_EMPLOYEES, GET_PAYROLL_RECIPIENTS, GET_PAYROLL_VAULT_BALANCE } from '../apollo/queries';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import PayrollRecipientModal from '../components/PayrollRecipientModal';
import { biometricAuthService } from '../services/biometricAuthService';
import { useAccount } from '../contexts/AccountContext';
import { usePayrollDelegates } from '../hooks/usePayrollDelegates';

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return 'Propietario';
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollSettings'>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

export const PayrollSettingsScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const {
    delegates,
    loading: delegatesLoading,
    isActivated,
    activatePayroll,
    refetch: refetchDelegates,
  } = usePayrollDelegates();
  const { data: vaultData, loading: vaultLoading, refetch: refetchVault } = useQuery(GET_PAYROLL_VAULT_BALANCE, {
    fetchPolicy: 'cache-and-network',
  });
  const { data, loading, refetch } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    fetchPolicy: 'cache-and-network',
  });
  const { data: recipientsData, refetch: refetchRecipients } = useQuery(GET_PAYROLL_RECIPIENTS, {
    fetchPolicy: 'cache-and-network',
  });
  const employees = useMemo(() => data?.currentBusinessEmployees || [], [data]);
  const recipients = useMemo(() => recipientsData?.payrollRecipients || [], [recipientsData]);
  const ownerUserId = useMemo(
    () => employees.find((e: any) => (e.role || '').toLowerCase() === 'owner')?.user?.id,
    [employees]
  );
  const recipientUserIds = useMemo(
    () => new Set(recipients.map((r: any) => r.recipientUser?.id).filter(Boolean)),
    [recipients]
  );
  const ownerMissingInRecipients = ownerUserId ? !recipientUserIds.has(ownerUserId) : false;
  const totalRecipients = recipients.length + (ownerMissingInRecipients ? 1 : 0);

  const [delegateMap, setDelegateMap] = useState<Record<string, boolean>>({});
  const [showRecipientsModal, setShowRecipientsModal] = useState(false);

  useEffect(() => {
    if (delegates && delegates.length) {
      const map: Record<string, boolean> = {};
      delegates.forEach((d) => { map[d.address] = true; });
      setDelegateMap(map);
    }
  }, [delegates]);
  const toggleDelegate = useCallback((id: string, name: string, current: boolean) => {
    const next = !current;
    Alert.alert(
      next ? 'Delegar nómina' : 'Revocar permiso',
      next
        ? `Concederás a ${name} permiso para aprobar y ejecutar pagos de nómina con su cuenta personal. Asegúrate de confiar en esta persona.`
        : `Revocarás el permiso de ${name} para aprobar y ejecutar nómina.`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: next ? 'Confirmar delegación' : 'Revocar delegación',
          style: next ? 'default' : 'destructive',
          onPress: async () => {
            const ok = await biometricAuthService.authenticate('Autoriza la delegación de nómina', true, true);
            if (!ok) {
              Alert.alert('Biometría requerida', 'No se pudo validar tu identidad.');
              return;
            }
            // TODO: tie into backend/on-chain delegation when available
            setDelegateMap((prev) => ({ ...prev, [id]: next }));
          },
        },
      ],
    );
  }, []);

  const handleRecipientActions = useCallback((recipient: any) => {
    navigation.navigate('PayeeDetail', {
      recipientId: recipient.id,
      displayName: recipient.displayName || recipient.recipientUser?.firstName || recipient.recipientUser?.username || 'Destinatario',
      username: recipient.recipientUser?.username,
      accountId: recipient.recipientAccount?.id || '',
      employeeRole: recipient.employeeRole,
      employeePermissions: recipient.employeeEffectivePermissions,
      onDeleted: () => refetchRecipients(),
    } as any);
  }, [navigation, refetchRecipients]);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Configuración de nómina</Text>
        <View style={{ width: 32 }} />
      </View>

      {!isActivated ? (
        <View style={styles.activationCard}>
          <Icon name="shield" size={20} color="#065f46" />
          <View style={{ flex: 1 }}>
            <Text style={styles.activationTitle}>Activa nómina</Text>
            <Text style={styles.activationSubtitle}>Añadiremos tu cuenta de negocio y la del propietario como delegados permitidos para pagar nómina.</Text>
          </View>
          <TouchableOpacity
            style={styles.activationButton}
            disabled={delegatesLoading}
            onPress={async () => {
              const ok = await biometricAuthService.authenticate('Autoriza la activación de nómina', true, true);
              if (!ok) return;
              const ownerAddr = activeAccount?.ownerAddress; // adjust if owner address stored elsewhere
              const res = await activatePayroll(ownerAddr);
              if (res.success) {
                Alert.alert('Nómina activada', 'Tu cuenta de negocio y la del propietario ya pueden pagar nómina.');
              } else if (res.error) {
                Alert.alert('Error', res.error);
              }
            }}
          >
            {delegatesLoading ? <ActivityIndicator color="#fff" /> : <Text style={styles.activationButtonText}>Activar</Text>}
          </TouchableOpacity>
        </View>
      ) : null}

      <View style={styles.infoCard}>
        <Icon name="info" size={18} color={colors.primary} style={{ marginRight: 8 }} />
        <Text style={styles.infoText}>
          Delegados de nómina: empleados que pueden aprobar y ejecutar pagos de nómina con su cuenta personal. Asigna solo a personas de confianza. Los destinatarios son solo pagados; no obtienen permisos.
        </Text>
      </View>

      <TouchableOpacity
        style={styles.secondaryButton}
        onPress={() => {
          refetchRecipients();
          setShowRecipientsModal(true);
        }}
      >
        <Icon name="users" size={16} color={colors.primary} />
        <Text style={styles.secondaryButtonText}>Destinatarios de nómina</Text>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{totalRecipients}</Text>
        </View>
      </TouchableOpacity>

      <View style={{ paddingHorizontal: 16, paddingTop: 10 }}>
        <Text style={styles.sectionHeader}>Destinatarios</Text>
        {recipients.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>Sin destinatarios</Text>
            <Text style={styles.emptySubtitle}>Agrega destinatarios de nómina con el botón superior.</Text>
          </View>
        ) : (
          recipients.map((item: any) => {
            const title = item.displayName || item.recipientUser?.firstName || item.recipientUser?.username || 'Destinatario';
            const subtitle = item.recipientUser?.username ? `@${item.recipientUser.username}` : '';
            const isEmployee = !!item.isEmployee;
            return (
              <TouchableOpacity
                key={item.id}
                style={styles.recipientCard}
                onPress={() => handleRecipientActions(item)}
                activeOpacity={0.9}
              >
                <View style={styles.recipientAvatar}>
                  <Text style={styles.recipientAvatarText}>{title.charAt(0).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{title}</Text>
                  <Text style={styles.subtext}>{subtitle}</Text>
                  <View style={[styles.badgeRow]}>
                    <Text style={[styles.pill, isEmployee ? styles.pillGreen : styles.pillGray]}>
                      {isEmployee ? 'Empleado' : 'Solo nómina'}
                    </Text>
                  </View>
                </View>
                <Icon name="chevron-right" size={18} color="#9ca3af" />
              </TouchableOpacity>
            );
          })
        )}
      </View>

      <FlatList
        data={employees}
        keyExtractor={(item: any) => item.id}
        refreshing={loading}
        onRefresh={() => refetch()}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>No hay empleados</Text>
            <Text style={styles.emptySubtitle}>Agrega empleados desde Empleados para habilitar nómina.</Text>
          </View>
        }
        renderItem={({ item }) => {
          const name = `${item.user?.firstName || ''} ${item.user?.lastName || ''}`.trim() || item.user?.username || 'Empleado';
          const role = getRoleLabel(item.role || '');
          const isDelegate = delegateMap[item.id] ?? (item.effectivePermissions?.includes?.('send_funds'));
          const isCashier = (item.role || '').toLowerCase() === 'cashier';

          return (
            <View style={styles.card}>
              <View style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{name}</Text>
                  <Text style={styles.subtext}>Rol: {role}</Text>
                  <Text style={styles.subtextMuted}>Permiso de nómina: {isDelegate ? 'Activo' : 'Inactivo'}</Text>
                </View>
                <TouchableOpacity
                  style={[styles.delegateBadge, isDelegate ? styles.delegateOn : styles.delegateOff]}
                  onPress={() => !isCashier && toggleDelegate(item.id, name, !!isDelegate)}
                  disabled={isCashier}
                  activeOpacity={0.8}
                >
                  <Text style={[styles.delegateText, isDelegate ? styles.delegateTextOn : styles.delegateTextOff]}>
                    {isDelegate ? 'Delegado' : 'Delegar'}
                  </Text>
                </TouchableOpacity>
              </View>
              <Text style={styles.subtext}>
                {isCashier
                  ? 'Cajeros no pueden aprobar nómina.'
                  : 'Permiso: aprobar y ejecutar pagos de nómina.'}
              </Text>
            </View>
          );
        }}
        contentContainerStyle={{ padding: 16 }}
      />

      <PayrollRecipientModal
        visible={showRecipientsModal}
        onClose={() => setShowRecipientsModal(false)}
        onChanged={() => refetchRecipients()}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 18,
    color: colors.text,
    fontWeight: '600',
  },
  infoCard: {
    margin: 16,
    padding: 12,
    backgroundColor: colors.bg,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
  },
  infoText: {
    flex: 1,
    color: colors.muted,
    fontSize: 13,
  },
  secondaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 16,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: '#f9fafb',
  },
  secondaryButtonText: {
    flex: 1,
    marginLeft: 8,
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  badge: {
    minWidth: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
    marginLeft: 8,
  },
  badgeText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 12,
  },
  activationCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fef3c7',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#fcd34d',
    marginHorizontal: 16,
    marginTop: 12,
    marginBottom: 12,
    gap: 10,
  },
  activationTitle: { fontSize: 15, fontWeight: '700', color: '#92400e' },
  activationSubtitle: { fontSize: 13, color: '#b45309', marginTop: 2 },
  activationButton: {
    backgroundColor: '#f59e0b',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
  },
  activationButtonText: { color: '#fff', fontWeight: '700' },
  card: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 10,
    shadowColor: '#000',
    shadowOpacity: 0.02,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  name: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  subtext: {
    fontSize: 12,
    color: colors.muted,
  },
  subtextMuted: {
    fontSize: 12,
    color: '#9ca3af',
  },
  delegateBadge: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1.5,
  },
  delegateOn: {
    borderColor: '#34d399',
    backgroundColor: '#ecfdf3',
  },
  delegateOff: {
    borderColor: '#e5e7eb',
    backgroundColor: '#f9fafb',
  },
  delegateText: { fontWeight: '700', fontSize: 13 },
  delegateTextOn: { color: '#065f46' },
  delegateTextOff: { color: '#6b7280' },
  emptyState: {
    alignItems: 'center',
    marginTop: 40,
    paddingHorizontal: 24,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  emptySubtitle: {
    marginTop: 4,
    fontSize: 13,
    color: colors.muted,
    textAlign: 'center',
  },
  sectionHeader: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
  },
  recipientCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 8,
  },
  recipientAvatar: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#ecfdf3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  recipientAvatarText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#065f46',
  },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    fontSize: 12,
    fontWeight: '700',
  },
  pillGreen: { backgroundColor: '#ecfdf3', color: '#065f46' },
  pillGray: { backgroundColor: '#f3f4f6', color: '#6b7280' },
});

export default PayrollSettingsScreen;
