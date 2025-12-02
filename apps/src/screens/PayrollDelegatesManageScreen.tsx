import React, { useMemo, useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, SafeAreaView, FlatList, Alert, ActivityIndicator, Modal, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useQuery, useMutation, gql } from '@apollo/client';
import { GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';
import { usePayrollDelegates } from '../hooks/usePayrollDelegates';
import { useAccount } from '../contexts/AccountContext';
import { biometricAuthService } from '../services/biometricAuthService';
import algorandService from '../services/algorandService';
import { Buffer } from 'buffer';

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

const SET_BUSINESS_DELEGATES_BY_EMPLOYEE = gql`
  mutation SetBusinessDelegatesByEmployee(
    $businessAccount: String!
    $addEmployeeIds: [ID!]!
    $removeEmployeeIds: [ID!]!
    $signedTransaction: String
  ) {
    setBusinessDelegatesByEmployee(
      businessAccount: $businessAccount
      addEmployeeIds: $addEmployeeIds
      removeEmployeeIds: $removeEmployeeIds
      signedTransaction: $signedTransaction
    ) {
      success
      errors
      unsignedTransactionB64
      transactionHash
    }
  }
`;

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return 'Propietario';
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

export const PayrollDelegatesManageScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const { data, loading, refetch } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    fetchPolicy: 'cache-and-network',
  });
  const { delegates, loading: delegatesLoading, refetch: refetchDelegates } = usePayrollDelegates();
  const [mutateDelegates, { loading: mutating }] = useMutation(SET_BUSINESS_DELEGATES_BY_EMPLOYEE);
  const [delegateMap, setDelegateMap] = useState<Record<string, boolean>>({});
  const [signingModalVisible, setSigningModalVisible] = useState(false);

  const employees = useMemo(() => data?.currentBusinessEmployees || [], [data]);

  useEffect(() => {
    console.log('[Delegates Debug] delegates list:', delegates);
    console.log('[Delegates Debug] employees count:', employees.length);

    const map: Record<string, boolean> = {};
    employees.forEach((e: any) => {
      // Parse permissions to detect delegated status even if address is missing
      const rawPerms = e.effectivePermissions || e.permissions;
      let hasSendFunds = false;
      if (rawPerms) {
        if (typeof rawPerms === 'string') {
          try {
            const parsed = JSON.parse(rawPerms);
            hasSendFunds = !!parsed?.send_funds || !!parsed?.sendFunds;
          } catch {
            hasSendFunds = rawPerms.includes?.('send_funds') || rawPerms.includes?.('sendFunds');
          }
        } else if (typeof rawPerms === 'object') {
          hasSendFunds = !!(rawPerms.send_funds ?? rawPerms.sendFunds);
        }
      }

      // Find personal account address
      const personalAccount = e.user?.accounts?.find(
        (a: any) => a.accountType === 'personal' || a.account_type === 'personal'
      );
      const address = personalAccount?.algorandAddress;

      console.log(`[Delegates Debug] Employee ${e.user?.firstName} ${e.user?.lastName}:`, {
        personalAccount,
        address,
        accounts: e.user?.accounts,
        accountsDetail: JSON.stringify(e.user?.accounts, null, 2),
      });

      // Normalize addresses to uppercase for comparison
      const normalizedAddress = address?.trim().toUpperCase();
      const normalizedDelegates = delegates.map((d: string) => d?.trim().toUpperCase());

      // Check if address is in delegates list
      const role = (e.role || '').toLowerCase();
      const isDelegate = role === 'owner' || hasSendFunds || (normalizedAddress && normalizedDelegates.includes(normalizedAddress));

      console.log(`[Delegates Debug] ${e.user?.firstName}: isDelegate=${isDelegate}, address=${normalizedAddress}, delegates=${normalizedDelegates.join(', ')}`);

      // Owner is always a delegate, but should be in the list anyway.
      // We rely on the list from the blockchain.
      map[e.id] = !!isDelegate;
    });
    setDelegateMap(map);
  }, [employees, delegates]);

  const toggleDelegate = useCallback(async (employeeId: string, name: string, current: boolean) => {
    const target = employees.find((e: any) => e.id === employeeId);
    if ((target?.role || '').toLowerCase() === 'owner') {
      Alert.alert('No permitido', 'El propietario siempre mantiene permiso de nómina.');
      return;
    }
    const next = !current;
    const ok = await biometricAuthService.authenticate(
      next ? 'Autoriza la delegación de nómina (igual que tu primer ingreso a Confío)' : 'Autoriza la revocación de nómina',
      true,
      true
    );
    if (!ok) {
      Alert.alert('Biometría requerida', 'No se pudo validar tu identidad.');
      return;
    }
    const businessAddr = activeAccount?.algorandAddress || (activeAccount as any)?.address;
    if (!businessAddr) {
      Alert.alert('Error', 'No se encontró la dirección de la cuenta de negocio.');
      return;
    }
    setSigningModalVisible(true);
    try {
      // Step 1: Prepare transaction
      const prepRes = await mutateDelegates({
        variables: {
          businessAccount: businessAddr,
          addEmployeeIds: next ? [employeeId] : [],
          removeEmployeeIds: next ? [] : [employeeId],
          signedTransaction: null,
        },
      });
      const prepData = prepRes.data?.setBusinessDelegatesByEmployee;
      const unsignedB64 = prepData?.unsignedTransactionB64;
      if (!prepData?.success || !unsignedB64) {
        const msg = prepData?.errors?.filter(Boolean).join('\n') || 'No se pudo preparar la delegación.';
        Alert.alert('Error', msg);
        return;
      }
      // Step 2: Sign transaction
      const unsignedBytes = Uint8Array.from(Buffer.from(unsignedB64, 'base64'));
      const signedBytes = await algorandService.signTransactionBytes(unsignedBytes);
      const signedB64 = Buffer.from(signedBytes).toString('base64');
      // Step 3: Submit transaction
      const submitRes = await mutateDelegates({
        variables: {
          businessAccount: businessAddr,
          addEmployeeIds: next ? [employeeId] : [],
          removeEmployeeIds: next ? [] : [employeeId],
          signedTransaction: signedB64,
        },
      });
      const submitData = submitRes.data?.setBusinessDelegatesByEmployee;
      if (!submitData?.success) {
        const msg = submitData?.errors?.filter(Boolean).join('\n') || 'No se pudo actualizar la delegación.';
        Alert.alert('Error', msg);
        return;
      }
      setDelegateMap((prev) => ({ ...prev, [employeeId]: next }));
      // Wait for blockchain to settle before refetching (5 seconds to ensure confirmation)
      setTimeout(() => {
        refetchDelegates();
      }, 5000);
      Alert.alert('Éxito', next ? `${name} ahora puede aprobar nómina.` : `Se revocó el permiso de ${name}.`);
    } catch (e: any) {
      console.error('toggleDelegate error', e);
      Alert.alert('Error', e?.message || 'No se pudo actualizar la delegación.');
    } finally {
      setSigningModalVisible(false);
    }
  }, [activeAccount, employees, mutateDelegates, refetchDelegates]);



  const eligibleEmployees = useMemo(() => {
    return employees.filter((e: any) => {
      const role = (e.role || '').toLowerCase();
      return role !== 'cashier';
    });
  }, [employees]);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Delegados</Text>
        <View style={{ width: 32 }} />
      </View>

      <View style={styles.infoCard}>
        <Icon name="info" size={16} color={colors.muted} />
        <Text style={styles.infoText}>
          Los delegados pueden aprobar y ejecutar pagos de nómina. Solo delega a personas de confianza.
        </Text>
      </View>

      <View style={styles.warningCard}>
        <Icon name="alert-triangle" size={18} color="#f59e0b" />
        <Text style={styles.warningText}>
          Los delegados tendrán poder para ejecutar pagos desde la bóveda de nómina.
        </Text>
      </View>

      <Modal visible={signingModalVisible} transparent animationType="fade">
        <View style={styles.blockerOverlay}>
          <View style={styles.blockerCard}>
            <Image source={require('../assets/png/CONFIO.png')} style={styles.blockerLogo} />
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.blockerText}>Firmando en Confío…</Text>
            <Text style={styles.blockerSubtext}>No cierres esta pantalla hasta que terminemos.</Text>
          </View>
        </View>
      </Modal>

      <FlatList
        data={eligibleEmployees}
        keyExtractor={(item: any) => item.id}
        refreshing={loading || delegatesLoading}
        onRefresh={() => {
          refetch();
          refetchDelegates();
        }}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Icon name="shield" size={48} color={colors.muted} />
            <Text style={styles.emptyTitle}>No hay empleados elegibles</Text>
            <Text style={styles.emptySubtitle}>
              Agrega empleados (excepto cajeros) para asignarlos como delegados de nómina.
            </Text>
          </View>
        }
        renderItem={({ item }) => {
          const name = `${item.user?.firstName || ''} ${item.user?.lastName || ''}`.trim() || item.user?.username || 'Empleado';
          const role = getRoleLabel(item.role || '');
          const isDelegate = delegateMap[item.id] ?? false;
          const isCashier = (item.role || '').toLowerCase() === 'cashier';
          const isOwner = (item.role || '').toLowerCase() === 'owner';
          const canToggle = !isCashier && !isOwner;

          return (
            <View style={styles.employeeCard}>
              <View style={styles.employeeInfo}>
                <View style={styles.employeeAvatar}>
                  <Text style={styles.employeeAvatarText}>{name.charAt(0).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.employeeName}>{name}</Text>
                  <Text style={styles.employeeRole}>{role}</Text>
                  {isDelegate ? (
                    <Text style={styles.employeeStatus}>Puede aprobar y ejecutar nómina</Text>
                  ) : (
                    <Text style={styles.employeeStatusInactive}>Sin permisos de nómina</Text>
                  )}
                </View>
              </View>
              <TouchableOpacity
                style={[styles.toggleButton, isDelegate ? styles.toggleButtonOn : styles.toggleButtonOff]}
                onPress={() => canToggle && toggleDelegate(item.id, name, isDelegate)}
                disabled={!canToggle || mutating}
                activeOpacity={0.7}
              >
                {mutating ? (
                  <ActivityIndicator size="small" color={isDelegate ? '#065f46' : '#6b7280'} />
                ) : (
                  <Text style={[styles.toggleButtonText, isDelegate ? styles.toggleButtonTextOn : styles.toggleButtonTextOff]}>
                    {isDelegate ? 'Delegado' : 'Delegar'}
                  </Text>
                )}
              </TouchableOpacity>
              {isCashier ? (
                <Text style={styles.employeeStatusInactive}>Cajeros no pueden delegarse.</Text>
              ) : isOwner ? (
                <Text style={styles.employeeStatusInactive}>El propietario siempre mantiene el permiso.</Text>
              ) : null}
            </View>
          );
        }}
        contentContainerStyle={styles.listContent}
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
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    margin: 16,
    marginBottom: 8,
    padding: 12,
    backgroundColor: colors.bg,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  warningCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginHorizontal: 16,
    marginBottom: 8,
    padding: 12,
    backgroundColor: '#fffbeb',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#fcd34d',
  },
  warningText: {
    flex: 1,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 18,
  },
  listContent: {
    padding: 16,
  },
  employeeCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    marginBottom: 10,
    shadowColor: '#000',
    shadowOpacity: 0.02,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  employeeInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 10,
  },
  employeeAvatar: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#ecfdf3',
    alignItems: 'center',
    justifyContent: 'center',
  },
  employeeAvatarText: {
    fontSize: 18,
    fontWeight: '700',
    color: '#065f46',
  },
  employeeName: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  employeeRole: {
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },
  employeeStatus: {
    fontSize: 12,
    color: colors.primary,
    marginTop: 4,
    fontWeight: '600',
  },
  employeeStatusInactive: {
    fontSize: 12,
    color: colors.muted,
    marginTop: 4,
  },
  toggleButton: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1.5,
    alignItems: 'center',
    minHeight: 42,
    justifyContent: 'center',
  },
  toggleButtonOn: {
    borderColor: colors.primary,
    backgroundColor: '#ecfdf3',
  },
  toggleButtonOff: {
    borderColor: colors.border,
    backgroundColor: colors.bg,
  },
  toggleButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  toggleButtonTextOn: {
    color: '#065f46',
  },
  toggleButtonTextOff: {
    color: colors.muted,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.muted,
    textAlign: 'center',
    marginTop: 8,
  },
  blockerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  blockerCard: {
    width: '100%',
    alignItems: 'center',
    padding: 24,
    borderRadius: 16,
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOpacity: 0.2,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
    gap: 10,
  },
  blockerLogo: { width: 64, height: 64, resizeMode: 'contain' },
  blockerText: { fontSize: 16, fontWeight: '700', color: colors.text },
  blockerSubtext: { fontSize: 13, color: colors.muted, textAlign: 'center' },
});

export default PayrollDelegatesManageScreen;
