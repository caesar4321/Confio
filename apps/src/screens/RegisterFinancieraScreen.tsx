import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  StatusBar,
  Modal,
  FlatList,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { countries, Country } from '../utils/countries';
import { useCountry } from '../contexts/CountryContext';
import { FINANCIERA_SERVICES, MANDATORY_SERVICE_ID } from '../types/financiera';
import {
  GET_COUNTRY_SUBDIVISIONS,
  GET_FINANCIERA_LOCATION_OPTIONS,
} from '../apollo/queries';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

// Simulated: in production this reflects the owner's identity-verification status.
const USER_VERIFIED = true;

const CountryPickerModal = ({
  visible,
  onClose,
  onSelect,
}: {
  visible: boolean;
  onClose: () => void;
  onSelect: (c: Country) => void;
}) => {
  const [q, setQ] = useState('');
  const data = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return countries;
    return countries.filter((c) => String(c[0]).toLowerCase().includes(query));
  }, [q]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHandle} />
          <View style={styles.modalHeaderRow}>
            <Text style={styles.modalTitle}>Selecciona el país</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalIconBtn}>
              <Icon name="x" size={22} color={colors.text.primary} />
            </TouchableOpacity>
          </View>
          <View style={styles.searchBox}>
            <Icon name="search" size={18} color={colors.text.light} />
            <TextInput
              style={styles.searchInput}
              placeholder="Buscar país"
              placeholderTextColor={colors.text.light}
              value={q}
              onChangeText={setQ}
            />
          </View>
          <FlatList
            data={data}
            keyExtractor={(item) => String(item[2])}
            style={{ maxHeight: 420 }}
            initialNumToRender={20}
            maxToRenderPerBatch={15}
            windowSize={21}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => (
              <TouchableOpacity
                style={styles.optionRow}
                onPress={() => {
                  onSelect(item);
                  setQ('');
                }}
              >
                <Text style={styles.optionLabel}>
                  {item[3]}  {item[0]}
                </Text>
                <Text style={styles.optionCode}>{item[1]}</Text>
              </TouchableOpacity>
            )}
          />
        </View>
      </View>
    </Modal>
  );
};

// Searchable picker for the estado/provincia list (ISO 3166-2 names from the API).
const StatePickerModal = ({
  visible,
  options,
  onClose,
  onSelect,
}: {
  visible: boolean;
  options: string[];
  onClose: () => void;
  onSelect: (value: string) => void;
}) => {
  const [q, setQ] = useState('');
  const data = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return options;
    return options.filter((o) => o.toLowerCase().includes(query));
  }, [q, options]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHandle} />
          <View style={styles.modalHeaderRow}>
            <Text style={styles.modalTitle}>Estado / Provincia</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalIconBtn}>
              <Icon name="x" size={22} color={colors.text.primary} />
            </TouchableOpacity>
          </View>
          <View style={styles.searchBox}>
            <Icon name="search" size={18} color={colors.text.light} />
            <TextInput
              style={styles.searchInput}
              placeholder="Buscar"
              placeholderTextColor={colors.text.light}
              value={q}
              onChangeText={setQ}
            />
          </View>
          <FlatList
            data={data}
            keyExtractor={(item) => item}
            style={{ maxHeight: 420 }}
            initialNumToRender={20}
            maxToRenderPerBatch={15}
            windowSize={21}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => (
              <TouchableOpacity
                style={styles.optionRow}
                onPress={() => {
                  onSelect(item);
                  setQ('');
                }}
              >
                <Text style={styles.optionLabel}>{item}</Text>
              </TouchableOpacity>
            )}
          />
        </View>
      </View>
    </Modal>
  );
};

// Tappable suggestions under city/barrio inputs, sourced from existing
// listings so spellings converge instead of fragmenting the filter cascade.
const SuggestionChips = ({
  options,
  current,
  onPick,
}: {
  options: string[];
  current: string;
  onPick: (value: string) => void;
}) => {
  const text = current.trim().toLowerCase();
  const matches = options
    .filter((o) => o.toLowerCase() !== text)
    .filter((o) => !text || o.toLowerCase().includes(text))
    .slice(0, 6);
  if (!matches.length) return null;
  return (
    <View style={styles.suggestionRow}>
      {matches.map((o) => (
        <TouchableOpacity key={o} style={styles.suggestionChip} onPress={() => onPick(o)}>
          <Text style={styles.suggestionChipText}>{o}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
};

const VerificationGate = ({ onBack }: { onBack: () => void }) => (
  <View style={styles.gate}>
    <View style={styles.gateIcon}>
      <Icon name="user-check" size={32} color={colors.primaryDark} />
    </View>
    <Text style={styles.gateTitle}>Verifica tu identidad</Text>
    <Text style={styles.gateText}>
      Para registrar tu financiera primero verifica tu identidad. Esto da confianza a las
      personas que te contactarán.
    </Text>
    <TouchableOpacity style={styles.gatePrimary}>
      <Text style={styles.gatePrimaryText}>Verificar mi identidad</Text>
    </TouchableOpacity>
    <TouchableOpacity onPress={onBack}>
      <Text style={styles.gateSecondary}>Volver</Text>
    </TouchableOpacity>
  </View>
);

export const RegisterFinancieraScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { userCountry } = useCountry();

  const [name, setName] = useState('');
  const [country, setCountry] = useState<Country | null>(userCountry || null);
  const [state, setState] = useState('');
  const [city, setCity] = useState('');
  const [barrio, setBarrio] = useState('');
  const [whatsapp, setWhatsapp] = useState('');
  const [services, setServices] = useState<string[]>([]);
  const [countryModal, setCountryModal] = useState(false);
  const [stateModal, setStateModal] = useState(false);

  const countryIso = country ? String(country[2]) : null;

  // ISO 3166-2 estados/provincias for the picker; empty for the rare
  // territories ISO doesn't cover, where we fall back to free text.
  const { data: subdivisionsData } = useQuery(GET_COUNTRY_SUBDIVISIONS, {
    variables: { countryCode: countryIso },
    skip: !countryIso,
  });
  const subdivisions: string[] = (subdivisionsData?.countrySubdivisions || []).map(
    (s: { name: string }) => s.name,
  );

  // Existing listing locations, so city/barrio spellings converge.
  const { data: cityOptionsData } = useQuery(GET_FINANCIERA_LOCATION_OPTIONS, {
    variables: { level: 'city', state, countryCode: countryIso },
    skip: !countryIso || !state,
  });
  const { data: barrioOptionsData } = useQuery(GET_FINANCIERA_LOCATION_OPTIONS, {
    variables: { level: 'neighborhood', state, city, countryCode: countryIso },
    skip: !countryIso || !state || !city.trim(),
  });
  const cityOptions: string[] = cityOptionsData?.financieraLocationOptions || [];
  const barrioOptions: string[] = barrioOptionsData?.financieraLocationOptions || [];

  const toggleService = (id: string) =>
    setServices((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const supportsUsdcAlgorand = services.includes(MANDATORY_SERVICE_ID);
  const canSubmit =
    !!name.trim() &&
    !!country &&
    !!state.trim() &&
    !!city.trim() &&
    !!whatsapp.trim() &&
    supportsUsdcAlgorand;

  if (!USER_VERIFIED) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <Header title="Registrar financiera" onBack={() => navigation.goBack()} />
        <VerificationGate onBack={() => navigation.goBack()} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header title="Registrar financiera" onBack={() => navigation.goBack()} />

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.verifiedNote}>
            <Icon name="check-circle" size={16} color={colors.primaryDark} />
            <Text style={styles.verifiedNoteText}>
              Tu identidad está verificada. Las personas verán tu insignia de confianza.
            </Text>
          </View>

          {/* Name */}
          <View style={styles.field}>
            <Text style={styles.label}>Nombre de la financiera</Text>
            <TextInput
              style={styles.input}
              placeholder="Ej. Cambios El Ávila"
              placeholderTextColor={colors.text.light}
              value={name}
              onChangeText={setName}
            />
          </View>

          {/* Location */}
          <Text style={styles.sectionTitle}>Ubicación</Text>
          <View style={styles.field}>
            <Text style={styles.label}>País</Text>
            <TouchableOpacity style={styles.selectInput} onPress={() => setCountryModal(true)}>
              <Text style={[styles.selectText, !country && { color: colors.text.light }]}>
                {country ? `${country[3]}  ${country[0]}` : 'Selecciona el país'}
              </Text>
              <Icon name="chevron-down" size={18} color={colors.text.secondary} />
            </TouchableOpacity>
          </View>
          <View style={styles.field}>
            <Text style={styles.label}>Estado / Provincia</Text>
            {subdivisions.length > 0 ? (
              <TouchableOpacity style={styles.selectInput} onPress={() => setStateModal(true)}>
                <Text style={[styles.selectText, !state && { color: colors.text.light }]}>
                  {state || 'Selecciona el estado o provincia'}
                </Text>
                <Icon name="chevron-down" size={18} color={colors.text.secondary} />
              </TouchableOpacity>
            ) : (
              <TextInput
                style={styles.input}
                placeholder="Ej. Distrito Capital"
                placeholderTextColor={colors.text.light}
                value={state}
                onChangeText={setState}
              />
            )}
          </View>
          <View style={styles.field}>
            <Text style={styles.label}>Ciudad</Text>
            <TextInput
              style={styles.input}
              placeholder="Ej. Caracas"
              placeholderTextColor={colors.text.light}
              value={city}
              onChangeText={setCity}
            />
            <SuggestionChips options={cityOptions} current={city} onPick={setCity} />
          </View>
          <View style={styles.field}>
            <Text style={styles.label}>Barrio / Zona</Text>
            <TextInput
              style={styles.input}
              placeholder="Ej. Chacao"
              placeholderTextColor={colors.text.light}
              value={barrio}
              onChangeText={setBarrio}
            />
            <SuggestionChips options={barrioOptions} current={barrio} onPick={setBarrio} />
          </View>

          {/* WhatsApp */}
          <Text style={styles.sectionTitle}>Contacto</Text>
          <View style={styles.field}>
            <Text style={styles.label}>WhatsApp</Text>
            <View style={styles.phoneRow}>
              <TouchableOpacity style={styles.phoneCode} onPress={() => setCountryModal(true)}>
                <Text style={styles.phoneCodeText}>{country ? country[1] : '+__'}</Text>
                <Icon name="chevron-down" size={14} color={colors.text.secondary} />
              </TouchableOpacity>
              <TextInput
                style={[styles.input, { flex: 1 }]}
                placeholder="Número de WhatsApp"
                placeholderTextColor={colors.text.light}
                keyboardType="phone-pad"
                value={whatsapp}
                onChangeText={setWhatsapp}
              />
            </View>
          </View>

          {/* Services */}
          <Text style={styles.sectionTitle}>¿Qué ofreces?</Text>
          {FINANCIERA_SERVICES.map((service) => {
            const active = services.includes(service.id);
            const isMandatory = !!service.mandatory;
            return (
              <TouchableOpacity
                key={service.id}
                style={[
                  styles.serviceItem,
                  isMandatory && styles.serviceItemMandatory,
                  active && styles.serviceItemActive,
                  isMandatory && !active && styles.serviceItemRequiredEmpty,
                ]}
                onPress={() => toggleService(service.id)}
                activeOpacity={0.8}
              >
                <View style={[styles.checkbox, active && styles.checkboxActive]}>
                  {active && <Icon name="check" size={14} color="#fff" />}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.serviceLabel}>{service.label}</Text>
                  {isMandatory && (
                    <Text style={styles.serviceHint}>
                      Por ahora todas las financieras deben aceptar USDC por Algorand.
                    </Text>
                  )}
                </View>
                {isMandatory && (
                  <View style={styles.requiredTag}>
                    <Text style={styles.requiredTagText}>Obligatorio</Text>
                  </View>
                )}
              </TouchableOpacity>
            );
          })}

          {!supportsUsdcAlgorand && (
            <View style={styles.warning}>
              <Icon name="alert-circle" size={14} color={colors.warning.icon} />
              <Text style={styles.warningText}>
                Para registrarte debes aceptar USDC por la red Algorand.
              </Text>
            </View>
          )}

          <View style={styles.infoNote}>
            <Icon name="info" size={14} color={colors.accent} />
            <Text style={styles.infoNoteText}>
              No registres una tasa de cambio. La tasa se calcula automáticamente con las reseñas
              reales de los usuarios.
            </Text>
          </View>
        </ScrollView>

        <SafeAreaView edges={['bottom']} style={styles.footer}>
          <TouchableOpacity
            style={[styles.submitBtn, !canSubmit && styles.submitBtnDisabled]}
            disabled={!canSubmit}
            onPress={() => navigation.goBack()}
          >
            <Text style={styles.submitText}>Registrar financiera</Text>
          </TouchableOpacity>
        </SafeAreaView>
      </KeyboardAvoidingView>

      <CountryPickerModal
        visible={countryModal}
        onClose={() => setCountryModal(false)}
        onSelect={(c) => {
          if (String(c[2]) !== countryIso) {
            // Location levels belong to the old country
            setState('');
            setCity('');
            setBarrio('');
          }
          setCountry(c);
          setCountryModal(false);
        }}
      />
      <StatePickerModal
        visible={stateModal}
        options={subdivisions}
        onClose={() => setStateModal(false)}
        onSelect={(value) => {
          if (value !== state) {
            setCity('');
            setBarrio('');
          }
          setState(value);
          setStateModal(false);
        }}
      />
    </View>
  );
};

const Header = ({ title, onBack }: { title: string; onBack: () => void }) => (
  <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
    <View style={styles.header}>
      <TouchableOpacity onPress={onBack} style={styles.headerIconBtn}>
        <Icon name="arrow-left" size={24} color="#fff" />
      </TouchableOpacity>
      <Text style={styles.headerTitle}>{title}</Text>
      <View style={styles.headerIconBtn} />
    </View>
  </SafeAreaView>
);

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  scrollContent: { padding: 16, paddingBottom: 24 },

  verifiedNote: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.primarySoft,
    borderRadius: 12,
    padding: 12,
    marginBottom: 16,
  },
  verifiedNoteText: { flex: 1, fontSize: 12, color: colors.text.secondary, lineHeight: 17 },

  sectionTitle: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginTop: 8, marginBottom: 8 },
  field: { marginBottom: 14 },
  row: { flexDirection: 'row', gap: 12 },
  label: { fontSize: 13, fontWeight: '600', color: colors.text.primary, marginBottom: 6 },
  input: {
    height: 48,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    fontSize: 15,
    color: colors.text.primary,
    backgroundColor: '#fff',
  },
  selectInput: {
    height: 48,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
  },
  selectText: { fontSize: 15, color: colors.text.primary },

  phoneRow: { flexDirection: 'row', gap: 10 },
  phoneCode: {
    height: 48,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#fff',
  },
  phoneCodeText: { fontSize: 15, fontWeight: '600', color: colors.text.primary },

  suggestionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
  suggestionChip: {
    backgroundColor: colors.primarySoft,
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  suggestionChipText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },

  // Service checklist
  serviceItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  serviceItemActive: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  serviceItemMandatory: { borderColor: colors.primaryMuted },
  serviceItemRequiredEmpty: { borderColor: colors.warning.border, backgroundColor: colors.warning.background },
  checkbox: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.borderMedium,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  serviceLabel: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  serviceHint: { fontSize: 12, color: colors.text.secondary, marginTop: 2, lineHeight: 16 },
  requiredTag: {
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  requiredTagText: { fontSize: 10, fontWeight: '700', color: colors.primaryDark },

  warning: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.warning.background,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  warningText: { flex: 1, fontSize: 12, color: colors.warning.text, lineHeight: 17 },

  infoNote: {
    flexDirection: 'row',
    gap: 8,
    backgroundColor: colors.infoLight,
    borderRadius: 12,
    padding: 12,
  },
  infoNoteText: { flex: 1, fontSize: 12, color: colors.text.secondary, lineHeight: 17 },

  footer: {
    backgroundColor: '#fff',
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  submitBtn: {
    height: 52,
    borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitBtnDisabled: { backgroundColor: colors.borderMedium },
  submitText: { fontSize: 16, fontWeight: '700', color: '#fff' },

  // Modal
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingBottom: 28,
    paddingTop: 8,
  },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: 'center', marginBottom: 8 },
  modalHeaderRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  modalIconBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  modalTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceMuted,
    borderRadius: 12,
    paddingHorizontal: 12,
    height: 44,
    gap: 8,
    marginBottom: 8,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, paddingVertical: 0 },
  optionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  optionLabel: { fontSize: 15, color: colors.text.primary },
  optionCode: { fontSize: 14, color: colors.text.light },

  // Verification gate
  gate: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  gateIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  gateTitle: { fontSize: 20, fontWeight: '800', color: colors.text.primary, marginBottom: 10 },
  gateText: { fontSize: 14, color: colors.text.secondary, textAlign: 'center', lineHeight: 20, marginBottom: 24 },
  gatePrimary: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    height: 52,
    paddingHorizontal: 32,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'stretch',
  },
  gatePrimaryText: { fontSize: 16, fontWeight: '700', color: '#fff' },
  gateSecondary: { fontSize: 15, color: colors.text.secondary, marginTop: 16, fontWeight: '600' },
});

export default RegisterFinancieraScreen;
