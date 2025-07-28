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

// Color palette
const colors = {
  primary: '#34D399', // emerald-400
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
    light: '#9CA3AF', // gray-400
  },
};

type EmployeeDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type EmployeeDetailScreenRouteProp = RouteProp<MainStackParamList, 'EmployeeDetail'>;

const getRoleLabel = (role: string) => {
  switch (role) {
    case 'cashier': return 'Cajero';
    case 'manager': return 'Gerente';
    case 'admin': return 'Administrador';
    default: return role;
  }
};

const getRoleColor = (role: string) => {
  switch (role) {
    case 'admin': return '#ef4444'; // red
    case 'manager': return '#f59e0b'; // amber
    case 'cashier': return colors.primary;
    default: return colors.text.secondary;
  }
};

const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  
  // Basic formatting - you can enhance this based on your country utils
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

  const [showActions, setShowActions] = useState(false);

  const handleToggleStatus = () => {
    const action = isActive ? 'desactivar' : 'activar';
    Alert.alert(
      `Confirmar ${action}`,
      `¿Estás seguro de que quieres ${action} a ${employeeName}?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { 
          text: action === 'desactivar' ? 'Desactivar' : 'Activar',
          style: action === 'desactivar' ? 'destructive' : 'default',
          onPress: () => {
            // TODO: Implement employee status toggle
            Alert.alert('Funcionalidad Pendiente', `La ${action}ción de empleados estará disponible pronto.`);
          }
        }
      ]
    );
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
          onPress: () => {
            // TODO: Implement employee removal
            Alert.alert('Funcionalidad Pendiente', 'La eliminación de empleados estará disponible pronto.');
          }
        }
      ]
    );
  };

  const handleEditEmployee = () => {
    // TODO: Navigate to edit employee screen
    Alert.alert('Funcionalidad Pendiente', 'La edición de empleados estará disponible pronto.');
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
        {/* Employee Header */}
        <View style={styles.employeeHeader}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>
              {employeeName.charAt(0).toUpperCase()}
            </Text>
          </View>
          
          <View style={styles.employeeInfo}>
            <Text style={styles.employeeName}>{employeeName}</Text>
            <Text style={styles.employeePhone}>{employeePhone}</Text>
            <View style={styles.roleContainer}>
              <Text style={[styles.employeeRole, { color: getRoleColor(employeeRole) }]}>
                {getRoleLabel(employeeRole)}
              </Text>
              <View style={[
                styles.statusBadge,
                { backgroundColor: isActive ? colors.primaryLight : '#fee2e2' }
              ]}>
                <Text style={[
                  styles.statusText,
                  { color: isActive ? colors.primaryDark : '#dc2626' }
                ]}>
                  {isActive ? 'Activo' : 'Inactivo'}
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Employee Details */}
        <View style={styles.detailsSection}>
          <Text style={styles.sectionTitle}>Información del Empleado</Text>
          
          <View style={styles.detailItem}>
            <Icon name="user" size={16} color={colors.text.secondary} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Nombre</Text>
              <Text style={styles.detailValue}>{employeeName}</Text>
            </View>
          </View>

          <View style={styles.detailItem}>
            <Icon name="phone" size={16} color={colors.text.secondary} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Teléfono</Text>
              <Text style={styles.detailValue}>{employeePhone}</Text>
            </View>
          </View>

          <View style={styles.detailItem}>
            <Icon name="briefcase" size={16} color={colors.text.secondary} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Rol</Text>
              <Text style={[styles.detailValue, { color: getRoleColor(employeeRole) }]}>
                {getRoleLabel(employeeRole)}
              </Text>
            </View>
          </View>

          <View style={styles.detailItem}>
            <Icon name={isActive ? "check-circle" : "x-circle"} size={16} color={isActive ? colors.primary : '#dc2626'} />
            <View style={styles.detailContent}>
              <Text style={styles.detailLabel}>Estado</Text>
              <Text style={[
                styles.detailValue,
                { color: isActive ? colors.primary : '#dc2626' }
              ]}>
                {isActive ? 'Activo' : 'Inactivo'}
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

          {employeeData?.permissions && (
            <View style={styles.detailItem}>
              <Icon name="shield" size={16} color={colors.text.secondary} />
              <View style={styles.detailContent}>
                <Text style={styles.detailLabel}>Permisos</Text>
                <Text style={styles.detailValue}>
                  {Object.keys(employeeData.permissions).length} permisos configurados
                </Text>
              </View>
            </View>
          )}
        </View>

        {/* Actions Section */}
        <View style={styles.actionsSection}>
          <Text style={styles.sectionTitle}>Acciones</Text>
          
          <TouchableOpacity style={styles.actionButton} onPress={handleEditEmployee}>
            <Icon name="edit-2" size={20} color={colors.text.primary} />
            <Text style={styles.actionButtonText}>Editar Empleado</Text>
            <Icon name="chevron-right" size={16} color={colors.text.light} />
          </TouchableOpacity>

          <TouchableOpacity style={styles.actionButton} onPress={handleToggleStatus}>
            <Icon 
              name={isActive ? "user-x" : "user-check"} 
              size={20} 
              color={isActive ? '#f59e0b' : colors.primary} 
            />
            <Text style={[
              styles.actionButtonText,
              { color: isActive ? '#f59e0b' : colors.primary }
            ]}>
              {isActive ? 'Desactivar Empleado' : 'Activar Empleado'}
            </Text>
            <Icon name="chevron-right" size={16} color={colors.text.light} />
          </TouchableOpacity>

          <TouchableOpacity style={styles.actionButton} onPress={handleRemoveEmployee}>
            <Icon name="user-minus" size={20} color="#dc2626" />
            <Text style={[styles.actionButtonText, { color: '#dc2626' }]}>
              Remover Empleado
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
    backgroundColor: '#fff',
  },
  content: {
    flex: 1,
  },
  employeeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 24,
    backgroundColor: colors.neutral,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  avatarContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  avatarText: {
    fontSize: 24,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  employeeInfo: {
    flex: 1,
  },
  employeeName: {
    fontSize: 20,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 4,
  },
  employeePhone: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 8,
  },
  roleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  employeeRole: {
    fontSize: 14,
    fontWeight: '500',
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '500',
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