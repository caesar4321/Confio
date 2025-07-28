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
    <View>
      <TouchableOpacity
        style={styles.dropdownButton}
        onPress={() => setIsOpen(!isOpen)}
      >
        <Text style={styles.dropdownButtonText}>
          {selectedOption?.label || placeholder}
        </Text>
        <Icon name={isOpen ? "chevron-up" : "chevron-down"} size={20} color="#6b7280" />
      </TouchableOpacity>
      
      {isOpen && (
        <View style={styles.dropdownList}>
          {options.map((option) => (
            <TouchableOpacity
              key={option.value}
              style={styles.dropdownItem}
              onPress={() => {
                onSelect(option.value);
                setIsOpen(false);
              }}
            >
              <Text style={[
                styles.dropdownItemText,
                value === option.value && styles.dropdownItemTextSelected
              ]}>
                {option.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );
};

export const InviteEmployeeModal: React.FC<InviteEmployeeModalProps> = ({
  visible,
  onClose,
  onSuccess,
}) => {
  const { activeAccount } = useAccount();
  const [phoneNumber, setPhoneNumber] = useState('');
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
    if (!phoneNumber) {
      Alert.alert('Error', 'Por favor ingresa el número de teléfono del empleado');
      return;
    }
    
    try {
      const { data } = await inviteEmployee({
        variables: {
          input: {
            employeePhone: phoneNumber,
            employeePhoneCountry: selectedCountry?.[2] || 'VE',
            employeeName,
            role,
            message,
          },
        },
      });
      
      if (data?.inviteEmployee?.success) {
        Alert.alert(
          'Invitación enviada',
          'Se ha enviado una invitación al empleado. Expirará en 7 días.',
          [{ text: 'OK', onPress: onSuccess }]
        );
        onClose();
      } else {
        Alert.alert('Error', data?.inviteEmployee?.errors?.[0] || 'No se pudo enviar la invitación');
      }
    } catch (error) {
      Alert.alert('Error', 'Ocurrió un error al enviar la invitación');
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
  dropdownButtonText: {
    fontSize: 16,
    color: '#1a1a1a',
    fontWeight: '500',
  },
  dropdownList: {
    position: 'absolute',
    top: '100%',
    left: 0,
    right: 0,
    backgroundColor: '#fff',
    borderRadius: 12,
    marginTop: 6,
    zIndex: 1000,
    elevation: 8,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.12,
    shadowRadius: 6,
    borderWidth: 1,
    borderColor: '#e9ecef',
    overflow: 'hidden',
  },
  dropdownItem: {
    paddingHorizontal: 16,
    paddingVertical: 14,
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