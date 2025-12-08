import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TextInput,
  TouchableOpacity,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  FlatList,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation } from '@apollo/client';
import { INVITE_EMPLOYEE } from '../apollo/queries';
import { countries, Country } from '../utils/countries';
import { useCountrySelection } from '../hooks/useCountrySelection';
import { useAccount } from '../contexts/AccountContext';

interface InviteEmployeeModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

interface RoleOption {
  value: string;
  label: string;
}

interface RoleDropdownProps {
  value: string;
  options: RoleOption[];
  onSelect: (value: string) => void;
  placeholder: string;
}

// Simple Dropdown Component for Role Selection
const RoleDropdown: React.FC<RoleDropdownProps> = ({ value, options, onSelect, placeholder }) => {
  const [isOpen, setIsOpen] = useState(false);
  const selectedOption = options.find(opt => opt.value === value);

  return (
    <>
      <TouchableOpacity
        style={styles.dropdownButton}
        onPress={() => setIsOpen(true)}
        activeOpacity={0.9}
      >
        <Text style={styles.dropdownButtonText}>
          {selectedOption?.label || placeholder}
        </Text>
        <Icon name="chevron-down" size={18} color="#6b7280" />
      </TouchableOpacity>

      <Modal
        transparent
        visible={isOpen}
        animationType="fade"
        onRequestClose={() => setIsOpen(false)}
      >
        <TouchableOpacity style={styles.dropdownModalOverlay} activeOpacity={1} onPress={() => setIsOpen(false)} />
        <View style={styles.dropdownModalCard}>
          {options.map((option) => {
            const isSelected = value === option.value;
            return (
              <TouchableOpacity
                key={option.value}
                style={[styles.dropdownModalItem, isSelected && styles.dropdownModalItemSelected]}
                onPress={() => {
                  onSelect(option.value);
                  setIsOpen(false);
                }}
                activeOpacity={0.9}
              >
                <Text style={[
                  styles.dropdownItemText,
                  isSelected && styles.dropdownItemTextSelected
                ]}>
                  {option.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </Modal>
    </>
  );
};

export const InviteEmployeeModal: React.FC<InviteEmployeeModalProps> = ({
  visible,
  onClose,
  onSuccess,
}) => {
  const { activeAccount } = useAccount();
  const [mode, setMode] = useState<'phone' | 'username'>('phone');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [employeeUsername, setEmployeeUsername] = useState('');
  const [employeeName, setEmployeeName] = useState('');
  const [role, setRole] = useState('cashier');
  const [message, setMessage] = useState('');
  const [showCountryPicker, setShowCountryPicker] = useState(false);

  const [inviteEmployee, { loading }] = useMutation(INVITE_EMPLOYEE);

  // Use the country selection hook
  const { selectedCountry, selectCountry } = useCountrySelection();

  // Default to Venezuela if no country selected
  React.useEffect(() => {
    if (!selectedCountry) {
      const venezuela = countries.find(c => c[2] === 'VE');
      if (venezuela) {
        selectCountry(venezuela);
      }
    }
  }, [selectedCountry, selectCountry]);

  const roleOptions = [
    { value: 'cashier', label: 'Cajero' },
    { value: 'manager', label: 'Gerente' },
    { value: 'admin', label: 'Administrador' },
  ];

  const renderCountryItem = ({ item }: { item: Country }) => (
    <TouchableOpacity
      style={styles.countryItem}
      onPress={() => {
        selectCountry(item);
        setShowCountryPicker(false);
      }}
    >
      <Text style={styles.countryFlag}>{item[3]}</Text>
      <Text style={styles.countryName}>{item[0]}</Text>
      <Text style={styles.countryCode}>{item[1]}</Text>
      {selectedCountry?.[2] === item[2] && (
        <Icon name="check" size={20} color="#10b981" style={styles.checkIcon} />
      )}
    </TouchableOpacity>
  );

  const handleInvite = async () => {
    const isUsernameMode = mode === 'username';
    if (isUsernameMode) {
      if (!employeeUsername.trim()) {
        Alert.alert('Error', 'Ingresa el @usuario de Confío del empleado', [{ text: 'OK' }]);
        return;
      }
    } else {
      if (!phoneNumber) {
        Alert.alert('Error', 'Por favor ingresa el número de teléfono del empleado', [{ text: 'OK' }]);
        return;
      }
    }

    try {
      const input: any = {
        employeeName,
        role,
        message,
      };
      if (isUsernameMode) {
        input.employeeUsername = employeeUsername.trim().replace(/^@/, '');
      } else {
        input.employeePhone = phoneNumber;
        input.employeePhoneCountry = selectedCountry?.[2] || 'VE';
      }

      const { data } = await inviteEmployee({ variables: { input } });

      if (data?.inviteEmployee?.success) {
        Alert.alert(
          'Invitación enviada',
          'Se ha enviado una invitación al empleado. Expirará en 7 días.',
          [{ text: 'OK', onPress: onSuccess }]
        );
        onClose();
      } else {
        Alert.alert('Error', data?.inviteEmployee?.errors?.[0] || 'No se pudo enviar la invitación', [{ text: 'OK' }]);
      }
    } catch (error) {
      Alert.alert('Error', 'Ocurrió un error al enviar la invitación', [{ text: 'OK' }]);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <TouchableOpacity style={styles.backdrop} onPress={onClose} />

        <View style={styles.content}>
          <View style={styles.header}>
            <Text style={styles.title}>Invitar Empleado</Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Icon name="x" size={20} color="#666" />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.form}>
            <View style={styles.modeToggle}>
              <TouchableOpacity
                style={[styles.modeButton, mode === 'username' && styles.modeButtonActive]}
                onPress={() => setMode('username')}
              >
                <Text style={[styles.modeButtonText, mode === 'username' && styles.modeButtonTextActive]}>@usuario de Confío</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modeButton, mode === 'phone' && styles.modeButtonActive]}
                onPress={() => setMode('phone')}
              >
                <Text style={[styles.modeButtonText, mode === 'phone' && styles.modeButtonTextActive]}>Número de teléfono</Text>
              </TouchableOpacity>
            </View>

            {mode === 'username' ? (
              <View style={styles.inputGroup}>
                <Text style={styles.label}>@usuario</Text>
                <View style={styles.atInputContainer}>
                  <Text style={styles.atPrefix}>@</Text>
                  <TextInput
                    style={styles.atInput}
                    placeholder="confio_usuario"
                    placeholderTextColor="#adb5bd"
                    value={employeeUsername.replace(/^@/, '')}
                    onChangeText={(text) => setEmployeeUsername(text.replace(/^@/, ''))}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                </View>
                <Text style={styles.helperText}>Invita a alguien que ya usa Confío usando su @usuario.</Text>
              </View>
            ) : (
              <>
                <View style={styles.inputGroup}>
                  <Text style={styles.label}>País</Text>
                  <TouchableOpacity
                    style={styles.countrySelector}
                    onPress={() => setShowCountryPicker(true)}
                  >
                    <View style={styles.countrySelectorContent}>
                      <Text style={styles.flag}>{selectedCountry?.[3] || '🌍'}</Text>
                      <Text style={styles.countryNameSelector}>{selectedCountry?.[0] || 'Seleccionar país'}</Text>
                    </View>
                    <Icon name="chevron-down" size={20} color="#6b7280" />
                  </TouchableOpacity>
                </View>

                <View style={styles.inputGroup}>
                  <Text style={styles.label}>Número de teléfono</Text>
                  <View style={styles.phoneInputContainer}>
                    <View style={styles.phoneCodeContainer}>
                      <Text style={styles.phoneCode}>{selectedCountry?.[1] || '+58'}</Text>
                    </View>
                    <TextInput
                      style={styles.phoneInput}
                      placeholder="412 1234567"
                      placeholderTextColor="#adb5bd"
                      value={phoneNumber}
                      onChangeText={setPhoneNumber}
                      keyboardType="phone-pad"
                    />
                  </View>
                </View>
              </>
            )}

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Nombre (opcional)</Text>
              <TextInput
                style={styles.input}
                placeholder="Nombre del empleado"
                placeholderTextColor="#adb5bd"
                value={employeeName}
                onChangeText={setEmployeeName}
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Rol</Text>
              <RoleDropdown
                value={role}
                options={roleOptions}
                onSelect={setRole}
                placeholder="Seleccionar rol"
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Mensaje (opcional)</Text>
              <TextInput
                style={[styles.input, styles.messageInput]}
                placeholder="Agrega un mensaje personalizado para el empleado"
                placeholderTextColor="#adb5bd"
                value={message}
                onChangeText={setMessage}
                multiline
                numberOfLines={3}
              />
            </View>

            <View style={styles.permissionsInfo}>
              <Icon name="shield" size={18} color="#065f46" />
              <Text style={styles.permissionsText}>
                {role === 'cashier' && 'Puede aceptar pagos y ver transacciones'}
                {role === 'manager' && 'Puede aceptar pagos, ver balances y gestionar empleados'}
                {role === 'admin' && 'Acceso completo excepto enviar fondos'}
              </Text>
            </View>
          </ScrollView>

          <View style={styles.footer}>
            <TouchableOpacity
              style={[styles.button, styles.cancelButton]}
              onPress={onClose}
            >
              <Text style={styles.cancelButtonText}>Cancelar</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.button, styles.inviteButton]}
              onPress={handleInvite}
              disabled={loading}
            >
              <Text style={styles.inviteButtonText}>
                {loading ? 'Enviando...' : 'Enviar invitación'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>

      {/* Country Selection Modal */}
      <Modal
        visible={showCountryPicker}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setShowCountryPicker(false)}
      >
        <View style={styles.countryModalContainer}>
          <View style={styles.countryModalContent}>
            <View style={styles.countryModalHeader}>
              <Text style={styles.countryModalTitle}>Selecciona un país</Text>
              <TouchableOpacity onPress={() => setShowCountryPicker(false)}>
                <Icon name="x" size={24} color="#666" />
              </TouchableOpacity>
            </View>
            <FlatList
              data={countries}
              renderItem={renderCountryItem}
              keyExtractor={(item) => item[2]}
              style={styles.countryList}
              showsVerticalScrollIndicator={true}
            />
          </View>
        </View>
      </Modal>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
  },
  content: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    maxHeight: '92%',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: -4,
    },
    shadowOpacity: 0.15,
    shadowRadius: 8,
    elevation: 10,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: '#1a1a1a',
    letterSpacing: -0.5,
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#f5f5f5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  form: {
    paddingHorizontal: 24,
    paddingBottom: 24,
  },
  modeToggle: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 20,
  },
  modeButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    backgroundColor: '#f8f9fa',
    alignItems: 'center',
  },
  modeButtonActive: {
    backgroundColor: '#f5f3ff',
    borderColor: '#c4b5fd',
  },
  modeButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#475569',
  },
  modeButtonTextActive: {
    color: '#6d28d9',
  },
  inputGroup: {
    marginBottom: 24,
  },
  label: {
    fontSize: 13,
    fontWeight: '600',
    color: '#666',
    marginBottom: 10,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  input: {
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  messageInput: {
    height: 100,
    textAlignVertical: 'top',
    paddingTop: 14,
  },
  countrySelector: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  countrySelectorContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  flag: {
    fontSize: 24,
  },
  countryNameSelector: {
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  phoneInputContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  phoneCodeContainer: {
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    justifyContent: 'center',
  },
  phoneCode: {
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '600',
  },
  phoneInput: {
    flex: 1,
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  helperText: {
    marginTop: 8,
    fontSize: 12,
    color: '#6b7280',
  },
  atInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
  },
  atPrefix: {
    fontSize: 18,
    fontWeight: '700',
    color: '#6d28d9',
  },
  atInput: {
    flex: 1,
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  dropdownButton: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#f8f9fa',
    borderWidth: 1.5,
    borderColor: '#e9ecef',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  dropdownWrapper: {
    position: 'relative',
    zIndex: 1,
  },
  dropdownWrapperOpen: {
    zIndex: 20,
  },
  dropdownButtonText: {
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  dropdownItemSelected: {
    backgroundColor: '#f5f3ff',
  },
  dropdownList: {
  },
  dropdownItem: {
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  dropdownModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.3)',
  },
  dropdownModalCard: {
    position: 'absolute',
    alignSelf: 'center',
    width: '90%',
    maxWidth: 360,
    bottom: 80,
    backgroundColor: '#fff',
    borderRadius: 12,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: '#e9ecef',
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 10,
  },
  dropdownModalItem: {
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  dropdownModalItemSelected: {
    backgroundColor: '#f5f3ff',
  },
  dropdownItemText: {
    fontSize: 16,
    color: '#495057',
    fontWeight: '500',
  },
  dropdownItemTextSelected: {
    color: '#10b981',
    fontWeight: '600',
  },
  helperText: {
    marginTop: 6,
    color: '#6b7280',
    fontSize: 12,
    lineHeight: 18,
  },
  permissionsInfo: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#e8f5f1',
    padding: 16,
    borderRadius: 12,
    gap: 12,
    marginTop: 8,
  },
  permissionsText: {
    flex: 1,
    fontSize: 14,
    color: '#065f46',
    lineHeight: 20,
    fontWeight: '500',
  },
  footer: {
    flexDirection: 'row',
    paddingHorizontal: 24,
    paddingTop: 20,
    paddingBottom: 34,
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: '#f0f0f0',
  },
  button: {
    flex: 1,
    paddingVertical: 16,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelButton: {
    backgroundColor: '#f5f5f5',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#666',
  },
  inviteButton: {
    backgroundColor: '#10b981',
    shadowColor: '#10b981',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 5,
  },
  inviteButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },
  countryModalContainer: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
    justifyContent: 'flex-end',
  },
  countryModalContent: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    maxHeight: '80%',
  },
  countryModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  countryModalTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#1a1a1a',
  },
  countryList: {
    paddingBottom: 20,
  },
  countryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
  },
  countryFlag: {
    fontSize: 24,
    marginRight: 16,
  },
  countryName: {
    flex: 1,
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  countryCode: {
    fontSize: 14,
    color: '#6b7280',
    marginRight: 12,
  },
  checkIcon: {
    marginLeft: 8,
  },
});
