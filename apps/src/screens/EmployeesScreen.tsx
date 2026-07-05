import React, { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Platform, Modal, Image, RefreshControl, ActivityIndicator, SectionList, Alert, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useApolloClient, useMutation, useQuery, gql } from '@apollo/client';
import { INVITE_EMPLOYEE, GET_CURRENT_BUSINESS_EMPLOYEES, GET_CURRENT_BUSINESS_INVITATIONS, CANCEL_INVITATION } from '../apollo/queries';
import { InviteEmployeeModal } from '../components/InviteEmployeeModal';
import { getCountryByIso } from '../utils/countries';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { EmptyState } from '../components/EmptyState';

type EmployeesScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

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

const EmployeeCard = memo(({ employee, onPress }: any) => {
  const initialSource = employee?.user?.firstName || employee?.user?.username || 'E';
  const avatarInitial = typeof initialSource === 'string' && initialSource.length > 0
    ? initialSource.charAt(0).toUpperCase()
    : 'E';
  const displayName =
    `${employee?.user?.firstName || ''} ${employee?.user?.lastName || ''}`.trim() ||
    employee?.user?.username ||
    'Empleado';

  return (
    <TouchableOpacity
      style={styles.employeeCard}
      onPress={() => onPress(employee)}
      accessibilityRole="button"
      accessibilityLabel={`Ver detalles de ${displayName}`}
    >
      <View style={styles.avatarContainer}>
        <Text style={styles.avatarText}>{avatarInitial}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.employeeName}>{displayName}</Text>
        <Text style={styles.employeeRole}>{getRoleLabel(employee?.role)}</Text>
        <Text style={styles.employeePhone}>{formatPhoneNumber(employee?.user?.phoneNumber, employee?.user?.phoneCountry)}</Text>
      </View>
      <Icon name="chevron-right" size={18} color={colors.text.light} />
    </TouchableOpacity>
  );
});

export const EmployeesScreen = () => {
  const navigation = useNavigation<EmployeesScreenNavigationProp>();
  const { activeAccount } = useAccount();
  const apolloClient = useApolloClient();
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
  const [searchTerm, setSearchTerm] = useState('');

  const isBusinessAccount = activeAccount?.type === 'business';

  // Queries
  const { data: employeesData, loading: employeesLoading, error: employeesError, refetch: refetchEmployees, fetchMore } = useQuery(GET_CURRENT_BUSINESS_EMPLOYEES, {
    variables: { includeInactive: false, first: 50 },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network',
    context: {
      // Force unique cache key per business to prevent cross-business contamination
      businessId: activeAccount?.business?.id || activeAccount?.id
    }
  });
  const { data: invitationsData, loading: invitationsLoading, refetch: refetchInvitations } = useQuery(GET_CURRENT_BUSINESS_INVITATIONS, {
    variables: { status: 'pending' },
    skip: !isBusinessAccount,
    fetchPolicy: 'cache-and-network'
  });
  const [cancelInvitation] = useMutation(CANCEL_INVITATION);

  const employees = useMemo(() => employeesData?.currentBusinessEmployees || [], [employeesData]);
  const invitations = useMemo(() => invitationsData?.currentBusinessInvitations || [], [invitationsData]);

  // Refetch when screen gains focus or account changes to prevent stale cache
  useFocusEffect(
    useCallback(() => {
      if (isBusinessAccount) {
        refetchEmployees();
        refetchInvitations();
      }
    }, [isBusinessAccount, refetchEmployees, refetchInvitations])
  );

  // Also refetch when active account changes
  useEffect(() => {
    if (isBusinessAccount) {
      refetchEmployees();
      refetchInvitations();
    }
  }, [activeAccount?.id, refetchEmployees, refetchInvitations, isBusinessAccount]);

  const filteredEmployees = useMemo(() => {
    if (!searchTerm) return employees;
    const lower = searchTerm.toLowerCase();
    return employees.filter((emp: any) =>
      (emp.user?.firstName || '').toLowerCase().includes(lower) ||
      (emp.user?.lastName || '').toLowerCase().includes(lower) ||
      (emp.user?.username || '').toLowerCase().includes(lower)
    );
  }, [employees, searchTerm]);

  const handleInvite = () => setShowInviteModal(true);

  const handleCancelInvitation = async (invitationId: string) => {
    try {
      const result = await cancelInvitation({ variables: { invitationId } });
      const success = result.data?.cancelInvitation?.success;
      const errorMsg = result.data?.cancelInvitation?.errors?.[0];
      if (!success) {
        setBanner({ variant: 'error', message: errorMsg || 'No se pudo cancelar la invitación' });
        return;
      }
      setBanner({ variant: 'success', message: 'Invitación cancelada correctamente.' });
      refetchInvitations();
    } catch (e) {
      setBanner({ variant: 'error', message: 'No se pudo cancelar la invitación' });
    }
  };

  const renderHeader = () => (
    <View style={styles.headerWrap}>
      {/* Emerald brand field (shared backdrop) bleeding through the list
          padding — same strip grammar as PayoutMethods/Guardarian. */}
      <View style={styles.brandField}>
        <BrandFieldBackground id="employeesField" ringCy="20%" ringR={80} ringWidth={20} />
        <View style={styles.fieldInner}>
          <Text style={styles.fieldEyebrow}>TU EQUIPO</Text>
          <Text style={styles.fieldTitle}>
            {employees.length > 0
              ? `${employees.length} ${employees.length === 1 ? 'persona contigo' : 'personas contigo'}`
              : 'Arma tu equipo'}
          </Text>
          <Text style={styles.fieldSubtitle}>
            Invítalos, gestiona sus permisos y conéctalos con la nómina.
          </Text>
        </View>
      </View>

      <View style={styles.actionRow}>
        <TouchableOpacity style={styles.actionButton} onPress={handleInvite}>
          <View style={styles.actionIconContainer}>
            <Icon name="user-plus" size={18} color={colors.white} />
          </View>
          <View style={styles.actionTextContainer}>
            <Text style={styles.actionButtonTitle}>Añadir empleado</Text>
            <Text style={styles.actionButtonSubtitle}>Gestiona tu equipo de trabajo</Text>
          </View>
          <Icon name="chevron-right" size={18} color={colors.text.light} />
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionButton, { borderColor: colors.violetLight, backgroundColor: colors.violetLight }]}
          onPress={() => navigation.navigate('PayrollHome')}
        >
          <View style={[styles.actionIconContainer, { backgroundColor: colors.secondary }]}>
            <Icon name="dollar-sign" size={18} color={colors.white} />
          </View>
          <View style={styles.actionTextContainer}>
            <Text style={styles.actionButtonTitle}>Nómina</Text>
            <Text style={styles.actionButtonSubtitle}>Paga a tu equipo automáticamente</Text>
          </View>
          <Icon name="chevron-right" size={18} color={colors.text.light} />
        </TouchableOpacity>

      </View>
    </View>
  );

  if (!isBusinessAccount) {
    return (
      <View style={styles.container}>
        <EmptyState
          icon="briefcase"
          title="Solo para negocios"
          subtitle="Cambia a tu cuenta de negocio para gestionar empleados."
        />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.searchContainer}>
        <View style={styles.searchBox}>
          <Icon name="search" size={18} color={colors.text.light} />
          <TextInput
            style={styles.searchInput}
            placeholder="Buscar empleados..."
            placeholderTextColor={colors.text.light}
            value={searchTerm}
            onChangeText={setSearchTerm}
          />
          {searchTerm.length > 0 && (
            <TouchableOpacity onPress={() => setSearchTerm('')} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Borrar búsqueda">
              <Icon name="x-circle" size={18} color={colors.text.light} />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {banner && (
        <InlineBanner
          message={banner.message}
          variant={banner.variant}
          onDismiss={dismissBanner}
          autoHideMs={banner.variant === 'success' ? 2500 : undefined}
          style={{ marginHorizontal: 16, marginTop: 8, marginBottom: 0 }}
        />
      )}

      <SectionList
        sections={[
          { key: 'employees', title: `Empleados (${filteredEmployees.length})`, data: filteredEmployees },
          ...(invitations.length > 0
            ? [{ key: 'invites', title: 'Invitaciones pendientes', data: invitations }]
            : []),
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
                <Text style={{ color: colors.danger }}>Cancelar</Text>
              </TouchableOpacity>
            </View>
          );
        }}
        renderSectionHeader={({ section }) => (
          <Text style={styles.sectionTitle}>{section.title}</Text>
        )}
        renderSectionFooter={({ section }) =>
          section.key === 'employees' && filteredEmployees.length === 0 ? (
            <EmptyState
              icon={searchTerm ? 'search' : 'users'}
              title={searchTerm ? 'Sin resultados' : 'Aún no tienes empleados'}
              subtitle={searchTerm
                ? `No encontramos empleados para "${searchTerm}".`
                : 'Invita a tu equipo para que puedan cobrar y ayudarte a operar.'}
              actionLabel={searchTerm ? undefined : 'Añadir empleado'}
              onAction={searchTerm ? undefined : handleInvite}
            />
          ) : null
        }
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
  container: { flex: 1, backgroundColor: colors.white },
  headerWrap: { gap: 12, marginBottom: 8 },
  brandField: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
    marginHorizontal: -16,
    marginTop: -16,
    marginBottom: 4,
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 22,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  fieldTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 6,
  },
  searchContainer: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.neutral,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  searchInput: {
    flex: 1,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.text.primary,
  },
  actionRow: { gap: 10 },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    justifyContent: 'space-between',
    gap: 12,
  },
  actionIconContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
  },
  actionTextContainer: { flex: 1 },
  actionButtonTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  actionButtonSubtitle: { fontSize: 12, color: colors.text.secondary },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 12,
    marginBottom: 8,
  },
  employeeCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: colors.white,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 8,
  },
  avatarContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: colors.violetLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.secondary,
  },
  employeeName: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text.primary,
  },
  employeeRole: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  employeePhone: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  inviteCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: colors.white,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 8,
  },
  inviteTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
  },
  inviteSubtitle: {
    fontSize: 12,
    color: colors.text.secondary,
  },
});

export default EmployeesScreen;
