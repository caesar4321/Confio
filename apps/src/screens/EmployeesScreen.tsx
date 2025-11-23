import React, { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Platform, Modal, Image, RefreshControl, ActivityIndicator, SectionList, Alert, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useApolloClient, useMutation, useQuery, gql } from '@apollo/client';
import { INVITE_EMPLOYEE, GET_CURRENT_BUSINESS_EMPLOYEES, GET_CURRENT_BUSINESS_INVITATIONS, CANCEL_INVITATION, GET_PAYROLL_RECIPIENTS } from '../apollo/queries';
import { InviteEmployeeModal } from '../components/InviteEmployeeModal';
import { getCountryByIso } from '../utils/countries';

type EmployeesScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  violet: '#8b5cf6',
};

const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1];
      const codeDigits = countryCode.replace('+', '');
      const phoneDigits = phoneNumber.replace(/\D/g, '');
      const localDigits = phoneDigits.startsWith(codeDigits)
        ? phoneDigits.slice(codeDigits.length)
        : phoneDigits;
      return `${countryCode} ${localDigits}`;
    }
  }
  return phoneNumber;
};

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return 'Propietario';
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

const EmployeeCard = memo(({ employee, onPress, onActions }: any) => {
  const initialSource = employee?.user?.firstName || employee?.user?.username || 'E';
  const avatarInitial = typeof initialSource === 'string' && initialSource.length > 0
    ? initialSource.charAt(0).toUpperCase()
    : 'E';
  const displayName =
    `${employee?.user?.firstName || ''} ${employee?.user?.lastName || ''}`.trim() ||
    employee?.user?.username ||
    'Empleado';

  return (
    <TouchableOpacity style={styles.employeeCard} onPress={() => onPress(employee)}>
      <View style={styles.avatarContainer}>
        <Text style={styles.avatarText}>{avatarInitial}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.employeeName}>{displayName}</Text>
        <Text style={styles.employeeRole}>{getRoleLabel(employee?.role)}</Text>
        <Text style={styles.employeePhone}>{formatPhoneNumber(employee?.user?.phoneNumber, employee?.user?.phoneCountry)}</Text>
      </View>
      <TouchableOpacity style={styles.moreButton} onPress={() => onActions(employee)}>
        <Icon name="more-vertical" size={20} color="#6b7280" />
      </TouchableOpacity>
    </TouchableOpacity>
  );
});

export const EmployeesScreen = () => {
  const navigation = useNavigation<EmployeesScreenNavigationProp>();
  const { activeAccount } = useAccount();
  const apolloClient = useApolloClient();
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  const isBusinessAccount = activeAccount?.type === 'business';

  // Queries
  const { data: employeesData, loading: employeesLoading, error: employeesError, refetch: refetchEmployees, fetchMore } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network'
  });
  const { data: invitationsData, loading: invitationsLoading, refetch: refetchInvitations } = useQuery(GET_CURRENT_BUSINESS_INVITATIONS, {
    variables: { status: 'pending' },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network'
  });
  const { data: payrollRecipientsData } = useQuery(GET_PAYROLL_RECIPIENTS, {
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network'
  });
  const [cancelInvitation] = useMutation(CANCEL_INVITATION);

  const employees = useMemo(() => employeesData?.currentBusinessEmployees || [], [employeesData]);
  const invitations = useMemo(() => invitationsData?.currentBusinessInvitations || [], [invitationsData]);
  const payrollRecipients = useMemo(() => payrollRecipientsData?.payrollRecipients || [], [payrollRecipientsData]);

  const filteredEmployees = useMemo(() => {
    if (!searchTerm) return employees;
    const lower = searchTerm.toLowerCase();
    return employees.filter((emp: any) =>
      (emp.user?.firstName || '').toLowerCase().includes(lower) ||
      (emp.user?.lastName || '').toLowerCase().includes(lower) ||
      (emp.user?.username || '').toLowerCase().includes(lower)
    );
  }, [employees, searchTerm]);

  const handleEmployeeActions = useCallback((emp: any) => {
    Alert.alert(
      'Acciones del empleado',
      `${emp.user?.firstName || ''} ${emp.user?.lastName || ''}`.trim() || emp.user?.username || 'Empleado',
      [
        { text: 'Ver detalles', onPress: () => navigation.navigate('EmployeeDetail', { employeeId: emp.id, employeeData: emp } as any) },
        { text: 'Cerrar', style: 'cancel' },
      ]
    );
  }, [navigation]);

  const handleInvite = () => setShowInviteModal(true);

  const handleCancelInvitation = async (invitationId: string) => {
    try {
      const result = await cancelInvitation({ variables: { invitationId } });
      const success = result.data?.cancelInvitation?.success;
      const errorMsg = result.data?.cancelInvitation?.errors?.[0];
      if (!success) {
        Alert.alert('Error', errorMsg || 'No se pudo cancelar la invitación');
        return;
      }
      Alert.alert('Éxito', 'Invitación cancelada correctamente.');
      refetchInvitations();
    } catch (e) {
      console.error('Error canceling invitation:', e);
      Alert.alert('Error', 'No se pudo cancelar la invitación');
    }
  };

  const renderHeader = () => (
    <View style={styles.headerWrap}>
      <View style={styles.heroCard}>
        <View style={styles.heroIcon}>
          <Icon name="users" size={20} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.heroTitle}>Empleados</Text>
          <Text style={styles.heroSubtitle}>Administra tu equipo y permisos de nómina.</Text>
        </View>
      </View>

      <View style={styles.actionRow}>
        <TouchableOpacity style={styles.actionButton} onPress={handleInvite}>
          <View style={styles.actionIconContainer}>
            <Icon name="user-plus" size={18} color="#fff" />
          </View>
          <View style={styles.actionTextContainer}>
            <Text style={styles.actionButtonTitle}>Añadir empleado</Text>
            <Text style={styles.actionButtonSubtitle}>Gestiona tu equipo de trabajo</Text>
          </View>
          <Icon name="chevron-right" size={18} color="#9ca3af" />
        </TouchableOpacity>

        <TouchableOpacity 
          style={[styles.actionButton, { borderColor: '#ebe9fe', backgroundColor: '#f5f3ff' }]}
          onPress={() => navigation.navigate('PayrollSettings' as any)}
        >
          <View style={[styles.actionIconContainer, { backgroundColor: '#8B5CF6' }]}>
            <Icon name="settings" size={18} color="#fff" />
          </View>
          <View style={styles.actionTextContainer}>
            <Text style={styles.actionButtonTitle}>Configurar nómina</Text>
            <Text style={styles.actionButtonSubtitle}>Delegados y permisos de pago</Text>
          </View>
          <Icon name="chevron-right" size={18} color="#9ca3af" />
        </TouchableOpacity>

      </View>
    </View>
  );

  if (!isBusinessAccount) {
    return (
      <View style={[styles.container, { alignItems: 'center', justifyContent: 'center' }]}>
        <Text>Esta vista es solo para cuentas de negocio.</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Buscar empleados..."
          placeholderTextColor="#6b7280"
          value={searchTerm}
          onChangeText={setSearchTerm}
        />
        <TouchableOpacity style={styles.searchRefresh} onPress={() => { refetchEmployees(); refetchInvitations(); }}>
          <Icon name="refresh-cw" size={20} color="#6b7280" />
        </TouchableOpacity>
      </View>

      <SectionList
        sections={[
          { key: 'employees', title: `Empleados (${filteredEmployees.length})`, data: filteredEmployees },
          { key: 'invites', title: 'Invitaciones pendientes', data: invitations },
        ]}
        keyExtractor={(item: any, index) => item.id || item.invitationCode || index.toString()}
        renderItem={({ item, section }) => {
          if (section.key === 'employees') {
            const displayName =
              `${item.user?.firstName || ''} ${item.user?.lastName || ''}`.trim() ||
              item.user?.username ||
              'Empleado';
            const displayPhone = formatPhoneNumber(item.user?.phoneNumber, item.user?.phoneCountry);
            return (
              <EmployeeCard
                employee={item}
                onPress={() => navigation.navigate('EmployeeDetail', { employeeId: item.id, employeeName: displayName, employeePhone: displayPhone, employeeRole: item.role, isActive: item.isActive, employeeData: item } as any)}
                onActions={handleEmployeeActions}
              />
            );
          }
          // invitations
          return (
            <View style={styles.inviteCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.inviteTitle}>{item.displayInvitee || item.employeeUsername || item.employeePhone || item.email || 'Invitación'}</Text>
                <Text style={styles.inviteSubtitle}>Rol: {getRoleLabel(item.role)}</Text>
              </View>
              <TouchableOpacity onPress={() => handleCancelInvitation(item.id)}>
                <Text style={{ color: '#ef4444' }}>Cancelar</Text>
              </TouchableOpacity>
            </View>
          );
        }}
        renderSectionHeader={({ section }) => (
          <Text style={styles.sectionTitle}>{section.title}</Text>
        )}
        ListHeaderComponent={renderHeader}
        refreshControl={
          <RefreshControl
            refreshing={employeesLoading || invitationsLoading}
            onRefresh={() => {
              refetchEmployees();
              refetchInvitations();
            }}
            tintColor={colors.primary}
          />
        }
        contentContainerStyle={{ padding: 16 }}
      />

      <InviteEmployeeModal
        visible={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        onEmployeeAdded={() => {
          setShowInviteModal(false);
          refetchEmployees();
          refetchInvitations();
        }}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  headerWrap: { gap: 12, marginBottom: 8 },
  heroCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ECFDF3',
    borderRadius: 14,
    padding: 12,
    borderWidth: 1,
    borderColor: '#DCFCE7',
  },
  heroIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#10B981',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  heroTitle: { fontSize: 16, fontWeight: '700', color: '#065F46' },
  heroSubtitle: { fontSize: 13, color: '#065F46' },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
    gap: 10,
  },
  searchInput: {
    flex: 1,
    backgroundColor: '#f9fafb',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  searchRefresh: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#f9fafb',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  actionRow: { gap: 10 },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    justifyContent: 'space-between',
    gap: 12,
  },
  actionIconContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#34d399',
  },
  actionTextContainer: { flex: 1 },
  actionButtonTitle: { fontSize: 16, fontWeight: '700', color: '#111827' },
  actionButtonSubtitle: { fontSize: 12, color: '#6b7280' },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#6b7280',
    marginTop: 12,
    marginBottom: 8,
  },
  employeeCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    marginBottom: 8,
    shadowColor: '#000',
    shadowOpacity: 0.03,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  avatarContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#e5e7eb',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
  },
  employeeName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#111827',
  },
  employeeRole: {
    fontSize: 12,
    color: '#6b7280',
  },
  employeePhone: {
    fontSize: 12,
    color: '#6b7280',
  },
  moreButton: {
    padding: 4,
  },
  inviteCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    marginBottom: 8,
  },
  inviteTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#111827',
  },
  inviteSubtitle: {
    fontSize: 12,
    color: '#6b7280',
  },
  payrollCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#f9fafb',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    marginBottom: 8,
  },
  payrollName: {
    fontSize: 14,
    fontWeight: '700',
    color: '#111827',
  },
  payrollAddress: {
    fontSize: 12,
    color: '#6b7280',
  },
});

export default EmployeesScreen;
