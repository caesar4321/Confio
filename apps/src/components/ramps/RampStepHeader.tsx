import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

type Props = {
  number: number;
  title: string;
  meta?: string | null;
  accentColor?: string;
  accentBackground?: string;
  titleColor?: string;
  metaColor?: string;
};

export const RampStepHeader = ({
  number,
  title,
  meta,
  accentColor = '#047857',
  accentBackground = '#d1fae5',
  titleColor = '#1f2937',
  metaColor = '#6b7280',
}: Props) => {
  return (
    <View style={styles.header}>
      <View style={styles.left}>
        <View style={[styles.badge, { backgroundColor: accentBackground }]}>
          <Text style={[styles.badgeText, { color: accentColor }]}>{number}</Text>
        </View>
        <Text style={[styles.title, { color: titleColor }]}>{title}</Text>
      </View>
      {meta ? <Text style={[styles.meta, { color: metaColor }]}>{meta}</Text> : null}
    </View>
  );
};

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  left: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    flexShrink: 1,
  },
  badge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: {
    fontSize: 13,
    fontWeight: '800',
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
  },
  meta: {
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 12,
    flexShrink: 1,
    textAlign: 'right',
  },
});
