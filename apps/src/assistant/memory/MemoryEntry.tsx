import React, { useState } from 'react';
import { Pressable, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { useAccount } from '../../contexts/AccountContext';
import { ASSISTANT_MEMORY_ENABLED } from './flag';
import MemorySheet from './MemorySheet';

function Entry() {
  const { activeAccount } = useAccount();
  // Keyed by account: switching closes one memory before another is read.
  const [openFor, setOpenFor] = useState<string | null>(null);
  if (!activeAccount?.id || !['personal', 'business'].includes(activeAccount.type)) {
    return null;
  }
  const accountKey = String(activeAccount.id);
  return (
    <>
      <Pressable style={styles.row} onPress={() => setOpenFor(accountKey)} accessibilityRole="button">
        <Icon name="bookmark" size={18} color={colors.successText} />
        <Text style={styles.label}>Memoria</Text>
        <Icon name="chevron-right" size={18} color={colors.textSecondary} />
      </Pressable>
      {openFor === accountKey ? <MemorySheet key={accountKey} onClose={() => setOpenFor(null)} /> : null}
    </>
  );
}

// With the flag off this reads no context and asks the server nothing.
export default function MemoryEntry() {
  return ASSISTANT_MEMORY_ENABLED ? <Entry /> : null;
}

const styles = StyleSheet.create({
  row: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  label: { flex: 1, fontSize: 15, color: colors.textFlat },
});
