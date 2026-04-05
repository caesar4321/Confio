import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Animated,
  StatusBar,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NavigationProp, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';

import { GET_MY_RAMP_ADDRESS, UPSERT_RAMP_USER_ADDRESS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { getCountryByIso } from '../utils/countries';
import { colors } from '../config/theme';

type Navigation = NavigationProp<MainStackParamList>;

export const RampAddressScreen: React.FC = () => {
  const navigation = useNavigation<Navigation>();
  const { userProfile } = useAuth();
  const { data, loading } = useQuery(GET_MY_RAMP_ADDRESS, {
    fetchPolicy: 'cache-and-network',
  });
  const [upsertRampAddress] = useMutation(UPSERT_RAMP_USER_ADDRESS);

  const [addressStreet, setAddressStreet] = useState('');
  const [addressCity, setAddressCity] = useState('');
  const [addressState, setAddressState] = useState('');
  const [addressZipCode, setAddressZipCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const successOpacity = useRef(new Animated.Value(0)).current;

  const rampAddress = data?.myRampAddress;
  const phoneCountryIso = String(userProfile?.phoneCountry || '').toUpperCase();
  const phoneCountry = useMemo(() => {
    if (!phoneCountryIso) return null;
    return getCountryByIso(phoneCountryIso);
  }, [phoneCountryIso]);

  useEffect(() => {
    setAddressStreet(rampAddress?.addressStreet || '');
    setAddressCity(rampAddress?.addressCity || '');
    setAddressState(rampAddress?.addressState || '');
    setAddressZipCode(rampAddress?.addressZipCode || '');
  }, [
    rampAddress?.addressStreet,
    rampAddress?.addressCity,
    rampAddress?.addressState,
    rampAddress?.addressZipCode,
  ]);

  const hasChanges = useMemo(() => {
    return (
      addressStreet.trim() !== (rampAddress?.addressStreet || '') ||
      addressCity.trim() !== (rampAddress?.addressCity || '') ||
      addressState.trim() !== (rampAddress?.addressState || '') ||
      addressZipCode.trim() !== (rampAddress?.addressZipCode || '')
    );
  }, [addressStreet, addressCity, addressState, addressZipCode, rampAddress]);

  const showSuccessBanner = () => {
    setSavedSuccess(true);
    Animated.sequence([
      Animated.timing(successOpacity, { toValue: 1, duration: 250, useNativeDriver: true }),
      Animated.delay(2000),
      Animated.timing(successOpacity, { toValue: 0, duration: 400, useNativeDriver: true }),
    ]).start(() => {
      setSavedSuccess(false);
      navigation.goBack();
    });
  };

  const validate = () => {
    if (!addressStreet.trim()) return 'Ingresa tu dirección.';
    if (!addressCity.trim()) return 'Ingresa tu ciudad.';
    if (!addressState.trim()) return 'Ingresa tu provincia o estado.';
    if (!addressZipCode.trim()) return 'Ingresa tu código postal.';
    if (!phoneCountryIso) return 'Primero configura el país de tu número de teléfono.';
    return null;
  };

  const handleSave = async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const { data: response } = await upsertRampAddress({
        variables: {
          addressStreet: addressStreet.trim(),
          addressCity: addressCity.trim(),
          addressState: addressState.trim(),
          addressZipCode: addressZipCode.trim(),
        },
        refetchQueries: [{ query: GET_MY_RAMP_ADDRESS }],
        awaitRefetchQueries: true,
      });

      const result = response?.upsertRampUserAddress;
      if (!result?.success) {
        setError(result?.error || 'No se pudo guardar tu dirección.');
        return;
      }

      showSuccessBanner();
    } catch (mutationError) {
      setError('No se pudo guardar tu dirección. Inténtalo nuevamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const countryName = rampAddress?.countryName || phoneCountry?.[0] || phoneCountryIso || 'Sin configurar';
  const countryFlag = phoneCountry?.[3] || '';
  const isButtonDisabled = isSaving || !hasChanges;

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={20} color="#ffffff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Dirección</Text>
        <View style={styles.headerSpacer} />
      </View>

      {savedSuccess && (
        <Animated.View style={[styles.successBanner, { opacity: successOpacity }]}>
          <Icon name="check-circle" size={16} color={colors.successText} />
          <Text style={styles.successBannerText}>Dirección guardada</Text>
        </Animated.View>
      )}

      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.infoCard}>
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Icon name="map-pin" size={15} color={colors.primaryDark} />
            </View>
            <Text style={styles.infoText}>
              La usamos para completar tus datos cuando un proveedor bancario la necesita para habilitar recargas y retiros.
            </Text>
          </View>
          <Text style={styles.infoHint}>
            El país se toma automáticamente desde el país de tu número de teléfono.
          </Text>
        </View>

        <View style={styles.formCard}>
          <Text style={[styles.label, styles.labelFirst]}>País</Text>
          <View style={styles.readOnlyField}>
            {loading ? (
              <ActivityIndicator size="small" color={colors.primaryDark} />
            ) : (
              <View style={styles.readOnlyInner}>
                {countryFlag ? <Text style={styles.flagEmoji}>{countryFlag}</Text> : null}
                <Text style={styles.readOnlyValue}>{countryName}</Text>
              </View>
            )}
          </View>

          <Text style={styles.label}>Dirección</Text>
          <View style={styles.inputWrapper}>
            <Icon name="home" size={15} color={colors.textSecondary} style={styles.inputIcon} />
            <TextInput
              style={styles.inputWithIcon}
              value={addressStreet}
              onChangeText={t => { setAddressStreet(t); setError(null); }}
              placeholder="Calle y número"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="words"
            />
          </View>

          <Text style={styles.label}>Ciudad</Text>
          <View style={styles.inputWrapper}>
            <Icon name="map" size={15} color={colors.textSecondary} style={styles.inputIcon} />
            <TextInput
              style={styles.inputWithIcon}
              value={addressCity}
              onChangeText={t => { setAddressCity(t); setError(null); }}
              placeholder="Ciudad"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="words"
            />
          </View>

          <Text style={styles.label}>Provincia o estado</Text>
          <View style={styles.inputWrapper}>
            <Icon name="flag" size={15} color={colors.textSecondary} style={styles.inputIcon} />
            <TextInput
              style={styles.inputWithIcon}
              value={addressState}
              onChangeText={t => { setAddressState(t); setError(null); }}
              placeholder="Provincia o estado"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="words"
            />
          </View>

          <Text style={styles.label}>Código postal</Text>
          <View style={styles.inputWrapper}>
            <Icon name="hash" size={15} color={colors.textSecondary} style={styles.inputIcon} />
            <TextInput
              style={styles.inputWithIcon}
              value={addressZipCode}
              onChangeText={t => { setAddressZipCode(t); setError(null); }}
              placeholder="Código postal"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="characters"
            />
          </View>

          {error ? (
            <View style={styles.errorBanner}>
              <Icon name="alert-circle" size={14} color={colors.error} />
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : null}

          <TouchableOpacity
            style={[styles.saveButton, isButtonDisabled && styles.saveButtonDisabled]}
            disabled={isButtonDisabled}
            onPress={handleSave}
          >
            {isSaving ? (
              <ActivityIndicator size="small" color="#FFFFFF" />
            ) : (
              <Text style={styles.saveButtonText}>Guardar dirección</Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.primaryDark,
  },
  backButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    marginHorizontal: 12,
    fontSize: 17,
    fontWeight: '700',
    color: '#ffffff',
  },
  headerSpacer: {
    width: 36,
  },
  successBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 16,
    marginBottom: 4,
    paddingVertical: 10,
    paddingHorizontal: 14,
    backgroundColor: colors.successLight,
    borderRadius: 12,
  },
  successBannerText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.successText,
  },
  content: {
    padding: 16,
    paddingBottom: 32,
    gap: 16,
  },
  infoCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  infoIconWrap: {
    marginTop: 1,
  },
  infoText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 20,
    color: colors.textFlat,
  },
  infoHint: {
    marginTop: 10,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
  },
  formCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
  },
  labelFirst: {
    marginTop: 0,
  },
  label: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: 6,
    marginTop: 14,
  },
  readOnlyField: {
    minHeight: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: '#F9FAFB',
    justifyContent: 'center',
    paddingHorizontal: 14,
  },
  readOnlyInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  flagEmoji: {
    fontSize: 20,
  },
  readOnlyValue: {
    fontSize: 15,
    color: colors.textFlat,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 14,
  },
  inputIcon: {
    marginRight: 10,
  },
  inputWithIcon: {
    flex: 1,
    height: 48,
    fontSize: 15,
    color: colors.textFlat,
  },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: colors.errorLight,
    borderRadius: 10,
  },
  errorText: {
    flex: 1,
    fontSize: 13,
    color: colors.error,
  },
  saveButton: {
    marginTop: 20,
    height: 50,
    borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButtonDisabled: {
    opacity: 0.45,
  },
  saveButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#FFFFFF',
  },
});

export default RampAddressScreen;
