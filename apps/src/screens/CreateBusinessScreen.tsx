import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  Alert,
  SafeAreaView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList, RootStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { useAccount } from '../contexts/AccountContext';
import { useMutation, useQuery } from '@apollo/client';
import { CREATE_BUSINESS, GET_USER_ACCOUNTS } from '../apollo/queries';

type CreateBusinessNavigationProp = NativeStackNavigationProp<MainStackParamList>;

interface BusinessType {
  id: string;
  name: string;
  icon: string;
  description: string;
}

const businessTypes: BusinessType[] = [
  {
    id: 'food',
    name: 'Comida y Bebidas',
    icon: 'coffee',
    description: 'Restaurantes, cafes, food trucks, bares'
  },
  {
    id: 'retail',
    name: 'Comercio y Ventas',
    icon: 'shopping-bag',
    description: 'Tiendas, ventas, productos al detal'
  },
  {
    id: 'services',
    name: 'Servicios Profesionales',
    icon: 'briefcase',
    description: 'Consultoria, reparaciones, freelance'
  },
  {
    id: 'health',
    name: 'Belleza y Salud',
    icon: 'heart',
    description: 'Salones, spas, farmacias, clinicas'
  },
  {
    id: 'transport',
    name: 'Transporte y Delivery',
    icon: 'truck',
    description: 'Taxis, delivery, mudanzas, logistica'
  },
  {
    id: 'other',
    name: 'Otros Negocios',
    icon: 'users',
    description: 'Entretenimiento, educacion, otros'
  }
];

export const CreateBusinessScreen = () => {
  const navigation = useNavigation<CreateBusinessNavigationProp>();
  const { syncWithServer } = useAccount();
  const [createBusiness] = useMutation(CREATE_BUSINESS);
  const { refetch: refetchAccounts } = useQuery(GET_USER_ACCOUNTS);
  const [currentStep, setCurrentStep] = useState(1);
  const [isCreating, setIsCreating] = useState(false);
  const lastCreateAttempt = useRef<number>(0);
  const [formData, setFormData] = useState({
    businessType: '',
    businessName: '',
    businessDescription: '',
    rif: '',
    address: ''
  });

  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleNext = () => {
    if (currentStep < 2) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    } else {
      navigation.goBack();
    }
  };

  const handleCreateBusiness = async () => {
    // Prevent double-clicks
    if (isCreating) {
      return;
    }

    // Rate limiting: Prevent rapid successive attempts
    const now = Date.now();
    const timeSinceLastAttempt = now - lastCreateAttempt.current;
    if (timeSinceLastAttempt < 2000) { // 2 seconds minimum between attempts
      Alert.alert(
        'Muy rápido',
        'Por favor, espera unos segundos antes de intentar de nuevo.',
        [{ text: 'Entendido' }]
      );
      return;
    }
    lastCreateAttempt.current = now;

    try {
      setIsCreating(true);
      
      // Get the business type name for the category
      const businessType = businessTypes.find(type => type.id === formData.businessType);
      const category = businessType?.id || formData.businessType;
      
      // Create the business on the server
      const result = await createBusiness({
        variables: {
          name: formData.businessName,
          description: formData.businessDescription || undefined,
          category: category,
          businessRegistrationNumber: formData.rif || undefined,
          address: formData.address || undefined
        }
      });
      
      if (result.data?.createBusiness?.success) {
        const createdAccount = result.data.createBusiness.account;
        const createdBusiness = result.data.createBusiness.business;
        
        
        // No need to generate address here - it will be generated automatically
        // when the user switches to or initializes this business account
        
        // Fetch updated accounts from server to get the new business account
        const { data: accountsData } = await refetchAccounts();
        
        // Sync local account manager with server data
        if (accountsData?.userAccounts) {
          await syncWithServer(accountsData.userAccounts);
        }
        
        // Frictionless: the new business account appearing in the switcher
        // is the confirmation.
        navigation.goBack();
      } else {
        const error = result.data?.createBusiness?.error || 'Error desconocido';
        Alert.alert('Error', error);
      }
    } catch (error) {
      Alert.alert(
        'Error',
        'No se pudo crear la cuenta de negocio. Por favor, inténtalo de nuevo.',
        [{ text: 'Entendido' }]
      );
    } finally {
      setIsCreating(false);
    }
  };

  const renderProgressBar = () => (
    <View style={styles.progressContainer}>
      <View style={styles.progressHeader}>
        <Text style={styles.progressText}>Paso {currentStep} de 2</Text>
        <Text style={styles.progressPercentage}>{Math.round((currentStep / 2) * 100)}%</Text>
      </View>
      <View style={styles.progressBar}>
        <View 
          style={[
            styles.progressFill,
            { width: `${(currentStep / 2) * 100}%` }
          ]}
        />
      </View>
    </View>
  );

  const renderStep1 = () => (
    <View style={styles.stepContainer}>
      <View style={styles.stepContent}>
        <View style={styles.stepHeader}>
          <View style={styles.stepIconContainer}>
            <Icon name="shopping-bag" size={32} color={colors.primaryDark} />
          </View>
          <Text style={styles.stepTitle}>Tipo de Negocio</Text>
          <Text style={styles.stepSubtitle}>
            Selecciona el tipo de negocio que mejor describe tu empresa
          </Text>
        </View>

        <View style={styles.businessTypesList}>
          {businessTypes.map((type) => (
            <TouchableOpacity
              key={type.id}
              style={[
                styles.businessTypeCard,
                formData.businessType === type.id && styles.selectedBusinessType
              ]}
              onPress={() => handleInputChange('businessType', type.id)}
            >
              <View style={styles.businessTypeContent}>
                <View style={[
                  styles.businessTypeIcon,
                  formData.businessType === type.id && styles.selectedBusinessTypeIcon
                ]}>
                  <Icon 
                    name={type.icon as any} 
                    size={24} 
                    color={formData.businessType === type.id ? colors.white : colors.text.secondary} 
                  />
                </View>
                <View style={styles.businessTypeInfo}>
                  <Text style={styles.businessTypeName}>{type.name}</Text>
                  <Text style={styles.businessTypeDescription}>{type.description}</Text>
                </View>
                {formData.businessType === type.id && (
                  <Icon name="check" size={24} color={colors.primaryDark} />
                )}
              </View>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <View style={styles.stepFooter}>
        <Button
          title="Continuar"
          onPress={handleNext}
          disabled={!formData.businessType}
          style={{ backgroundColor: !formData.businessType ? colors.neutralDark : colors.primaryDark, borderRadius: 16 }}
          textStyle={{ fontSize: 18, color: !formData.businessType ? colors.text.light : colors.white }}
        />
      </View>
    </View>
  );

  const renderStep2 = () => (
    <View style={styles.stepContainer}>
      <View style={styles.stepContent}>
        <View style={styles.stepHeader}>
          <View style={styles.stepIconContainer}>
            <Icon name="shopping-bag" size={32} color={colors.primaryDark} />
          </View>
          <Text style={styles.stepTitle}>Información del Negocio</Text>
          <Text style={styles.stepSubtitle}>
            Completa los datos básicos de tu empresa
          </Text>
        </View>

        <View style={styles.formContainer}>
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Nombre del Negocio *</Text>
            <TextInput
              style={styles.textInput}
              placeholder="Ej: Restaurante El Sabor"
              value={formData.businessName}
              onChangeText={(value) => handleInputChange('businessName', value)}
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Descripción del Negocio</Text>
            <TextInput
              style={[styles.textInput, styles.textArea]}
              placeholder="Describe brevemente tu negocio..."
              value={formData.businessDescription}
              onChangeText={(value) => handleInputChange('businessDescription', value)}
              multiline
              numberOfLines={4}
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Número de Registro del Negocio</Text>
            <TextInput
              style={styles.textInput}
              placeholder="Opcional - si tu negocio está registrado"
              value={formData.rif}
              onChangeText={(value) => handleInputChange('rif', value)}
            />
            <Text style={styles.inputHelp}>
              RIF, Licencia Comercial, o Número de Registro (si está disponible)
            </Text>
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Dirección</Text>
            <TextInput
              style={[styles.textInput, styles.textArea]}
              placeholder="Dirección del negocio (opcional para negocios online)"
              value={formData.address}
              onChangeText={(value) => handleInputChange('address', value)}
              multiline
              numberOfLines={3}
            />
            <Text style={styles.inputHelp}>
              Deja vacío si es un negocio online sin ubicación física
            </Text>
          </View>

          <View style={styles.infoCard}>
            <Text style={styles.infoTitle}>Cuenta Personal Vinculada:</Text>
            <Text style={styles.infoText}>
              Esta cuenta de negocio estará vinculada a tu cuenta personal de Julian Moon. 
              Podrás cambiar entre cuentas fácilmente desde el menú principal.
            </Text>
          </View>
        </View>
      </View>

      <View style={styles.stepFooter}>
        <View style={styles.footerButtons}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={handleBack}
          >
            <Text style={styles.backButtonText}>Atrás</Text>
          </TouchableOpacity>
          <Button
            title="Crear Negocio"
            onPress={handleCreateBusiness}
            loading={isCreating}
            disabled={!formData.businessName}
            accessibilityLabel="Crear negocio"
            style={{ flex: 1, backgroundColor: !formData.businessName ? colors.neutralDark : colors.primaryDark, borderRadius: 16 }}
            textStyle={{ fontSize: 18, color: !formData.businessName ? colors.text.light : colors.white }}
          />
        </View>
      </View>
    </View>
  );

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Crear Cuenta de Negocio"
        backgroundColor={colors.primaryDark}
        isLight={true}
        showBackButton={true}
      />

      {/* Progress Bar */}
      {renderProgressBar()}

      {/* Content */}
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {currentStep === 1 && renderStep1()}
        {currentStep === 2 && renderStep2()}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  progressContainer: {
    backgroundColor: colors.white,
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  progressHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  progressText: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  progressPercentage: {
    fontSize: 15,
    color: colors.text.light,
  },
  progressBar: {
    height: 8,
    backgroundColor: colors.border,
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.primaryDark,
    borderRadius: 4,
  },
  content: {
    flex: 1,
    paddingBottom: 20,
  },
  stepContainer: {
    flex: 1,
    flexDirection: 'column',
  },
  stepContent: {
    flex: 1,
  },
  stepHeader: {
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingVertical: 32,
  },
  stepIconContainer: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primaryLight,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
  },
  stepTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 12,
    textAlign: 'center',
  },
  stepSubtitle: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 24,
    paddingHorizontal: 20,
  },
  businessTypesList: {
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  businessTypeCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: colors.border,
    marginBottom: 16,
    padding: 20,
  },
  selectedBusinessType: {
    borderColor: colors.primaryDark,
    backgroundColor: '#f0fdf4',
  },
  businessTypeContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  businessTypeIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 20,
  },
  selectedBusinessTypeIcon: {
    backgroundColor: colors.primaryDark,
  },
  businessTypeInfo: {
    flex: 1,
  },
  businessTypeName: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 6,
  },
  businessTypeDescription: {
    fontSize: 15,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  stepFooter: {
    paddingHorizontal: 20,
    paddingVertical: 20,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.white,
  },
  formContainer: {
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  inputGroup: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 10,
  },
  textInput: {
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 16,
    fontSize: 16,
    backgroundColor: colors.white,
  },
  textArea: {
    height: 100,
    textAlignVertical: 'top',
  },
  inputHelp: {
    fontSize: 13,
    color: colors.text.light,
    marginTop: 6,
  },
  infoCard: {
    backgroundColor: '#f0fdf4',
    borderWidth: 1,
    borderColor: '#bbf7d0',
    borderRadius: 12,
    padding: 20,
    marginTop: 12,
  },
  infoTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#166534',
    marginBottom: 10,
  },
  infoText: {
    fontSize: 15,
    color: '#15803d',
    lineHeight: 22,
  },
  footerButtons: {
    flexDirection: 'row',
    gap: 16,
  },
  backButton: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderRadius: 16,
    paddingVertical: 18,
    alignItems: 'center',
  },
  backButtonText: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
});