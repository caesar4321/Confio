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
import { View, Text, StyleSheet, TouchableOpacity, Modal, Image, ScrollView, useWindowDimensions, ImageSourcePropType } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { useAppSafeArea } from '../hooks/useAppSafeArea';

export interface RouteOption {
  /**
   * Stable key. REQUIRED whenever titles can repeat — six rails are called
   * "Cuenta bancaria", and duplicate React keys silently reuse the wrong row's
   * state. Titles used to be unique only because each carried a flag emoji.
   */
  id?: string;
  /**
   * Country flag, rendered in its OWN fixed-width cell before the title.
   *
   * It used to be concatenated (`${flag}  ${title}`), which broke alignment on
   * Android: emoji come from the system emoji font while the text comes from
   * Roboto, the two runs are measured separately, and flag glyphs do not all
   * advance the same width. Titles therefore started at a different x on every
   * row — most visible on the shortest one, "Pix", which looked indented. A
   * fixed-width cell makes every title share one left edge on both platforms.
   */
  flag?: string;
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
  const { height } = useWindowDimensions();
  // Bound the LIST in real pixels rather than leaning on the sheet's
  // percentage maxHeight to constrain it.
  //
  // The percentage cap alone did not work: `maxHeight: '85%'` limits how tall
  // the sheet may DRAW, but the ScrollView inside still measured itself at its
  // full content height, so it had nothing to scroll within — it simply got
  // painted past the sheet's edge and the overflow disappeared. Adding
  // flexShrink was not enough either, because a flex child only shrinks when
  // the container's own height is already resolved, and here it is resolved
  // from that same content.
  //
  // An explicit pixel maxHeight makes the ScrollView's viewport smaller than
  // its content unconditionally, which is the only state in which it scrolls.
  // 0.62 leaves room for the handle, the title, the safe-area inset and enough
  // backdrop above the sheet to still read as dismissable.
  const listMaxHeight = Math.round(height * 0.62);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose}>
        <View style={styles.sheet} onStartShouldSetResponder={() => true}>
          <View style={styles.handle} />
          <Text style={styles.title}>{title}</Text>
          <ScrollView
            style={[styles.optionScroll, { maxHeight: listMaxHeight }]}
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
                key={o.id ?? o.title}
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
                  <View style={styles.optionTitleRow}>
                    {o.flag ? <Text style={styles.optionFlag}>{o.flag}</Text> : null}
                    <Text style={styles.optionTitle}>{o.title}</Text>
                  </View>
                  <Text style={styles.optionSubtitle}>{o.subtitle}</Text>
                  {o.note ? <Text style={styles.optionNote}>{o.note}</Text> : null}
                </View>
                <Icon name="chevron-right" size={18} color={colors.text.light} />
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
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
    // flexGrow 0 → a two-option world picker hugs its content instead of
    // rendering as a half-screen slab of white.
    // flexShrink 1 → and a twelve-rail list is allowed to shrink INSIDE the
    // sheet's maxHeight and scroll. This pair is not redundant: Yoga defaults
    // flexShrink to 0 (unlike web CSS, which defaults to 1), so with only
    // flexGrow set the ScrollView could neither grow nor shrink. It kept its
    // full content height, overflowed the capped sheet, and the last row was
    // clipped off the bottom with no way to scroll to it.
    flexGrow: 0,
    flexShrink: 1,
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
  optionTitleRow: { flexDirection: 'row', alignItems: 'center' },
  // Fixed width, centred glyph: the title's left edge is then independent of
  // how wide a given flag happens to render.
  optionFlag: { fontSize: 15, width: 22, marginRight: 8, textAlign: 'center' },
  optionTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary, flexShrink: 1 },
  optionSubtitle: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  optionNote: { fontSize: 12, color: colors.text.light, marginTop: 3 },
});
