// The icon chip shared by the notification list and the transaction ledger:
// a colored glyph on a soft tint of the same color, with an optional corner
// badge for state.
//
// Both lists used to build this inline, with the tint faked as `${color}20`.
// That alpha hack muddies against the tinted unread rows, so tints are now
// explicit tokens picked in `vocabulary.ts`.

import React from 'react';
import { View, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Path } from 'react-native-svg';

import { colors } from '../../config/theme';
import { BADGE_GLYPHS, BADGE_RINGED, BadgeName, CUSTOM_GLYPHS } from './glyphs';

export type IconVisual = {
  // A key of CUSTOM_GLYPHS, else a Feather icon name.
  glyph: string;
  color: string;
  bg: string;
  badge?: BadgeName;
};

const Strokes = ({ paths, color, size, width }: { paths: readonly string[]; color: string; size: number; width: number }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    {paths.map(d => (
      <Path key={d} d={d} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />
    ))}
  </Svg>
);

// One glyph, custom or Feather, for surfaces that have their own container —
// the transaction detail header draws a 72px tile of its own, and still has to
// speak the same vocabulary.
export const Glyph = ({ name, color, size = 20 }: { name: string; color: string; size?: number }) => {
  const custom = CUSTOM_GLYPHS[name];
  // The viewBox scales the stroke with the glyph, the way a Feather font
  // glyph scales, so one weight holds at every size.
  return custom ? (
    <Strokes paths={custom} color={color} size={size} width={1.9} />
  ) : (
    <Icon name={name as any} size={size} color={color} />
  );
};

export const IconChip = ({
  visual,
  // A badge needs a ring to stay readable over the glyph, and unread rows are
  // tinted, so the ring has to be the row's own background, not always white.
  ringColor = colors.background,
  // Notifications use a circle, the ledger a squircle. Both surfaces already
  // did, and the shape is how you tell at a glance which list you are in.
  radius = 20,
  style,
}: {
  visual: IconVisual;
  ringColor?: string;
  radius?: number;
  style?: any;
}) => {
  return (
    <View style={[styles.chip, { backgroundColor: visual.bg, borderRadius: radius }, style]}>
      <Glyph name={visual.glyph} color={visual.color} />
      {visual.badge ? (
        <View style={[styles.badge, { backgroundColor: visual.color, borderColor: ringColor }]}>
          <Strokes
            paths={
              BADGE_RINGED.includes(visual.badge)
                ? ['M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18Z', ...BADGE_GLYPHS[visual.badge]]
                : BADGE_GLYPHS[visual.badge]
            }
            color={colors.white}
            size={10}
            width={2.8}
          />
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  chip: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
  badge: {
    // Pinned to the 40x40 corner rather than hung outside it: Android clips
    // children that overflow their parent, and the circle leaves the corner
    // free anyway, so the badge still reads as overlapping the chip.
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: 17,
    height: 17,
    borderRadius: 9,
    borderWidth: 2,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
