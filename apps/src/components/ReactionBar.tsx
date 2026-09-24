import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

export const REACTION_OPTIONS = ['🔥', '🙌', '😍', '🤯', '💡', '😎', '💪', '👀', '😢', '❤️'] as const;

type Props = {
  reactions?: Array<{ emoji: string; count: number }>;
  viewerReaction?: string | null;
  canReact?: boolean;
  onReact: (emoji: string) => void;
  /** How many existing reactions to show before the add button. */
  limit?: number;
};

/** Reactions under a post, the same on Descubrir, Mensajes and the detail screen. */
export function ReactionBar({ reactions = [], viewerReaction, canReact = true, onReact, limit = 3 }: Props) {
  const [pickerOpen, setPickerOpen] = React.useState(false);
  // The viewer's own reaction always stays visible: if it ranks below the
  // cut, it takes the last slot so the bar still shows what they picked.
  const top = reactions.slice(0, limit);
  const own = viewerReaction ? reactions.find((reaction) => reaction.emoji === viewerReaction) : undefined;
  const shown = own && !top.includes(own) ? [...top.slice(0, Math.max(limit - 1, 0)), own] : top;
  if (!shown.length && !canReact) return null;

  return (
    <View>
      <View style={styles.row}>
        {shown.map(({ emoji, count }) => {
          const active = viewerReaction === emoji;
          return (
            <Pressable
              key={emoji}
              onPress={() => onReact(emoji)}
              disabled={!canReact}
              style={[styles.chip, active && styles.chipActive]}
              accessibilityRole="button"
              accessibilityLabel={`Reaccionar con ${emoji}, ${count} ${count === 1 ? 'reacción' : 'reacciones'}`}
              accessibilityState={{ selected: active }}
            >
              <Text style={styles.emoji}>{emoji}</Text>
              <Text style={[styles.count, active && styles.countActive]}>{count}</Text>
            </Pressable>
          );
        })}
        {canReact && (
          <Pressable
            onPress={() => setPickerOpen((open) => !open)}
            style={[styles.addButton, pickerOpen && styles.addButtonOpen]}
            hitSlop={6}
            accessibilityRole="button"
            accessibilityLabel="Agregar una reacción"
            accessibilityState={{ expanded: pickerOpen }}
          >
            <Icon name="smile" size={15} color={pickerOpen ? colors.primaryDeep : colors.text.secondary} />
            <Icon name="plus" size={11} color={pickerOpen ? colors.primaryDeep : colors.text.secondary} />
          </Pressable>
        )}
      </View>

      {pickerOpen && canReact && (
        <View style={styles.picker}>
          {REACTION_OPTIONS.map((emoji) => {
            const active = viewerReaction === emoji;
            return (
              <Pressable
                key={emoji}
                onPress={() => {
                  setPickerOpen(false);
                  onReact(emoji);
                }}
                style={[styles.option, active && styles.optionActive]}
                accessibilityRole="button"
                accessibilityLabel={`Reaccionar con ${emoji}`}
                accessibilityState={{ selected: active }}
              >
                <Text style={styles.optionEmoji}>{emoji}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 6,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: colors.neutralDark,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  chipActive: {
    backgroundColor: colors.primarySoft,
    borderColor: colors.primaryMuted,
  },
  emoji: {
    fontSize: 13,
  },
  count: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  countActive: {
    color: colors.primaryDeep,
  },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 1,
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: colors.border,
  },
  addButtonOpen: {
    borderColor: colors.primaryMuted,
    backgroundColor: colors.primarySoft,
  },
  picker: {
    marginTop: 8,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    padding: 8,
  },
  option: {
    width: 36,
    height: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  optionActive: {
    backgroundColor: colors.primarySoft,
  },
  optionEmoji: {
    fontSize: 18,
  },
});
