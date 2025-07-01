import React, { useState } from 'react';
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
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList, RootStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import { useAccountManager } from '../hooks/useAccountManager';

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
  const { createAccount } = useAccountManager();
  const [currentStep, setCurrentStep] = useState(1);
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
    try {
      // Get the business type name for the category
      const businessType = businessTypes.find(type => type.id === formData.businessType);
      const category = businessType?.name || formData.businessType;
      
      // Create the business account
      const newAccount = await createAccount(
        formData.businessName,
        formData.businessName.charAt(0).toUpperCase(), // Use first letter as avatar
        undefined, // No phone for business accounts
        category
      );
      
      console.log('Business account created successfully:', {
        accountId: newAccount.id,
        accountType: newAccount.type,
        accountIndex: newAccount.index,
        name: newAccount.name,
        category: newAccount.category
      });
      
      Alert.alert(
        'Éxito',
        'Cuenta de negocio creada exitosamente!',
        [
          {
            text: 'OK',
            onPress: () => navigation.goBack()
          }
        ]
      );
    } catch (error) {
      console.error('Error creating business account:', error);
      Alert.alert(
        'Error',
        'No se pudo crear la cuenta de negocio. Por favor, inténtalo de nuevo.',
        [{ text: 'OK' }]
      );
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
            <Icon name="shopping-bag" size={32} color="#10b981" />
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
                    color={formData.businessType === type.id ? '#fff' : '#6b7280'} 
                  />
                </View>
                <View style={styles.businessTypeInfo}>
                  <Text style={styles.businessTypeName}>{type.name}</Text>
                  <Text style={styles.businessTypeDescription}>{type.description}</Text>
                </View>
                {formData.businessType === type.id && (
                  <Icon name="check" size={24} color="#10b981" />
                )}
              </View>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <View style={styles.stepFooter}>
        <TouchableOpacity
          style={[
            styles.continueButton,
            !formData.businessType && styles.disabledButton
          ]}
          onPress={handleNext}
          disabled={!formData.businessType}
        >
          <Text style={[
            styles.continueButtonText,
            !formData.businessType && styles.disabledButtonText
          ]}>
            Continuar
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  const renderStep2 = () => (
    <View style={styles.stepContainer}>
      <View style={styles.stepContent}>
        <View style={styles.stepHeader}>
          <View style={styles.stepIconContainer}>
            <Icon name="shopping-bag" size={32} color="#10b981" />
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
            <Text style={styles.inputLabel}>Business Registration Number</Text>
            <TextInput
              style={styles.textInput}
              placeholder="Optional - if your business is registered"
              value={formData.rif}
              onChangeText={(value) => handleInputChange('rif', value)}
            />
            <Text style={styles.inputHelp}>
              Tax ID, Business License, or Registration Number (if available)
            </Text>
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Dirección *</Text>
            <TextInput
              style={[styles.textInput, styles.textArea]}
              placeholder="Dirección completa del negocio"
              value={formData.address}
              onChangeText={(value) => handleInputChange('address', value)}
              multiline
              numberOfLines={3}
            />
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
          <TouchableOpacity
            style={[
              styles.createButton,
              (!formData.businessName || !formData.address) && styles.disabledButton
            ]}
            onPress={handleCreateBusiness}
            disabled={!formData.businessName || !formData.address}
          >
            <Text style={[
              styles.createButtonText,
              (!formData.businessName || !formData.address) && styles.disabledButtonText
            ]}>
              Crear Negocio
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Crear Cuenta de Negocio"
        backgroundColor="#10b981"
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
    backgroundColor: '#fff',
  },
  progressContainer: {
    backgroundColor: '#fff',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
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
    color: '#6b7280',
  },
  progressPercentage: {
    fontSize: 15,
    color: '#9ca3af',
  },
  progressBar: {
    height: 8,
    backgroundColor: '#e5e7eb',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#10b981',
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
    backgroundColor: '#d1fae5',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
  },
  stepTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 12,
    textAlign: 'center',
  },
  stepSubtitle: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 24,
    paddingHorizontal: 20,
  },
  businessTypesList: {
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  businessTypeCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    marginBottom: 16,
    padding: 20,
  },
  selectedBusinessType: {
    borderColor: '#10b981',
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
    backgroundColor: '#f3f4f6',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 20,
  },
  selectedBusinessTypeIcon: {
    backgroundColor: '#10b981',
  },
  businessTypeInfo: {
    flex: 1,
  },
  businessTypeName: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 6,
  },
  businessTypeDescription: {
    fontSize: 15,
    color: '#6b7280',
    lineHeight: 20,
  },
  stepFooter: {
    paddingHorizontal: 20,
    paddingVertical: 20,
    borderTopWidth: 1,
    borderTopColor: '#e5e7eb',
    backgroundColor: '#fff',
  },
  continueButton: {
    backgroundColor: '#10b981',
    borderRadius: 16,
    paddingVertical: 18,
    alignItems: 'center',
  },
  disabledButton: {
    backgroundColor: '#f3f4f6',
  },
  continueButtonText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  disabledButtonText: {
    color: '#9ca3af',
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
    color: '#374151',
    marginBottom: 10,
  },
  textInput: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 16,
    fontSize: 16,
    backgroundColor: '#fff',
  },
  textArea: {
    height: 100,
    textAlignVertical: 'top',
  },
  inputHelp: {
    fontSize: 13,
    color: '#9ca3af',
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
    borderColor: '#d1d5db',
    borderRadius: 16,
    paddingVertical: 18,
    alignItems: 'center',
  },
  backButtonText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#374151',
  },
  createButton: {
    flex: 1,
    backgroundColor: '#10b981',
    borderRadius: 16,
    paddingVertical: 18,
    alignItems: 'center',
  },
  createButtonText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
}); 