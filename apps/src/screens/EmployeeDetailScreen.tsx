import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { getCountryByIso } from '../utils/countries';
import { useMutation } from '@apollo/client';
import { REMOVE_BUSINESS_EMPLOYEE, GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

// Color palette
type EmployeeDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type EmployeeDetailScreenRouteProp = RouteProp<MainStackParamList, 'EmployeeDetail'>;

const getRoleLabel = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return 'Propietario';
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role || 'Empleado';
  }
};

const getRoleColor = (role: string) => {
  switch ((role || '').toLowerCase()) {
    case 'owner': return colors.primaryDark;
    case 'admin': return colors.secondary;
    case 'manager': return colors.offRampIcon;
    case 'cashier': return colors.primary;
    default: return colors.text.secondary;
  }
};

const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const code = country[1];
      const codeDigits = code.replace('+', '');
      const phoneDigits = phoneNumber.replace(/\D/g, '');
      const localDigits = phoneDigits.startsWith(codeDigits)
        ? phoneDigits.slice(codeDigits.length)
        : phoneDigits;
      return `${code} ${localDigits}`;
    }
  }
  return phoneNumber;
};

export const EmployeeDetailScreen = () => {
  const navigation = useNavigation<EmployeeDetailScreenNavigationProp>();
  const route = useRoute<EmployeeDetailScreenRouteProp>();
  
  const { 
    employeeId, 
    employeeName, 
    employeePhone, 
    employeeRole, 
    isActive,
    employeeData 
  } = route.params;

  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
  const [removeEmployee, { loading: removing }] = useMutation(REMOVE_BUSINESS_EMPLOYEE, {
    refetchQueries: [{ query: GET_CURRENT_BUSINESS_EMPLOYEES, variables: { includeInactive: false, first: 50 } }],
    awaitRefetchQueries: true,
  });

  const resolvedName =
    employeeName ||
    `${employeeData?.user?.firstName || ''} ${employeeData?.user?.lastName || ''}`.trim() ||
    employeeData?.user?.username ||
    'Empleado';
  const resolvedPhone =
    employeePhone ||
    employeeData?.user?.phoneNumber ||
    '';
  const resolvedPhoneCountry = employeeData?.user?.phoneCountry || '';
  const resolvedRole = (() => {
    const raw = employeeRole || employeeData?.role || 'cashier';
    return typeof raw === 'string' ? raw.toLowerCase() : 'cashier';
  })();
  const resolvedActive = typeof isActive === 'boolean' ? isActive : !!employeeData?.isActive;
  const rawPermissions = employeeData?.effectivePermissions || employeeData?.permissions || {};
  const permissions = React.useMemo(() => {
    if (typeof rawPermissions === 'string') {
      try {
        const parsed = JSON.parse(rawPermissions);
        if (parsed && typeof parsed === 'object') return parsed;
      } catch {}
      return {};
    }
    return rawPermissions && typeof rawPermissions === 'object' ? rawPermissions : {};
  }, [rawPermissions]);
  const hasPermissions = permissions && Object.keys(permissions).length > 0;
  const avatarInitial =
    typeof resolvedName === 'string' && resolvedName.length > 0
      ? resolvedName.charAt(0).toUpperCase()
      : 'E';

  const friendlyLabels: Record<string, string> = {
    accept_payments: 'Aceptar pagos',
    view_transactions: 'Ver transacciones',
    view_balance: 'Ver balance',
    send_funds: 'Enviar fondos',
    manage_employees: 'Gestionar empleados',
    view_business_address: 'Ver dirección del negocio',
    view_analytics: 'Ver analíticas',
    delete_business: 'Eliminar negocio',
    edit_business_info: 'Editar info del negocio',
    manage_bank_accounts: 'Gestionar cuentas bancarias',
    manage_p2p: 'Gestionar P2P',
    create_invoices: 'Crear facturas',
    manage_invoices: 'Gestionar facturas',
    export_data: 'Exportar datos',
  };

  const handleRemoveEmployee = () => {
    Alert.alert(
      'Confirmar Eliminación',
      `¿Estás seguro de que quieres remover a ${employeeName} como empleado? Esta acción no se puede deshacer.`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { 
          text: 'Remover', 
          style: 'destructive',
          onPress: async () => {
            try {
              const res = await removeEmployee({
                variables: { input: { employeeId } },
              });
              if (!res.data?.removeBusinessEmployee?.success) {
                setBanner({ variant: 'error', message: res.data?.removeBusinessEmployee?.errors?.[0] || 'No se pudo remover al empleado' });
                return;
              }
              Alert.alert('Empleado removido', `${employeeName} ha sido removido.`, [
                { text: 'Entendido', onPress: () => navigation.goBack() },
              ]);
            } catch (e) {
              setBanner({ variant: 'error', message: 'Ocurrió un error al remover al empleado' });
            }
          }
        }
      ]
    );
  };

  const handleEditEmployee = () => {
    navigation.navigate('EmployeeEdit', {
      employeeId,
      employeeData,
      name: resolvedName,
      phone: resolvedPhone,
      role: resolvedRole,
      isActive: resolvedActive,
    } as any);
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Detalles del Empleado"
        backgroundColor={colors.primary}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={dismissBanner}
            style={{ marginTop: 12 }}
          />
        )}
        {/* Hero — brand field, seamless with the emerald nav header */}
        <View style={styles.employeeHeader}>
          <BrandFieldBackground id="employeeDetailField" ringCy="30%" ringR={80} ringWidth={20} />
          <View style={styles.employeeHeaderInner}>
            <View style={styles.avatarContainer}>
              <Text style={styles.avatarText}>{avatarInitial}</Text>
            </View>
            <View style={styles.employeeInfo}>
              <Text style={styles.employeeName}>{resolvedName}</Text>
              <Text style={styles.employeePhone}>{formatPhoneNumber(resolvedPhone, resolvedPhoneCountry)}</Text>
              <View style={styles.roleContainer}>
                <View style={styles.rolePill}>
                  <Text style={styles.rolePillText}>{getRoleLabel(resolvedRole)}</Text>
                </View>
                <View style={[styles.statusBadge, !resolvedActive && styles.statusBadgeInactive]}>
                  <Text style={[styles.statusText, !resolvedActive && styles.statusTextInactive]}>
                    {resolvedActive ? 'Activo' : 'Inactivo'}
                  </Text>
                </View>
              </View>
            </View>
          </View>
        </View>

        {/* Employee Details */}
        <View style={styles.detailsSection}>
          <Text style={styles.sectionTitle}>Información del Empleado</Text>
          
          <View style={styles.detailItem}>
            <Icon name="briefcase" size={16} color={colors.text.secondary} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Rol</Text>
              <Text style={[styles.detailValue, { color: getRoleColor(resolvedRole) }]}>
                {getRoleLabel(resolvedRole)}
              </Text>
            </View>
          </View>

          <View style={styles.detailItem}>
            <Icon name={resolvedActive ? "check-circle" : "x-circle"} size={16} color={resolvedActive ? colors.primaryDark : colors.error.icon} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Estado</Text>
              <Text style={[
                styles.detailValue,
                { color: resolvedActive ? colors.primary : colors.error.icon }
              ]}>
                {resolvedActive ? 'Activo' : 'Inactivo'}
              </Text>
            </View>
          </View>

          {employeeData?.hiredAt && (
            <View style={styles.detailItem}>
              <Icon name="calendar" size={16} color={colors.text.secondary} />
              <View style={styles.detailContent}>
                <Text style={styles.detailLabel}>Fecha de Contratación</Text>
                <Text style={styles.detailValue}>
                  {new Date(employeeData.hiredAt).toLocaleDateString('es-ES')}
                </Text>
              </View>
            </View>
          )}

          {hasPermissions && (
            <View style={styles.detailItem}>
              <Icon name="shield" size={16} color={colors.text.secondary} />
              <View style={styles.detailContent}>
                <Text style={styles.detailLabel}>Permisos</Text>
                <Text style={styles.detailValue}>
                  {Object.entries(permissions).filter(([_, val]) => !!val).length} permisos activos
                </Text>
              </View>
            </View>
          )}
        </View>

        {/* Permissions */}
        {hasPermissions && (
          <View style={styles.detailsSection}>
            <Text style={styles.sectionTitle}>Permisos</Text>
            <View style={styles.permsBox}>
              {Object.entries(permissions)
                .filter(([key, val]) => typeof val === 'boolean')
                .map(([key, val]) => {
                  const label = friendlyLabels[key] || key.replace(/_/g, ' ');
                  return (
                    <View key={key} style={styles.permRow}>
                      <Text style={styles.permKey}>{label}</Text>
                      <Icon
                        name={val ? 'check-circle' : 'x-circle'}
                        size={16}
                        color={val ? colors.primaryDark : colors.text.light}
                      />
                    </View>
                  );
                })}
            </View>
          </View>
        )}

        {/* Actions Section */}
        <View style={styles.actionsSection}>
          <Text style={styles.sectionTitle}>Acciones</Text>
          
          <TouchableOpacity style={styles.actionButton} onPress={handleEditEmployee}>
            <Icon name="edit-2" size={20} color={colors.text.primary} />
            <Text style={styles.actionButtonText}>Editar Empleado</Text>
            <Icon name="chevron-right" size={16} color={colors.text.light} />
          </TouchableOpacity>

          <TouchableOpacity style={styles.actionButton} onPress={handleRemoveEmployee}>
            <Icon name="user-minus" size={20} color={colors.error.icon} />
            <Text style={[styles.actionButtonText, { color: colors.error.icon }]}>
              {removing ? 'Removiendo...' : 'Remover Empleado'}
            </Text>
            <Icon name="chevron-right" size={16} color={colors.text.light} />
          </TouchableOpacity>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  content: {
    flex: 1,
  },
  employeeHeader: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  employeeHeaderInner: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 24,
  },
  avatarContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  avatarText: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.secondary,
  },
  employeeInfo: {
    flex: 1,
  },
  employeeName: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.white,
    marginBottom: 4,
  },
  employeePhone: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.85)',
    marginBottom: 10,
  },
  roleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  rolePill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
  },
  rolePillText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.white,
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.9)',
  },
  statusBadgeInactive: {
    backgroundColor: colors.error.background,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  statusTextInactive: {
    color: colors.error.icon,
  },
  detailsSection: {
    padding: 24,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 16,
  },
  detailItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 16,
  },
  detailContent: {
    marginLeft: 12,
    flex: 1,
  },
  detailLabel: {
    fontSize: 12,
    color: colors.text.secondary,
    marginBottom: 2,
  },
  detailValue: {
    fontSize: 16,
    color: colors.text.primary,
    fontWeight: '500',
  },
  permsBox: {
    marginTop: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    overflow: 'hidden',
  },
  permRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  permKey: { fontSize: 13, color: colors.text.primary, flex: 1, paddingRight: 12 },
  actionsSection: {
    padding: 24,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 16,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    marginBottom: 12,
  },
  actionButtonText: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginLeft: 12,
  },
});
