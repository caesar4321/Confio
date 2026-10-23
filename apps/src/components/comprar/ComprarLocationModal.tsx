import React, { useEffect, useMemo, useState } from 'react';
import { FlatList, Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { Text, TextInput } from '../common/AppText';
import { FlagLabel } from '../CountryFlag';
import { colors } from '../../config/theme';
import { filterCountries, getCountryByIso } from '../../utils/countries';
import { GET_MARKETPLACE_CITIES } from '../../services/comprar';

type Props = {
  visible: boolean;
  countryCode: string;
  city: string;
  /** Where the user is (GPS city, else phone country): always listed first. */
  homeCountryCode?: string;
  homeCity?: string;
  onClose: () => void;
  onSelect: (countryCode: string, city: string) => void;
  onUseGps: () => void;
};

/**
 * Country → city picker, ordered like Financieras: the user's own country
 * (and city) first, then places that already have stores with listings
 * (most first), then the rest alphabetically.
 */
export const ComprarLocationModal = ({
  visible, countryCode, city, homeCountryCode, homeCity, onClose, onSelect, onUseGps,
}: Props) => {
  const [step, setStep] = useState<'country' | 'city'>('city');
  const [pickedCountry, setPickedCountry] = useState(countryCode);
  const [q, setQ] = useState('');
  // Each opening starts on the country being browsed now.
  useEffect(() => {
    if (visible) {
      setPickedCountry(countryCode);
      setStep('city');
    }
  }, [visible, countryCode]);
  const { data, loading } = useQuery(GET_MARKETPLACE_CITIES, {
    variables: { countryCode: pickedCountry },
    skip: !visible || !pickedCountry,
    fetchPolicy: 'cache-and-network',
  });
  const storeCounts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of data?.marketplaceCountries || []) out[c.countryCode] = c.storeCount;
    return out;
  }, [data]);
  const countries = useMemo(() => {
    const rank = (iso: string) => (iso === homeCountryCode ? 0 : storeCounts[iso] ? 1 : 2);
    // Stable sort keeps alphabetical order inside each group.
    return [...filterCountries(q)].sort((a, b) => {
      const ra = rank(String(a[2]));
      const rb = rank(String(b[2]));
      if (ra !== rb) return ra - rb;
      return (storeCounts[String(b[2])] || 0) - (storeCounts[String(a[2])] || 0);
    });
  }, [q, storeCounts, homeCountryCode]);
  const cities = useMemo(() => {
    const isHome = (c: any) => c.countryCode === homeCountryCode && c.city === homeCity;
    return [...(data?.marketplaceCities || [])].sort((a: any, b: any) => {
      if (isHome(a) !== isHome(b)) return isHome(a) ? -1 : 1;
      if ((b.storeCount || 0) !== (a.storeCount || 0)) return (b.storeCount || 0) - (a.storeCount || 0);
      if (a.isLive !== b.isLive) return a.isLive ? -1 : 1;
      return String(a.city).localeCompare(String(b.city), 'es');
    });
  }, [data, homeCountryCode, homeCity]);

  const close = () => {
    setStep('city');
    setQ('');
    onClose();
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            {step === 'city' ? (
              <TouchableOpacity onPress={() => setStep('country')} style={styles.countryButton}
                accessibilityRole="button" accessibilityLabel="Cambiar país">
                <FlagLabel iso={pickedCountry} textStyle={styles.title}>
                  {getCountryByIso(pickedCountry)?.[0] || pickedCountry}
                </FlagLabel>
                <Icon name="chevron-down" size={18} color={colors.text.primary} />
              </TouchableOpacity>
            ) : (
              <Text style={styles.title}>País</Text>
            )}
            <TouchableOpacity onPress={close} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.text.primary} />
            </TouchableOpacity>
          </View>

          {step === 'country' ? (
            <>
              <View style={styles.searchBox}>
                <Icon name="search" size={18} color={colors.text.light} />
                <TextInput style={styles.searchInput} placeholder="Buscar país"
                  placeholderTextColor={colors.text.light} value={q} onChangeText={setQ} />
              </View>
              <FlatList
                data={countries}
                keyExtractor={(item) => String(item[2])}
                style={{ maxHeight: 420 }}
                initialNumToRender={20}
                maxToRenderPerBatch={15}
                windowSize={21}
                keyboardShouldPersistTaps="handled"
                renderItem={({ item }) => (
                  <TouchableOpacity style={styles.row} onPress={() => {
                    setPickedCountry(String(item[2]));
                    setStep('city');
                    setQ('');
                  }}>
                    <FlagLabel iso={item[2]} textStyle={styles.rowText}>{item[0]}</FlagLabel>
                    {String(item[2]) === homeCountryCode ? (
                      <Text style={styles.rowMeta}>Tu país</Text>
                    ) : storeCounts[String(item[2])] ? (
                      <Text style={styles.rowMeta}>{storeCounts[String(item[2])]} tiendas</Text>
                    ) : null}
                  </TouchableOpacity>
                )}
              />
            </>
          ) : (
            <>
              <TouchableOpacity style={styles.gpsRow} onPress={() => { onUseGps(); close(); }}>
                <Icon name="navigation" size={16} color={colors.primaryDark} />
                <Text style={styles.gpsText}>Usar mi ubicación</Text>
              </TouchableOpacity>
              <FlatList
                data={cities}
                keyExtractor={(item: any) => `${item.countryCode}-${item.city}`}
                style={{ maxHeight: 420 }}
                initialNumToRender={20}
                maxToRenderPerBatch={15}
                windowSize={21}
                ListEmptyComponent={
                  <Text style={styles.empty}>
                    {loading ? 'Cargando…' : 'Aún no hay ciudades en Comprar para este país.'}
                  </Text>
                }
                renderItem={({ item }: any) => {
                  const selected = item.city === city && item.countryCode === countryCode;
                  return (
                    <TouchableOpacity style={styles.row} onPress={() => { onSelect(item.countryCode, item.city); close(); }}>
                      <Text style={[styles.rowText, selected && styles.rowSelected]}>
                        {item.city}{item.city === homeCity && item.countryCode === homeCountryCode ? ' · Tu ciudad' : ''}
                      </Text>
                      <Text style={styles.rowMeta}>
                        {item.isLive ? `${item.storeCount} tiendas` : 'Próximamente'}
                      </Text>
                    </TouchableOpacity>
                  );
                }}
              />
            </>
          )}
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 32 },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: '#E5E7EB', marginBottom: 12 },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  countryButton: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  title: { fontSize: 18, fontWeight: '700', color: colors.text.primary },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.neutralDark, borderRadius: 12, paddingHorizontal: 12, marginBottom: 8 },
  searchInput: { flex: 1, paddingVertical: 10, fontSize: 15, color: colors.text.primary },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: colors.neutralDark },
  rowText: { fontSize: 16, color: colors.text.primary },
  rowSelected: { fontWeight: '700', color: colors.primaryDark },
  rowMeta: { fontSize: 13, color: colors.text.secondary },
  gpsRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 12 },
  gpsText: { fontSize: 15, fontWeight: '600', color: colors.primaryDark },
  empty: { textAlign: 'center', color: colors.text.secondary, paddingVertical: 24 },
});
