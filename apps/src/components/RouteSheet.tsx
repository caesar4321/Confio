// RouteSheet — the app's money-routing bottom sheet.
//
// Purpose determines the settlement rail, so every option names its real cost
// or consequence in the subtitle — users pick the cheap/right path knowingly.
// Used by: HomeScreen Recargar/Retirar (world picker: spend vs grow) and the
// Ahorros hub (source/destination pickers). Keep options to 2-3: two clear
// doors teach the product split; four doors teach confusion.

import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, Image, ImageSourcePropType } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

export interface RouteOption {
  /** Feather icon name; ignored when `image` is provided. */
  icon: string;
  /** Token/brand logo — takes the icon slot when provided. */
  image?: ImageSourcePropType;
  title: string;
  subtitle: string;
  onPress: () => void;
  disabled?: boolean;
}

export const RouteSheet = ({
  visible,
  title,
  options,
  onClose,
}: {
  visible: boolean;
  title: string;
  options: RouteOption[];
  onClose: () => void;
}) => (
  <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
    <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose}>
      <TouchableOpacity activeOpacity={1} style={styles.sheet}>
        <View style={styles.handle} />
        <Text style={styles.title}>{title}</Text>
        {options.map((o) => (
          <TouchableOpacity
            key={o.title}
            style={[styles.option, o.disabled && { opacity: 0.45 }]}
            disabled={o.disabled}
            onPress={() => {
              onClose();
              o.onPress();
            }}
            activeOpacity={0.8}
          >
            {o.image ? (
              <Image source={o.image} style={styles.optionImage} />
            ) : (
              <View style={styles.optionIcon}>
                <Icon name={o.icon} size={20} color={colors.primaryDark} />
              </View>
            )}
            <View style={{ flex: 1 }}>
              <Text style={styles.optionTitle}>{o.title}</Text>
              <Text style={styles.optionSubtitle}>{o.subtitle}</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>
        ))}
      </TouchableOpacity>
    </TouchableOpacity>
  </Modal>
);

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 32,
  },
  handle: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.surfaceMuted,
    marginBottom: 14,
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 12,
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceMuted,
  },
  optionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  optionImage: { width: 40, height: 40, borderRadius: 20 },
  optionTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  optionSubtitle: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
});
