import React, { useMemo, useState } from 'react';
import { FlatList, Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Text, TextInput } from '../common/AppText';
import { CountryFlag } from '../CountryFlag';
import { colors } from '../../config/theme';
import { Country, filterCountries } from '../../utils/countries';

const ROW_HEIGHT = 58;

/** Every country, searchable: where an address is, or a phone's calling code. */
export const RampCountryPicker = ({ visible, selected, title, showCallingCode = false, onPick, onClose }: {
  visible: boolean;
  selected?: string | null;
  title: string;
  showCallingCode?: boolean;
  onPick: (country: Country) => void;
  onClose: () => void;
}) => {
  const [search, setSearch] = useState('');
  const results = useMemo(() => filterCountries(search), [search]);
  const close = () => { setSearch(''); onClose(); };
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={close}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.header}>
          <TouchableOpacity onPress={close} accessibilityRole="button" accessibilityLabel="Cancelar">
            <Text style={styles.cancel}>Cancelar</Text>
          </TouchableOpacity>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          <View style={styles.spacer} />
        </View>
        <View style={styles.search}>
          <Icon name="search" size={16} color={colors.textSecondary} />
          <TextInput
            style={styles.searchInput}
            value={search}
            onChangeText={setSearch}
            placeholder="Buscar país"
            placeholderTextColor={colors.textSecondary}
            autoCapitalize="none"
            autoCorrect={false}
          />
        </View>
        <FlatList
          data={results}
          keyExtractor={item => String(item[2])}
          keyboardShouldPersistTaps="handled"
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          getItemLayout={(_, index) => ({ length: ROW_HEIGHT, offset: ROW_HEIGHT * index, index })}
          renderItem={({ item }) => {
            const isSelected = item[2] === selected;
            return (
              <TouchableOpacity
                style={styles.row}
                onPress={() => { onPick(item); close(); }}
                accessibilityRole="button"
                accessibilityLabel={String(item[0])}
                accessibilityState={{ selected: isSelected }}
              >
                <CountryFlag iso={String(item[2])} size={26} />
                <Text style={styles.name} numberOfLines={1}>{item[0]}</Text>
                {showCallingCode ? <Text style={styles.code}>{item[1]}</Text> : null}
                {isSelected ? <Icon name="check" size={18} color={colors.primary} /> : null}
              </TouchableOpacity>
            );
          }}
          ListEmptyComponent={<Text style={styles.empty}>No encontramos ese país.</Text>}
        />
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 16 },
  cancel: { fontSize: 15, color: colors.successText, fontWeight: '600', width: 70 },
  title: { flex: 1, textAlign: 'center', fontSize: 16, fontWeight: '700', color: colors.dark },
  spacer: { width: 70 },
  search: {
    flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 14,
    height: 46, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.dark, padding: 0 },
  row: {
    height: ROW_HEIGHT, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  name: { flex: 1, fontSize: 15, color: colors.dark },
  code: { fontSize: 14, color: colors.textSecondary, fontWeight: '600' },
  empty: { textAlign: 'center', padding: 32, color: colors.textSecondary },
});
