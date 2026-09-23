import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { colors } from '../config/theme';
import { RouteOption, RouteOptionRow, RouteSheet } from './RouteSheet';

/**
 * One section of the Enviar and Recibir screens: a white card, an uppercase
 * label, RouteOptionRows. Both screens are built from these so the two verbs
 * read as mirror images — same card, same row, same order of ideas.
 */
export const RouteCard = ({ label, children }: { label?: string; children: React.ReactNode }) => (
  <View style={styles.card}>
    {label ? <Text style={styles.label}>{label}</Text> : null}
    {children}
  </View>
);

/**
 * The bank-and-wallet section, identical in both directions: rails usable now
 * inline, everything else (nationality-blocked, not-yet-open corridors) behind
 * "Más países". `leading`/`trailing` are the direction's own rows (Recargar
 * ahora / A mi propia cuenta).
 */
export const LocalRailsCard = ({
  label,
  primary,
  more,
  moreTitle,
  leading = [],
  trailing = [],
}: {
  label: string;
  primary: RouteOption[];
  more: RouteOption[];
  moreTitle: string;
  leading?: RouteOption[];
  trailing?: RouteOption[];
}) => {
  const [showMore, setShowMore] = useState(false);
  const rows = [...leading, ...primary, ...trailing];
  return (
    <RouteCard label={label}>
      {rows.map((option, index) => (
        <RouteOptionRow key={option.id ?? option.title} option={option} first={index === 0} />
      ))}
      {more.length > 0 && (
        <TouchableOpacity
          style={[styles.moreRow, rows.length === 0 && styles.moreRowFirst]}
          onPress={() => setShowMore(true)}
          accessibilityRole="button"
          accessibilityLabel={rows.length === 0 ? 'Ver países' : 'Más países'}
        >
          <Icon name="globe" size={16} color={colors.primaryDark} />
          <Text style={styles.moreText}>{rows.length === 0 ? 'Ver países' : 'Más países'}</Text>
          <Icon name="chevron-right" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
      )}
      <RouteSheet visible={showMore} title={moreTitle} options={more} onClose={() => setShowMore(false)} />
    </RouteCard>
  );
};

/** Collapsed "Avanzado" card (crypto addresses) — same in both directions. */
export const AdvancedCard = ({ subtitle, options }: { subtitle: string; options: RouteOption[] }) => {
  const [open, setOpen] = useState(false);
  return (
    <RouteCard>
      <TouchableOpacity
        style={styles.advancedToggle}
        onPress={() => setOpen(v => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`Avanzado: ${subtitle}`}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.advancedTitle}>Avanzado</Text>
          <Text style={styles.advancedSub}>{subtitle}</Text>
        </View>
        <Icon name={open ? 'chevron-up' : 'chevron-down'} size={20} color={colors.text.light} />
      </TouchableOpacity>
      {open ? options.map(option => <RouteOptionRow key={option.id ?? option.title} option={option} />) : null}
    </RouteCard>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: colors.border,
  },
  label: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.6,
    color: colors.text.secondary,
    marginBottom: 6,
  },
  moreRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingTop: 12,
    marginTop: 2,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceMuted,
  },
  moreRowFirst: {
    borderTopWidth: 0,
    marginTop: 0,
    paddingTop: 4,
  },
  moreText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  advancedToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
  },
  advancedTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text.secondary,
  },
  advancedSub: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 2,
  },
});
