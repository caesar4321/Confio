// RouteSheet — the app's money-routing bottom sheet.
//
// Purpose determines the settlement rail, so every option names its real cost
// or consequence in the subtitle — users pick the cheap/right path knowingly.
// Used by: HomeScreen Recargar/Retirar (world picker: spend vs grow), the
// Ahorros hub (source/destination pickers), and TransferScreen (rail lists).
//
// Two shapes share this component and they have different limits:
//   - a WORLD PICKER is 2-3 options; two clear doors teach the product split,
//     four doors teach confusion.
//   - a RAIL LIST (which country, which network) is inherently longer, and
//     grows every time a corridor opens. That is why the sheet scrolls and is
//     height-capped rather than assuming the content fits — an eight-row list
//     ran off the top of a small phone and past the home indicator at the
//     bottom before this was capped.

import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, Image, ScrollView, ImageSourcePropType } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { useAppSafeArea } from '../hooks/useAppSafeArea';

export interface RouteOption {
  /** Feather icon name; ignored when `image` is provided. */
  icon: string;
  /** Token/brand logo — takes the icon slot when provided. */
  image?: ImageSourcePropType;
  title: string;
  subtitle: string;
  /**
   * Status line rendered BELOW the subtitle, in its own colour. For things
   * true of the option's AVAILABILITY rather than of the rail itself — see
   * `COMING_SOON_NOTE`. Keep it out of `subtitle`: appended there it produced
   * one long wrapping line where the rail description and its availability
   * were indistinguishable, which is precisely the row an app reviewer reads
   * as a broken button rather than a published roadmap entry.
   */
  note?: string;
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
}) => {
  const { bottom } = useAppSafeArea();

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose}>
        <TouchableOpacity activeOpacity={1} style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>{title}</Text>
          <ScrollView
            style={styles.optionScroll}
            // Keep breathing room even on devices that report a zero inset;
            // otherwise the last rail sits flush against the sheet edge.
            contentContainerStyle={{ paddingBottom: Math.max(bottom, 24) }}
            showsVerticalScrollIndicator={true}
            // A capped sheet that happens to be short must still hug its
            // content, otherwise every two-option world picker would render
            // as a half-screen slab of empty white.
            bounces={false}
          >
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
                  {o.note ? <Text style={styles.optionNote}>{o.note}</Text> : null}
                </View>
                <Icon name="chevron-right" size={18} color={colors.text.light} />
              </TouchableOpacity>
            ))}
          </ScrollView>
        </TouchableOpacity>
      </TouchableOpacity>
    </Modal>
  );
};

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
    // Never taller than most of the screen: the backdrop above it is the only
    // affordance telling the user this is dismissable, so it has to stay
    // visible even when the rail list is long.
    maxHeight: '85%',
  },
  optionScroll: {
    flexGrow: 0,
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
  optionNote: { fontSize: 12, color: colors.text.light, marginTop: 3 },
});
