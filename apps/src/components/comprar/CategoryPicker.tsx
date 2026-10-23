import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text, TextInput } from '../common/AppText';
import { colors } from '../../config/theme';

export type MarketCategory = { key: string; label: string; group?: string | null; icon?: string | null };

type Props = {
  categories: MarketCategory[];
  selected: string[];
  onToggle: (key: string) => void;
  /** Single choice (product editor) vs several (fake-door probe). */
  multiple?: boolean;
  /** Multiple: the most that can be picked (further taps are ignored, with a note). */
  max?: number;
};

const normalize = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

/**
 * The (admin-managed, so ever-growing) category list, grouped under its
 * headings in server order, with a search box so a long list stays usable.
 */
export const CategoryPicker = ({ categories, selected, onToggle, multiple = false, max }: Props) => {
  const full = multiple && max !== undefined && selected.length >= max;
  const [q, setQ] = useState('');
  const groups = useMemo(() => {
    const needle = normalize(q.trim());
    const out: { group: string; items: MarketCategory[] }[] = [];
    for (const c of categories) {
      if (needle && !normalize(`${c.label} ${c.group || ''}`).includes(needle)) continue;
      const group = c.group || 'Otros';
      const bucket = out.find((g) => g.group === group) || out[out.push({ group, items: [] }) - 1];
      bucket.items.push(c);
    }
    return out;
  }, [categories, q]);

  return (
    <View style={styles.wrap}>
      {categories.length > 10 ? (
        <View style={styles.search}>
          <Icon name="search" size={15} color={colors.text.light} />
          <TextInput style={styles.searchInput} placeholder="Buscar categoría" placeholderTextColor={colors.text.light}
            value={q} onChangeText={setQ} returnKeyType="search" />
        </View>
      ) : null}
      {groups.map(({ group, items }) => (
        <View key={group} style={styles.group}>
          <Text style={styles.groupTitle}>{group}</Text>
          <View style={styles.chips}>
            {items.map((c) => {
              const on = selected.includes(c.key);
              return (
                <Pressable key={c.key} onPress={() => { if (on || !full) onToggle(c.key); }}
                  style={[styles.chip, on && styles.chipOn, !on && full && styles.chipDim]}
                  accessibilityRole={multiple ? 'checkbox' : 'radio'} accessibilityState={{ checked: on }}>
                  <Text style={[styles.chipText, on && styles.chipTextOn]}>{c.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ))}
      {full ? <Text style={styles.empty}>Puedes elegir hasta {max}.</Text> : null}
      {groups.length === 0 ? (
        <Text style={styles.empty}>Ninguna categoría coincide. Elige «Otros» y descríbelo en el texto.</Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.neutral, borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 12, paddingHorizontal: 12 },
  searchInput: { flex: 1, paddingVertical: 9, fontSize: 14, color: colors.text.primary },
  group: { gap: 6 },
  groupTitle: { fontSize: 12, fontWeight: '700', color: colors.text.secondary, textTransform: 'uppercase', letterSpacing: 0.4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB' },
  chipOn: { backgroundColor: colors.textFlat, borderColor: colors.textFlat },
  chipText: { fontSize: 13, color: colors.text.primary },
  chipTextOn: { color: colors.white, fontWeight: '600' },
  chipDim: { opacity: 0.45 },
  empty: { fontSize: 13, color: colors.text.secondary },
});
