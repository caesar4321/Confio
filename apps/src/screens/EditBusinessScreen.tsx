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
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { APP_LAYOUT } from '../config/layout';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { Button } from '../components/common/Button';
import { EmptyState } from '../components/EmptyState';

type EditBusinessScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const EditBusinessScreen = () => {
  const navigation = useNavigation<EditBusinessScreenNavigationProp>();
  const { activeAccount } = useAccount();
  const { userProfile } = useAuth();
  const [updateBusiness] = useMutation(UPDATE_BUSINESS);
  const { refetch: refetchAccounts } = useQuery(GET_USER_ACCOUNTS);
  const { data: accountsData, loading: accountsLoading } = useQuery(GET_USER_ACCOUNTS, { fetchPolicy: 'cache-and-network' });

  const [businessName, setBusinessName] = useState('');
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
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

    if (!categoryId) return 'No especificada';

    // First try to find by ID (for database values like 'food', 'retail', etc.)
    let category = businessCategories.find(cat => cat.id === categoryId);

    if (category) {
      return category.name;
    }

    // Try case-insensitive match
    category = businessCategories.find(cat => cat.id.toLowerCase() === categoryId.toLowerCase());

    if (category) {
      return category.name;
    }

    // If not found by ID, it might be a display name already, so return as is
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
      setBanner({ variant: 'error', message: 'Este negocio ya fue verificado; su información no puede cambiarse.' });
      return;
    }
    if (!businessName.trim()) {
      setBanner({ variant: 'error', message: 'El nombre del negocio es requerido' });
      return;
    }

    if (!businessCategory) {
      setBanner({ variant: 'error', message: 'La categoría del negocio es requerida' });
      return;
    }

    if (!activeAccount?.business?.id) {
      setBanner({ variant: 'error', message: 'No se pudo identificar el negocio' });
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
        // Frictionless save: refresh and return — the updated data on the
        // previous screen IS the confirmation.
        await refetchAccounts();
        navigation.goBack();
      } else {
        const error = result.data?.updateBusiness?.error || 'Error desconocido';
        setBanner({ variant: 'error', message: error });
      }
    } catch (error) {
      setBanner({ variant: 'error', message: 'No se pudo actualizar la información del negocio' });
    } finally {
      setIsLoading(false);
    }
  };

  if (!activeAccount || activeAccount.type.toLowerCase() !== 'business') {
    return (
      <View style={styles.container}>
        <EmptyState
          icon="briefcase"
          title="Solo para negocios"
          subtitle="Cambia a tu cuenta de negocio para editar su información."
        />
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
        <Header
          navigation={navigation as any}
          title="Editar Negocio"
          backgroundColor={colors.primary}
          isLight
          showBackButton
        />

        <View style={styles.verifiedHero}>
          <BrandFieldBackground id="editBusinessVerifiedField" ringCy="30%" ringR={70} ringWidth={18} />
          <View style={styles.verifiedHeroInner}>
            <View style={styles.verifiedBadge}>
              <Icon name="check" size={28} color={colors.primaryDark} />
            </View>
            <Text style={styles.verifiedTitle}>Negocio verificado</Text>
            <Text style={styles.verifiedSubtitle}>
              La información verificada no puede modificarse.
            </Text>
          </View>
        </View>

        <View style={{ padding: 16 }}>
          <View style={styles.verifiedCard}>
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
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Editar Negocio"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />
    <ScrollView contentContainerStyle={styles.scrollContent}>
      {banner && (
        <InlineBanner
          message={banner.message}
          variant={banner.variant}
          onDismiss={dismissBanner}
          style={{ marginHorizontal: 16, marginTop: 12 }}
        />
      )}
      {/* Avatar hero — brand field, seamless with the emerald nav header */}
      <View style={styles.avatarSection}>
        <BrandFieldBackground id="editBusinessField" ringCy="30%" ringR={70} ringWidth={18} />
        <View style={styles.avatarSectionInner}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>{avatarLetter}</Text>
          </View>
          <Text style={styles.avatarLabel}>Avatar del negocio</Text>
        </View>
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
            placeholderTextColor={colors.text.light}
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
            <Icon name="chevron-down" size={20} color={colors.text.secondary} />
          </TouchableOpacity>
        </View>

        {/* Business Description */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Descripción</Text>
          <TextInput
            style={[styles.input, styles.inputMultiline]}
            value={businessDescription}
            onChangeText={setBusinessDescription}
            placeholder="Ingresa la descripción del negocio"
            placeholderTextColor={colors.text.light}
            maxLength={200}
            multiline
            numberOfLines={3}
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
            placeholderTextColor={colors.text.light}
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
            placeholderTextColor={colors.text.light}
            maxLength={200}
          />
        </View>
      </View>

      {/* Action Buttons */}
      <View style={styles.actions}>
        <Button
          title="Guardar cambios"
          onPress={handleSave}
          loading={isLoading}
          accessibilityLabel="Guardar cambios del negocio"
        />
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
               accessibilityRole="button" accessibilityLabel="Cerrar">
                <Icon name="x" size={24} color={colors.text.secondary} />
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
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  scrollContent: {
    flexGrow: 1,
  },
  avatarSection: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  avatarSectionInner: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.white,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  avatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.primaryDark,
  },
  avatarLabel: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.85)',
  },
  verifiedHero: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  verifiedHeroInner: {
    alignItems: 'center',
    paddingVertical: 28,
    paddingHorizontal: 24,
  },
  verifiedBadge: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.white,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
  },
  verifiedTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.white,
    marginBottom: 6,
  },
  verifiedSubtitle: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.85)',
    textAlign: 'center',
  },
  verifiedCard: {
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 6,
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
    color: colors.text.primary,
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text.primary,
    backgroundColor: colors.white,
  },
  inputMultiline: {
    minHeight: 80,
    textAlignVertical: 'top',
  },
  pickerContainer: {
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: colors.white,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pickerText: {
    fontSize: 16,
    color: colors.text.primary,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
  },
  infoLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  infoValue: {
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
    flex: 1,
    textAlign: 'right',
    marginLeft: 8,
  },
  actions: {
    padding: 16,
    paddingBottom: 32,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.white,
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
    color: colors.text.primary,
  },
  modalCloseButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
  },
  categoryList: {
    maxHeight: 300,
  },
  categoryItem: {
    padding: 16,
    borderWidth: 1,
    borderColor: colors.borderMedium,
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
    color: colors.text.primary,
  },
  categoryItemTextSelected: {
    fontWeight: '600',
    color: colors.primary,
  },
}); 
