import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Alert, Platform, StatusBar, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useMutation } from '@apollo/client';
import { UPDATE_USER_PROFILE, UPDATE_USERNAME } from '../apollo/queries';
import { getCountryByIso } from '../utils/countries';

// Colors from the design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

type EditProfileScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

// Utility function to format phone number with country code
const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  
  // If we have a country code, format it
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1]; // country[1] is the phone code (e.g., '+54')
      return `${countryCode} ${phoneNumber}`;
    }
  }
  
  return phoneNumber;
};

export const EditProfileScreen = () => {
  const { userProfile, isUserProfileLoading, refreshUserProfile } = useAuth();
  const navigation = useNavigation<EditProfileScreenNavigationProp>();
  
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [username, setUsername] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [usernameError, setUsernameError] = useState<string | null>(null);

  const [updateProfile] = useMutation(UPDATE_USER_PROFILE);
  const [updateUsername] = useMutation(UPDATE_USERNAME);

  // Check if user is verified
  const isVerified = userProfile?.isIdentityVerified || false;

  // Initialize form with current user data
  useEffect(() => {
    if (userProfile) {
      setFirstName(userProfile.firstName || '');
      setLastName(userProfile.lastName || '');
      setUsername(userProfile.username || '');
    }
  }, [userProfile]);

  const handleSave = async () => {
    if (isVerified) {
      Alert.alert(
        'No se puede editar', 
        'Tu identidad ya ha sido verificada. No puedes cambiar tu nombre legal.',
        [{ text: 'OK' }]
      );
      return;
    }

    if (!firstName.trim()) {
      Alert.alert('Error', 'El nombre es requerido');
      return;
    }

    if (!username.trim()) {
      Alert.alert('Error', 'El nombre de usuario es requerido');
      return;
    }

    // Validate username format
    const usernameValidation = validateUsername(username);
    if (usernameValidation) {
      Alert.alert('Error', usernameValidation);
      return;
    }

    setIsSaving(true);
    try {
      // Update profile (first name and last name)
      const profileResult = await updateProfile({
        variables: {
          firstName: firstName.trim(),
          lastName: lastName.trim(),
        },
      });

      // Update username
      const usernameResult = await updateUsername({
        variables: {
          username: username.trim(),
        },
      });

      if (profileResult.data?.updateUserProfile?.success && usernameResult.data?.updateUsername?.success) {
        Alert.alert(
          'Éxito', 
          'Perfil actualizado correctamente',
          [
            {
              text: 'OK',
              onPress: () => {
                refreshUserProfile();
                navigation.goBack();
              }
            }
          ]
        );
      } else {
        const profileError = profileResult.data?.updateUserProfile?.error;
        const usernameError = usernameResult.data?.updateUsername?.error;
        
        if (usernameError && usernameError.includes('ya está en uso')) {
          const suggestions = getUsernameSuggestions(username.trim());
          const suggestionsText = suggestions.map(s => '• ' + s).join('\n');
          Alert.alert(
            'Nombre de usuario no disponible',
            'Este nombre de usuario ya está en uso. Intenta con otro nombre, por ejemplo:\n\n' + suggestionsText,
            [
              {
                text: 'Entendido',
                style: 'default'
              }
            ]
          );
        } else {
          const errorMessage = profileError || usernameError || 'Error desconocido';
          Alert.alert('Error', errorMessage);
        }
      }
    } catch (error) {
      console.error('Error updating profile:', error);
      Alert.alert('Error', 'No se pudo actualizar el perfil. Inténtalo de nuevo.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    navigation.goBack();
  };

  const handleChangePhoneNumber = () => {
    navigation.navigate('PhoneVerification');
  };

  // Username validation and suggestions
  const validateUsername = (username: string) => {
    const trimmed = username.trim();
    if (trimmed.length < 3) {
      return 'El nombre de usuario debe tener al menos 3 caracteres';
    }
    if (trimmed.length > 30) {
      return 'El nombre de usuario no puede tener más de 30 caracteres';
    }
    if (!/^[a-zA-Z0-9_]+$/.test(trimmed)) {
      return 'Solo se permiten letras, números y guiones bajos (_)';
    }
    return null;
  };

  const getUsernameSuggestions = (baseUsername: string) => {
    const suggestions = [
      baseUsername + '123',
      baseUsername + '_2024',
      baseUsername + 'Real',
      baseUsername + 'Official',
      baseUsername + 'VE',
      baseUsername + 'Latam'
    ];
    return suggestions;
  };

  const handleUsernameChange = (text: string) => {
    setUsername(text);
    setUsernameError(null); // Clear previous errors
    
    if (text.trim()) {
      const validation = validateUsername(text);
      if (validation) {
        setUsernameError(validation);
      }
    }
  };

  if (isUserProfileLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity style={styles.backButton} onPress={handleCancel}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Cargando...</Text>
          <View style={styles.placeholder} />
        </View>
        <View style={styles.loadingContainer}>
          <Text style={styles.loadingText}>Cargando perfil...</Text>
        </View>
      </View>
    );
  }

  // If user is verified, show a different screen
  if (isVerified) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity style={styles.backButton} onPress={handleCancel}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Editar Perfil</Text>
          <View style={styles.placeholder} />
        </View>

        <View style={styles.verifiedContainer}>
          <View style={styles.verifiedIcon}>
            <Text style={styles.verifiedIconText}>✓</Text>
          </View>
          <Text style={styles.verifiedTitle}>Identidad Verificada</Text>
          <Text style={styles.verifiedDescription}>
            Tu identidad ha sido verificada. Tu nombre legal no puede ser modificado.
          </Text>
          
          <View style={styles.currentInfoContainer}>
            <Text style={styles.currentInfoLabel}>Nombre verificado:</Text>
            <Text style={styles.currentInfoText}>
              {userProfile?.firstName} {userProfile?.lastName}
            </Text>
            {userProfile?.lastVerifiedDate && (
              <>
                <Text style={styles.currentInfoLabel}>Verificado el:</Text>
                <Text style={styles.currentInfoText}>
                  {new Date(userProfile.lastVerifiedDate).toLocaleDateString('es-ES', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                  })}
                </Text>
              </>
            )}
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={handleCancel}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Editar Perfil</Text>
        <TouchableOpacity 
          style={[styles.saveButton, isSaving && styles.saveButtonDisabled]} 
          onPress={handleSave}
          disabled={isSaving}
        >
          <Text style={styles.saveButtonText}>
            {isSaving ? 'Guardando...' : 'Guardar'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Form */}
      <ScrollView 
        style={styles.scrollView}
        contentContainerStyle={styles.formContainer}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.inputGroup}>
          <Text style={styles.inputLabel}>Nombre</Text>
          <TextInput
            style={styles.textInput}
            value={firstName}
            onChangeText={setFirstName}
            placeholder="Ingresa tu nombre"
            placeholderTextColor="#9CA3AF"
            autoCapitalize="words"
            autoCorrect={false}
          />
        </View>

        <View style={styles.inputGroup}>
          <Text style={styles.inputLabel}>Apellido</Text>
          <TextInput
            style={styles.textInput}
            value={lastName}
            onChangeText={setLastName}
            placeholder="Ingresa tu apellido"
            placeholderTextColor="#9CA3AF"
            autoCapitalize="words"
            autoCorrect={false}
          />
        </View>

        <View style={styles.inputGroup}>
          <Text style={styles.inputLabel}>Nombre de usuario</Text>
          <View style={[
            styles.usernameInputContainer,
            usernameError && styles.usernameInputError
          ]}>
            <Text style={styles.atSymbol}>@</Text>
            <TextInput
              style={styles.usernameTextInput}
              value={username}
              onChangeText={handleUsernameChange}
              placeholder="usuario"
              placeholderTextColor="#9CA3AF"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="off"
            />
          </View>
          {usernameError ? (
            <Text style={styles.errorText}>{usernameError}</Text>
          ) : (
            <Text style={styles.inputSubtext}>
              Este será tu nombre de usuario único en Confío (3-30 caracteres)
            </Text>
          )}
        </View>

        <View style={styles.inputGroup}>
          <Text style={styles.inputLabel}>Número de teléfono</Text>
          <TouchableOpacity 
            style={styles.phoneInputContainer}
            onPress={handleChangePhoneNumber}
            activeOpacity={0.7}
          >
            <View style={styles.phoneInputContent}>
              <Text style={styles.phoneInputText}>
                {userProfile?.phoneNumber && userProfile?.phoneCountry 
                  ? formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry)
                  : 'No configurado'
                }
              </Text>
              <Icon name="chevron-right" size={20} color="#9CA3AF" />
            </View>
          </TouchableOpacity>
          <Text style={styles.phoneInputSubtext}>
            Toca para cambiar tu número de teléfono
          </Text>
        </View>

        <View style={styles.infoContainer}>
          <Icon name="info" size={16} color="#6B7280" />
          <Text style={styles.infoText}>
            Puedes cambiar tu nombre hasta que verifiques tu identidad. Una vez verificada, tu nombre legal no podrá ser modificado.
          </Text>
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
  header: {
    backgroundColor: '#34d399', // emerald-400
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
    paddingBottom: 16,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#fff',
  },
  saveButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    borderRadius: 8,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 14,
  },
  placeholder: {
    width: 40,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 16,
    color: '#6B7280',
  },
  scrollView: {
    flex: 1,
  },
  formContainer: {
    padding: 20,
  },
  inputGroup: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  textInput: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    color: '#1F2937',
    backgroundColor: '#F9FAFB',
  },
  inputSubtext: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  usernameInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    backgroundColor: '#F9FAFB',
  },
  atSymbol: {
    fontSize: 16,
    color: '#6B7280',
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontWeight: '500',
  },
  usernameTextInput: {
    flex: 1,
    paddingVertical: 12,
    paddingRight: 16,
    fontSize: 16,
    color: '#1F2937',
    backgroundColor: 'transparent',
  },
  usernameInputError: {
    borderColor: '#EF4444',
  },
  errorText: {
    fontSize: 12,
    color: '#EF4444',
    marginTop: 4,
  },
  phoneInputContainer: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    backgroundColor: '#F9FAFB',
    marginBottom: 4,
  },
  phoneInputContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  phoneInputText: {
    fontSize: 16,
    color: '#1F2937',
    flex: 1,
  },
  phoneInputSubtext: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  infoContainer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#F3F4F6',
    padding: 16,
    borderRadius: 12,
    marginTop: 16,
  },
  infoText: {
    fontSize: 14,
    color: '#6B7280',
    marginLeft: 8,
    flex: 1,
    lineHeight: 20,
  },
  verifiedContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  verifiedIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#10B981',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  verifiedIconText: {
    fontSize: 40,
    color: '#fff',
    fontWeight: 'bold',
  },
  verifiedTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
    textAlign: 'center',
  },
  verifiedDescription: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 32,
  },
  currentInfoContainer: {
    backgroundColor: '#F3F4F6',
    padding: 20,
    borderRadius: 12,
    width: '100%',
  },
  currentInfoLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 8,
  },
  currentInfoText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
  },
}); 