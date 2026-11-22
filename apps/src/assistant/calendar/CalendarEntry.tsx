import React, { useState } from 'react';
import { Pressable, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { useAccount } from '../../contexts/AccountContext';
import { useAuth } from '../../contexts/AuthContext';
import CalendarConnectSheet from './CalendarConnectSheet';
import { calendarSupported } from './deviceCalendar';
import { ASSISTANT_CALENDAR_ENABLED } from './flag';

function Entry() {
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  const [open, setOpen] = useState(false);
  if (!userProfile?.id || activeAccount?.type !== 'personal' || !calendarSupported()) {
    return null;
  }
  const userId = String(userProfile.id);
  return (
    <>
      <Pressable style={styles.row} onPress={() => setOpen(true)} accessibilityRole="button">
        <Icon name="calendar" size={18} color={colors.successText} />
        <Text style={styles.label}>Tu agenda</Text>
        <Icon name="chevron-right" size={18} color={colors.textSecondary} />
      </Pressable>
      {open ? <CalendarConnectSheet key={userId} userId={userId} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

// With the flag off this reads no context and no native module.
export default function CalendarEntry() {
  return ASSISTANT_CALENDAR_ENABLED ? <Entry /> : null;
}

const styles = StyleSheet.create({
  row: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16 },
  label: { flex: 1, fontSize: 15, color: colors.textFlat },
});
