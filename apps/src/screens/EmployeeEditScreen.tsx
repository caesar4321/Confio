import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { UPDATE_BUSINESS_EMPLOYEE, GET_CURRENT_BUSINESS_EMPLOYEES } from '../apollo/queries';

type EmployeeEditNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type EmployeeEditRouteProp = RouteProp<MainStackParamList, 'EmployeeEdit'>;

const roleOptions = [
  { value: 'cashier', label: 'Cajero' },
  { value: 'manager', label: 'Gerente' },
  { value: 'admin', label: 'Administrador' },
];

export const EmployeeEditScreen = () => {
  const navigation = useNavigation<EmployeeEditNavigationProp>();
  const route = useRoute<EmployeeEditRouteProp>();
  const { employeeId, employeeData, role, isActive } = route.params || {};

  const initialRole = useMemo(() => {
    const raw = role || employeeData?.role || 'cashier';
    return typeof raw === 'string' ? raw.toLowerCase() : 'cashier';
  }, [role, employeeData?.role]);
  const initialActive = useMemo(() => (isActive ?? employeeData?.isActive ?? true), [isActive, employeeData?.isActive]);

  const [selectedRole, setSelectedRole] = useState(initialRole);
  const [active, setActive] = useState<boolean>(initialActive);
  const isOwner = initialRole === 'owner';

  // Keep state in sync if params change (e.g., navigating with different role)
  React.useEffect(() => {
    setSelectedRole(initialRole);
    setActive(initialActive);
  }, [initialRole, initialActive]);
  const [updateEmployee, { loading }] = useMutation(UPDATE_BUSINESS_EMPLOYEE, {
    refetchQueries: [{ query: GET_CURRENT_BUSINESS_EMPLOYEES, variables: { includeInactive: true, first: 50 } }],
  });

  const employeeName = useMemo(() => {
    const nameFromParams = route.params?.name;
    if (nameFromParams) return nameFromParams;
    const u = employeeData?.user;
    return `${u?.firstName || ''} ${u?.lastName || ''}`.trim() || u?.username || 'Empleado';
  }, [employeeData?.user, route.params]);

  const handleSave = async () => {
    try {
      const { data } = await updateEmployee({
        variables: {
          input: {
            employeeId,
            role: selectedRole,
            isActive: active,
          },
        },
      });
      if (data?.updateBusinessEmployee?.success) {
        Alert.alert('Éxito', 'Empleado actualizado correctamente.', [
          { text: 'OK', onPress: () => navigation.goBack() },
        ]);
      } else {
        Alert.alert('Error', data?.updateBusinessEmployee?.errors?.[0] || 'No se pudo actualizar al empleado');
      }
    } catch (err) {
      Alert.alert('Error', 'Ocurrió un error al actualizar al empleado');
    }
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Editar Empleado"
        backgroundColor="#34d399"
        isLight
        showBackButton
      />

      <View style={styles.content}>
        <Text style={styles.label}>Empleado</Text>
        <Text style={styles.value}>{employeeName}</Text>

        <Text style={[styles.label, { marginTop: 20 }]}>Rol</Text>
        <View style={styles.roleRow}>
          {roleOptions.map((opt) => {
            const selected = selectedRole === opt.value;
            return (
              <TouchableOpacity
                key={opt.value}
                style={[styles.chip, selected && styles.chipSelected, isOwner && styles.chipDisabled]}
                onPress={() => !isOwner && setSelectedRole(opt.value)}
                accessibilityState={{ selected, disabled: isOwner }}
                disabled={isOwner}
              >
                <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{opt.label}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <Text style={[styles.label, { marginTop: 20 }]}>Estado</Text>
        <TouchableOpacity
          style={[styles.toggleRow, active ? styles.toggleOn : styles.toggleOff, isOwner && styles.chipDisabled]}
          onPress={() => !isOwner && setActive((prev) => !prev)}
          disabled={isOwner}
        >
          <View style={[styles.toggleDot, active ? styles.toggleDotOn : styles.toggleDotOff]} />
          <Text style={styles.toggleText}>{active ? 'Activo' : 'Inactivo'}</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.footer}>
        <TouchableOpacity style={[styles.button, styles.cancelButton]} onPress={() => navigation.goBack()} disabled={loading}>
          <Text style={styles.cancelText}>Cancelar</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.button, styles.saveButton]} onPress={handleSave} disabled={loading}>
          <Text style={styles.saveText}>{loading ? 'Guardando...' : 'Guardar cambios'}</Text>
          <Icon name="check" size={16} color="#fff" />
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 20 },
  label: { fontSize: 13, color: '#6b7280', fontWeight: '600', letterSpacing: 0.5, textTransform: 'uppercase' },
  value: { fontSize: 18, fontWeight: '700', color: '#111827', marginTop: 6 },
  roleRow: { flexDirection: 'row', gap: 10, marginTop: 10 },
  chip: { paddingHorizontal: 12, paddingVertical: 10, borderRadius: 12, borderWidth: 1.5, borderColor: '#e5e7eb', backgroundColor: '#f9fafb' },
  chipSelected: { borderColor: '#34d399', backgroundColor: '#ecfdf3' },
  chipText: { fontSize: 15, color: '#111827', fontWeight: '600' },
  chipTextSelected: { color: '#065f46' },
  chipDisabled: { opacity: 0.5 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderRadius: 12, padding: 12, marginTop: 10 },
  toggleOn: { backgroundColor: '#ecfdf3', borderWidth: 1.5, borderColor: '#34d399' },
  toggleOff: { backgroundColor: '#fef2f2', borderWidth: 1.5, borderColor: '#fecdd3' },
  toggleDot: { width: 20, height: 20, borderRadius: 10 },
  toggleDotOn: { backgroundColor: '#10b981' },
  toggleDotOff: { backgroundColor: '#f87171' },
  toggleText: { fontSize: 15, fontWeight: '600', color: '#111827' },
  footer: { flexDirection: 'row', padding: 20, gap: 12 },
  button: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', borderRadius: 12, paddingVertical: 14, gap: 8 },
  cancelButton: { backgroundColor: '#f3f4f6' },
  cancelText: { color: '#374151', fontSize: 15, fontWeight: '700' },
  saveButton: { backgroundColor: '#10b981', shadowColor: '#000', shadowOpacity: 0.1, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  saveText: { color: '#fff', fontSize: 15, fontWeight: '700' },
});
