import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Modal,
  FlatList,
  ActivityIndicator,
  StatusBar,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NavigationProp, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';

import { GET_MY_RAMP_ADDRESS, UPSERT_RAMP_USER_ADDRESS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { AnalyticsService } from '../services/analyticsService';
import { getCountryByIso } from '../utils/countries';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';

type Navigation = NavigationProp<MainStackParamList>;
type EconomicActivityOption = {
  label: string;
  value: string;
};

export const RampAddressScreen: React.FC = () => {
  const navigation = useNavigation<Navigation>();
  const { userProfile } = useAuth();
  const { data, loading } = useQuery(GET_MY_RAMP_ADDRESS, {
    fetchPolicy: 'cache-and-network',
  });
  const [upsertRampAddress] = useMutation(UPSERT_RAMP_USER_ADDRESS);

  const [addressStreet, setAddressStreet] = useState('');
  const [addressNeighborhood, setAddressNeighborhood] = useState('');
  const [addressCity, setAddressCity] = useState('');
  const [addressState, setAddressState] = useState('');
  const [addressZipCode, setAddressZipCode] = useState('');
  const [economicActivity, setEconomicActivity] = useState('');
  const [activitySearch, setActivitySearch] = useState('');
  const [showActivityPicker, setShowActivityPicker] = useState(false);
  const [authEmail, setAuthEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const rampAddress = data?.myRampAddress;
  const phoneCountryIso = String(userProfile?.phoneCountry || '').toUpperCase();
  const phoneCountry = useMemo(() => {
    if (!phoneCountryIso) return null;
    return getCountryByIso(phoneCountryIso);
  }, [phoneCountryIso]);
  const accountEmail = String(userProfile?.email || '').trim().toLowerCase();
  const isAppleRelayEmail = /@privaterelay\.appleid\.com$/i.test(accountEmail);
  const shouldShowAuthEmailField = phoneCountryIso === 'CO' && isAppleRelayEmail;
  const economicActivities: EconomicActivityOption[] = data?.economicActivities || [];
  const shouldShowEconomicActivityField = economicActivities.length > 0;
  const addressRequirements = data?.rampAddressRequirements;
  const shouldShowAddressNeighborhoodField = Boolean(addressRequirements?.requiresAddressNeighborhood);
  const addressNeighborhoodLabel = addressRequirements?.addressNeighborhoodLabel || 'Colonia o barrio';
  const addressNeighborhoodPlaceholder = addressRequirements?.addressNeighborhoodPlaceholder || addressNeighborhoodLabel;
  const filteredEconomicActivities = useMemo(() => {
    const query = activitySearch.trim().toLowerCase();
    if (!query) {
      return economicActivities;
    }
    return economicActivities.filter(activity =>
      activity.label.toLowerCase().includes(query) || activity.value.toLowerCase().includes(query),
    );
  }, [activitySearch, economicActivities]);

  useEffect(() => {
    setAddressStreet(rampAddress?.addressStreet || '');
    setAddressNeighborhood(rampAddress?.addressNeighborhood || '');
    setAddressCity(rampAddress?.addressCity || '');
    setAddressState(rampAddress?.addressState || '');
    setAddressZipCode(rampAddress?.addressZipCode || '');
    setEconomicActivity(rampAddress?.economicActivity || '');
    setAuthEmail(rampAddress?.authEmail || '');
  }, [
    rampAddress?.addressStreet,
    rampAddress?.addressNeighborhood,
    rampAddress?.addressCity,
    rampAddress?.addressState,
    rampAddress?.addressZipCode,
    rampAddress?.economicActivity,
    rampAddress?.authEmail,
  ]);

  const hasChanges = useMemo(() => {
    return (
      addressStreet.trim() !== (rampAddress?.addressStreet || '') ||
      (shouldShowAddressNeighborhoodField && addressNeighborhood.trim() !== (rampAddress?.addressNeighborhood || '')) ||
      addressCity.trim() !== (rampAddress?.addressCity || '') ||
      addressState.trim() !== (rampAddress?.addressState || '') ||
      addressZipCode.trim() !== (rampAddress?.addressZipCode || '') ||
      (shouldShowEconomicActivityField && economicActivity.trim() !== (rampAddress?.economicActivity || '')) ||
      (shouldShowAuthEmailField && authEmail.trim().toLowerCase() !== String(rampAddress?.authEmail || '').trim().toLowerCase())
    );
  }, [
    addressStreet,
    addressNeighborhood,
    addressCity,
    addressState,
    addressZipCode,
    economicActivity,
    authEmail,
    rampAddress,
    shouldShowAuthEmailField,
    shouldShowAddressNeighborhoodField,
    shouldShowEconomicActivityField,
  ]);

  const validate = () => {
    if (!addressStreet.trim()) return 'Ingresa tu dirección.';
    if (shouldShowAddressNeighborhoodField && !addressNeighborhood.trim()) return `Ingresa tu ${addressNeighborhoodLabel.toLowerCase()}.`;
    if (!addressCity.trim()) return 'Ingresa tu ciudad.';
    if (!addressState.trim()) return 'Ingresa tu provincia o estado.';
    if (!addressZipCode.trim()) return 'Ingresa tu código postal.';
    if (shouldShowEconomicActivityField && !economicActivity.trim()) return 'Ingresa tu actividad económica.';
    if (shouldShowAuthEmailField) {
      const normalizedAuthEmail = authEmail.trim().toLowerCase();
      if (!normalizedAuthEmail) return 'Ingresa un email real para recibir códigos de PSE.';
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedAuthEmail)) return 'Ingresa un email válido.';
      if (/@privaterelay\.appleid\.com$/i.test(normalizedAuthEmail)) return 'Usa un email real, no un Apple private relay.';
    }
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
          addressNeighborhood: shouldShowAddressNeighborhoodField ? addressNeighborhood.trim() : undefined,
          addressCity: addressCity.trim(),
          addressState: addressState.trim(),
          addressZipCode: addressZipCode.trim(),
          economicActivity: shouldShowEconomicActivityField ? economicActivity.trim() : undefined,
          authEmail: shouldShowAuthEmailField ? authEmail.trim().toLowerCase() : undefined,
        },
        refetchQueries: [{ query: GET_MY_RAMP_ADDRESS }],
        awaitRefetchQueries: true,
      });

      const result = response?.upsertRampUserAddress;
      if (!result?.success) {
        setError(result?.error || 'No se pudo guardar tu dirección.');
        return;
      }

      void AnalyticsService.logEvent('ramp_profile_completed', {
        provider: 'koywe',
        country: phoneCountryIso || '',
        has_auth_email: shouldShowAuthEmailField && Boolean(authEmail.trim()),
      });
      // No interstitial: the saved address on the previous screen is the
      // confirmation.
      navigation.goBack();
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
    <View style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header
        navigation={navigation as any}
        title="Recargas y retiros"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {/* Emerald brand field: this is a money-rails screen. Lead with the
            payoff, not the chore — vertical gradient meets the flat nav
            header seamlessly; padding on fieldInner (Yoga rule). */}
        <View style={styles.brandField}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="rampField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#rampField)" />
            <Circle cx="105%" cy="16%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.fieldInner}>
            <Text style={styles.fieldEyebrow}>RECARGAS Y RETIROS</Text>
            <Text style={styles.fieldTitle}>Conecta tu banco a Confío</Text>
            <Text style={styles.fieldSubtitle}>
              Los proveedores bancarios necesitan estos datos para habilitar
              recargas y retiros. Los completas una sola vez.
            </Text>
            <View style={styles.fieldTrustRow}>
              <Icon name="lock" size={13} color={colors.primaryLight} />
              <Text style={styles.fieldTrustText}>
                Solo se comparten con el proveedor cuando tú inicias una operación
              </Text>
            </View>
          </View>
        </View>

        <View style={styles.body}>
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
          <Text style={styles.fieldHelp}>
            Se toma automáticamente del país de tu número de teléfono.
          </Text>

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

          {shouldShowAddressNeighborhoodField ? (
            <>
              <Text style={styles.label}>{addressNeighborhoodLabel}</Text>
              <View style={styles.inputWrapper}>
                <Icon name="map-pin" size={15} color={colors.textSecondary} style={styles.inputIcon} />
                <TextInput
                  style={styles.inputWithIcon}
                  value={addressNeighborhood}
                  onChangeText={t => { setAddressNeighborhood(t); setError(null); }}
                  placeholder={addressNeighborhoodPlaceholder}
                  placeholderTextColor={colors.textSecondary}
                  autoCapitalize="words"
                />
              </View>
            </>
          ) : null}

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

          {shouldShowEconomicActivityField ? (
            <>
              <Text style={styles.label}>Actividad económica</Text>
              <TouchableOpacity
                style={styles.inputWrapper}
                activeOpacity={0.8}
                onPress={() => {
                  setActivitySearch('');
                  setShowActivityPicker(true);
                }}
                accessibilityRole="button"
                accessibilityLabel={economicActivity ? `Actividad económica: ${economicActivity}` : 'Seleccionar actividad económica'}
              >
                <Icon name="briefcase" size={15} color={colors.textSecondary} style={styles.inputIcon} />
                <Text
                  numberOfLines={1}
                  style={[styles.pickerValue, !economicActivity && styles.pickerPlaceholder]}
                >
                  {economicActivity || 'Selecciona una actividad'}
                </Text>
                <Icon name="chevron-down" size={16} color={colors.textSecondary} />
              </TouchableOpacity>
              <Text style={styles.fieldHelp}>
                Koywe la requiere para cumplir requisitos regulatorios.
              </Text>
            </>
          ) : null}

          {shouldShowAuthEmailField ? (
            <>
              <Text style={styles.label}>Email para códigos de PSE</Text>
              <View style={styles.inputWrapper}>
                <Icon name="mail" size={15} color={colors.textSecondary} style={styles.inputIcon} />
                <TextInput
                  style={styles.inputWithIcon}
                  value={authEmail}
                  onChangeText={t => { setAuthEmail(t); setError(null); }}
                  placeholder="tuemail@dominio.com"
                  placeholderTextColor={colors.textSecondary}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="email-address"
                />
              </View>
              <Text style={styles.fieldHelp}>
                Tu cuenta usa Apple private relay; aquí va el email real donde
                recibirás los códigos de PSE.
              </Text>
            </>
          ) : null}

          {error ? (
            <InlineBanner
              message={error}
              variant="error"
              onDismiss={() => setError(null)}
              style={{ marginTop: 12, marginBottom: 0 }}
            />
          ) : null}

          <Button
            title="Guardar dirección"
            onPress={handleSave}
            loading={isSaving}
            disabled={isButtonDisabled}
            style={{ marginTop: 20, backgroundColor: colors.primary }}
            textStyle={{ fontWeight: '700' }}
          />
        </View>
        </View>
      </ScrollView>

      <Modal
        visible={showActivityPicker}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowActivityPicker(false)}
      >
        <SafeAreaView style={styles.modalSafeArea}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowActivityPicker(false)} accessibilityRole="button" accessibilityLabel="Cancelar">
              <Text style={styles.modalCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Actividad económica</Text>
            <View style={styles.modalHeaderSpacer} />
          </View>
          <View style={styles.modalSearchWrapper}>
            <Icon name="search" size={16} color={colors.textSecondary} style={styles.inputIcon} />
            <TextInput
              style={styles.inputWithIcon}
              value={activitySearch}
              onChangeText={setActivitySearch}
              placeholder="Buscar actividad"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>
          <FlatList
            data={filteredEconomicActivities}
            keyExtractor={item => item.value}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.activityListContent}
            renderItem={({ item }) => {
              const selected = item.value === economicActivity;
              return (
                <TouchableOpacity
                  style={styles.activityItem}
                  onPress={() => {
                    setEconomicActivity(item.value);
                    setError(null);
                    setShowActivityPicker(false);
                  }}
                  accessibilityRole="button"
                  accessibilityLabel={item.label}
                  accessibilityState={{ selected: item.value === economicActivity }}
                >
                  <Text style={styles.activityItemText}>{item.label}</Text>
                  {selected ? <Icon name="check" size={18} color={colors.primary} /> : null}
                </TouchableOpacity>
              );
            }}
            ListEmptyComponent={
              <Text style={styles.activityEmptyText}>
                No encontramos esa actividad. Elige la opción más cercana del catálogo.
              </Text>
            }
          />
        </SafeAreaView>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 32,
  },
  brandField: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 24,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 8,
  },
  fieldTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.white,
    lineHeight: 30,
  },
  fieldSubtitle: {
    fontSize: 14,
    lineHeight: 21,
    color: 'rgba(255, 255, 255, 0.85)',
    marginTop: 8,
  },
  fieldTrustRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    marginTop: 14,
  },
  fieldTrustText: {
    flex: 1,
    fontSize: 12,
    fontWeight: '600',
    color: colors.primaryLight,
  },
  body: {
    padding: 16,
  },
  fieldHelp: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.textSecondary,
    marginTop: 6,
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
    backgroundColor: colors.neutral,
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
  pickerValue: {
    flex: 1,
    fontSize: 15,
    color: colors.textFlat,
  },
  pickerPlaceholder: {
    color: colors.textSecondary,
  },
  modalSafeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 14,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalCancel: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.primary,
  },
  modalTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textFlat,
  },
  modalHeaderSpacer: {
    width: 68,
  },
  modalSearchWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    margin: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
  },
  activityListContent: {
    paddingBottom: 24,
  },
  activityItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  activityItemText: {
    flex: 1,
    fontSize: 15,
    lineHeight: 20,
    color: colors.textFlat,
  },
  activityEmptyText: {
    padding: 20,
    fontSize: 14,
    lineHeight: 20,
    color: colors.textSecondary,
    textAlign: 'center',
  },
});

export default RampAddressScreen;
