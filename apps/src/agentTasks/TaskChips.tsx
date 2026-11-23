// "Abrir la tienda": the chip agent_tasks/notes.py puts on its chat notes
// ({type: 'task', target: <task id>}). It opens the task screen.
import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { taskIdOf } from './helpers';

const CHIP_LABEL = 'Abrir la tienda';

type Action = { type: string; target?: string | null; label?: string | null };

export function taskActions(actions: Action[]): { taskId: string; label: string }[] {
  const seen = new Set<string>();
  const found: { taskId: string; label: string }[] = [];
  for (const a of actions) {
    const taskId = a.type === 'task' ? taskIdOf(a.target) : null;
    if (taskId && !seen.has(taskId)) {
      seen.add(taskId);
      // Its own words, whatever an older note said ("Ver la tarea" is gone).
      found.push({ taskId, label: CHIP_LABEL });
    }
  }
  return found;
}

export function TaskChips({ actions, onOpen }: { actions: Action[]; onOpen: (taskId: string) => void }) {
  const tasks = taskActions(actions);
  if (!tasks.length) {
    return null;
  }
  return (
    <View style={styles.row}>
      {tasks.map((t) => (
        <Pressable key={t.taskId} onPress={() => onOpen(t.taskId)} style={styles.chip} accessibilityRole="button">
          <Text style={styles.text}>{t.label}</Text>
          <Icon name="chevron-right" size={14} color={colors.primaryDark} />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 44, paddingHorizontal: 14, borderRadius: 22,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.background,
  },
  text: { fontSize: 15, fontWeight: '600', color: colors.primaryDark },
});
