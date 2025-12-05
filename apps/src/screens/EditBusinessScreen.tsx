import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Alert,
  Platform,
  StatusBar,
  Modal,
  FlatList,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useMutation, useQuery } from '@apollo/client';
import { UPDATE_BUSINESS, GET_USER_ACCOUNTS, GET_BUSINESS_KYC_STATUS } from '../apollo/queries';

type EditBusinessScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  primaryText: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#10b981',
  secondary: '#8b5cf6',
  secondaryText: '#8b5cf6',
  accent: '#3b82f6',
  accentText: '#3b82f6',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
  error: '#ef4444',
  success: '#10b981',
};

export const EditBusinessScreen = () => {
  const navigation = useNavigation<EditBusinessScreenNavigationProp>();
  const { activeAccount } = useAccount();
  const { userProfile } = useAuth();
  const [updateBusiness] = useMutation(UPDATE_BUSINESS);
  const { refetch: refetchAccounts } = useQuery(GET_USER_ACCOUNTS);
  const { data: accountsData, loading: accountsLoading } = useQuery(GET_USER_ACCOUNTS, { fetchPolicy: 'cache-and-network' });

  const [businessName, setBusinessName] = useState('');
  const [businessCategory, setBusinessCategory] = useState('');
  const [businessDescription, setBusinessDescription] = useState('');
  const [businessRegistrationNumber, setBusinessRegistrationNumber] = useState('');
  const [businessAddress, setBusinessAddress] = useState('');
  const [avatarLetter, setAvatarLetter] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showCategoryPicker, setShowCategoryPicker] = useState(false);

  // Business categories with display names (matching Django backend)
  const businessCategories = [
    { id: 'food', name: 'Comida y Bebidas' },
    { id: 'retail', name: 'Comercio y Ventas' },
    { id: 'services', name: 'Servicios Profesionales' },
    { id: 'health', name: 'Belleza y Salud' },
    { id: 'transport', name: 'Transporte y Delivery' },
    { id: 'other', name: 'Otros Negocios' }
  ];

  // Load current business data
  useEffect(() => {
    if (activeAccount && activeAccount.type.toLowerCase() === 'business' && activeAccount.business) {
      console.log('EditBusinessScreen - Loading business data:', {
        businessName: activeAccount.business.name,
        businessCategory: activeAccount.business.category,
        businessDescription: activeAccount.business.description,
        businessRegistrationNumber: activeAccount.business.businessRegistrationNumber,
        businessAddress: activeAccount.business.address,
        avatar: activeAccount.avatar
      });

      setBusinessName(activeAccount.business.name || '');
      setBusinessCategory(activeAccount.business.category || '');
      setBusinessDescription(activeAccount.business.description || '');
      setBusinessRegistrationNumber(activeAccount.business.businessRegistrationNumber || '');
      setBusinessAddress(activeAccount.business.address || '');
      setAvatarLetter(activeAccount.avatar || '');
    }
  }, [activeAccount]);

  // Update avatar letter when business name changes
  useEffect(() => {
    if (businessName.trim()) {
      setAvatarLetter(businessName.trim().charAt(0).toUpperCase());
    }
  }, [businessName]);

  const getCategoryDisplayName = (categoryId: string) => {
    console.log('getCategoryDisplayName called with:', categoryId);
    console.log('Available categories:', businessCategories.map(cat => ({ id: cat.id, name: cat.name })));

    if (!categoryId) return 'No especificada';

    // First try to find by ID (for database values like 'food', 'retail', etc.)
    let category = businessCategories.find(cat => cat.id === categoryId);
    console.log('Found category by exact match:', category);

    if (category) {
      console.log('Returning display name:', category.name);
      return category.name;
    }

    // Try case-insensitive match
    category = businessCategories.find(cat => cat.id.toLowerCase() === categoryId.toLowerCase());
    console.log('Found category by case-insensitive match:', category);

    if (category) {
      console.log('Returning display name (case-insensitive):', category.name);
      return category.name;
    }

    // If not found by ID, it might be a display name already, so return as is
    console.log('Category not found, returning as is:', categoryId);
    return categoryId;
  };

  const handleCategorySelect = (category: { id: string; name: string }) => {
    setBusinessCategory(category.id);
    setShowCategoryPicker(false);
  };

  // Determine if current business is verified (from server data)
  const { data: bizKycData } = useQuery(GET_BUSINESS_KYC_STATUS, {
    variables: { businessId: activeAccount?.business?.id || '' },
    skip: !activeAccount?.business?.id,
    fetchPolicy: 'network-only'
  });

  const isBusinessVerified = (() => {
    // Check real-time status first
    const status = bizKycData?.businessKycStatus?.status;
    if (status && status.toLowerCase() === 'verified') return true;

    // Fallback to account data
    const list = accountsData?.userAccounts || [];
    const currentBizId = activeAccount?.business?.id;
    const match = list.find((acc: any) => acc.business?.id === currentBizId);
    return !!match?.business?.isVerified;
  })();

  const businessVerifiedDate = (() => {
    const list = accountsData?.userAccounts || [];
    const currentBizId = activeAccount?.business?.id;
    const match = list.find((acc: any) => acc.business?.id === currentBizId);
    return match?.business?.lastVerifiedDate || null;
  })();

  const handleSave = async () => {
    if (isBusinessVerified) {
      Alert.alert('No se puede editar', 'Este negocio ya ha sido verificado. No puedes cambiar la información verificada.');
      return;
    }
    if (!businessName.trim()) {
      Alert.alert('Error', 'El nombre del negocio es requerido');
      return;
    }

    if (!businessCategory) {
      Alert.alert('Error', 'La categoría del negocio es requerida');
      return;
    }

    if (!activeAccount?.business?.id) {
      Alert.alert('Error', 'No se pudo identificar el negocio');
      return;
    }

    setIsLoading(true);
    try {
      const result = await updateBusiness({
        variables: {
          businessId: activeAccount.business.id,
          name: businessName.trim(),
          description: businessDescription.trim() || undefined,
          category: businessCategory,
          businessRegistrationNumber: businessRegistrationNumber.trim() || undefined,
          address: businessAddress.trim() || undefined
        }
      });

      if (result.data?.updateBusiness?.success) {
        // Refresh accounts to get updated data
        await refetchAccounts();

        Alert.alert(
          'Éxito',
          'Información del negocio actualizada correctamente',
          [
            {
              text: 'OK',
              onPress: () => navigation.goBack(),
            },
          ]
        );
      } else {
        const error = result.data?.updateBusiness?.error || 'Error desconocido';
        Alert.alert('Error', error);
      }
    } catch (error) {
      console.error('Error updating business:', error);
      Alert.alert('Error', 'No se pudo actualizar la información del negocio');
    } finally {
      setIsLoading(false);
    }
  };

  if (!activeAccount || activeAccount.type.toLowerCase() !== 'business') {
    return (
      <View style={styles.container}>
        <Text style={styles.errorText}>Esta pantalla solo está disponible para cuentas de negocio</Text>
      </View>
    );
  }

  // If business is verified, block editing like EditProfileScreen
  if (accountsLoading) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text>Cargando negocio…</Text>
      </View>
    );
  }

  if (isBusinessVerified) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Editar Negocio</Text>
          <View style={styles.placeholder} />
        </View>

        <View style={{ padding: 16, alignItems: 'center' }}>
          <View style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: colors.success, justifyContent: 'center', alignItems: 'center', marginBottom: 12 }}>
            <Text style={{ color: 'white', fontSize: 28, fontWeight: 'bold' }}>✓</Text>
          </View>
          <Text style={{ fontSize: 18, fontWeight: '700', color: '#111827', marginBottom: 6 }}>Negocio Verificado</Text>
          <Text style={{ fontSize: 14, color: '#374151', textAlign: 'center' }}>
            La información verificada del negocio no puede ser modificada.
          </Text>
          <View style={{ marginTop: 16, backgroundColor: colors.neutral, borderRadius: 8, padding: 12, alignSelf: 'stretch' }}>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Nombre:</Text>
              <Text style={styles.infoValue}>{activeAccount?.business?.name || '-'}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Categoría:</Text>
              <Text style={styles.infoValue}>{getCategoryDisplayName(activeAccount?.business?.category || '')}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Registro:</Text>
              <Text style={styles.infoValue}>{activeAccount?.business?.businessRegistrationNumber || '-'}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Dirección:</Text>
              <Text style={styles.infoValue}>{activeAccount?.business?.address || '-'}</Text>
            </View>
            {businessVerifiedDate && (
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Verificado el:</Text>
                <Text style={styles.infoValue}>
                  {new Date(businessVerifiedDate).toLocaleDateString('es-ES', { year: 'numeric', month: 'long', day: 'numeric' })}
                </Text>
              </View>
            )}
          </View>
        </View>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity
          style={styles.backButton}
          onPress={() => navigation.goBack()}
        >
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Editar Negocio</Text>
        <View style={styles.placeholder} />
      </View>

      {/* Avatar Section */}
      <View style={styles.avatarSection}>
        <View style={styles.avatarContainer}>
          <Text style={styles.avatarText}>{avatarLetter}</Text>
        </View>
        <Text style={styles.avatarLabel}>Avatar del negocio</Text>
      </View>

      {/* Form */}
      <View style={styles.form}>
        {/* Business Name */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Nombre del Negocio *</Text>
          <TextInput
            style={styles.input}
            value={businessName}
            onChangeText={setBusinessName}
            placeholder="Ingresa el nombre de tu negocio"
            placeholderTextColor="#9CA3AF"
            maxLength={50}
          />
        </View>

        {/* Business Category */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Categoría *</Text>
          <TouchableOpacity
            style={styles.pickerContainer}
            onPress={() => setShowCategoryPicker(true)}
            activeOpacity={0.7}
          >
            <Text style={styles.pickerText}>
              {businessCategory ? getCategoryDisplayName(businessCategory) : 'Selecciona una categoría'}
            </Text>
            <Icon name="chevron-down" size={20} color="#6B7280" />
          </TouchableOpacity>
        </View>

        {/* Business Description */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Descripción</Text>
          <TextInput
            style={styles.input}
            value={businessDescription}
            onChangeText={setBusinessDescription}
            placeholder="Ingresa la descripción del negocio"
            placeholderTextColor="#9CA3AF"
            maxLength={200}
          />
        </View>

        {/* Business Registration Number */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Número de Registro</Text>
          <TextInput
            style={styles.input}
            value={businessRegistrationNumber}
            onChangeText={setBusinessRegistrationNumber}
            placeholder="Ingresa el número de registro del negocio"
            placeholderTextColor="#9CA3AF"
            maxLength={20}
          />
        </View>

        {/* Business Address */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Dirección</Text>
          <TextInput
            style={styles.input}
            value={businessAddress}
            onChangeText={setBusinessAddress}
            placeholder="Ingresa la dirección del negocio"
            placeholderTextColor="#9CA3AF"
            maxLength={200}
          />
        </View>
      </View>

      {/* Action Buttons */}
      <View style={styles.actions}>
        <TouchableOpacity
          style={[styles.saveButton, isLoading && styles.disabledButton]}
          onPress={handleSave}
          disabled={isLoading}
        >
          <Text style={styles.saveButtonText}>
            {isLoading ? 'Guardando...' : 'Guardar Cambios'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Category Picker Modal */}
      <Modal
        visible={showCategoryPicker}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setShowCategoryPicker(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Seleccionar Categoría</Text>
              <TouchableOpacity
                onPress={() => setShowCategoryPicker(false)}
                style={styles.modalCloseButton}
              >
                <Icon name="x" size={24} color="#6B7280" />
              </TouchableOpacity>
            </View>
            <FlatList
              data={businessCategories}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={[
                    styles.categoryItem,
                    businessCategory === item.id && styles.categoryItemSelected
                  ]}
                  onPress={() => handleCategorySelect(item)}
                >
                  <Text style={[
                    styles.categoryItemText,
                    businessCategory === item.id && styles.categoryItemTextSelected
                  ]}>
                    {item.name}
                  </Text>
                  {businessCategory === item.id && (
                    <Icon name="check" size={20} color={colors.primary} />
                  )}
                </TouchableOpacity>
              )}
              style={styles.categoryList}
            />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    backgroundColor: colors.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
    paddingBottom: 16,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  placeholder: {
    width: 40,
  },
  avatarSection: {
    alignItems: 'center',
    paddingVertical: 24,
    backgroundColor: colors.neutral,
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  avatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#fff',
  },
  avatarLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  form: {
    padding: 16,
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 16,
    fontWeight: '500',
    color: '#374151',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 16,
    color: '#1F2937',
    backgroundColor: '#fff',
  },
  pickerContainer: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: '#fff',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pickerText: {
    fontSize: 16,
    color: '#1F2937',
  },
  infoSection: {
    backgroundColor: colors.neutral,
    borderRadius: 8,
    padding: 16,
    marginTop: 16,
  },
  infoTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 12,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 4,
  },
  infoLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  infoValue: {
    fontSize: 14,
    color: '#374151',
    fontWeight: '500',
    flex: 1,
    textAlign: 'right',
    marginLeft: 8,
  },
  actions: {
    padding: 16,
    paddingBottom: 32,
  },
  saveButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  saveButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  disabledButton: {
    opacity: 0.6,
  },
  errorText: {
    fontSize: 16,
    color: colors.error,
    textAlign: 'center',
    padding: 20,
  },
  readOnlyContainer: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    padding: 12,
    backgroundColor: '#fff',
  },
  readOnlyText: {
    fontSize: 16,
    color: '#374151',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    width: '80%',
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#374151',
  },
  modalCloseButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
  },
  categoryList: {
    maxHeight: 300,
  },
  categoryItem: {
    padding: 16,
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    marginBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  categoryItemSelected: {
    backgroundColor: colors.primaryLight,
    borderColor: colors.primary,
  },
  categoryItemText: {
    fontSize: 16,
    color: '#374151',
  },
  categoryItemTextSelected: {
    fontWeight: '600',
    color: colors.primary,
  },
}); 
