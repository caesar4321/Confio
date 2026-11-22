import React, { useState } from 'react';
import { Pressable } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';
import { useAccount } from '../../contexts/AccountContext';
import { useAuth } from '../../contexts/AuthContext';
import { ASSISTANT_MAIL_ENABLED } from './flag';
import MailSheet from './MailSheet';
import { closeMailSession, mailSession } from './session';
import { styles } from './ui';

function Entry() {
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  const [, setChanged] = useState(0);
  if (!userProfile?.id || activeAccount?.type !== 'personal') {
    return null;
  }
  const userId = String(userProfile.id);
  // Read from the session, not from state: the lock remounts this row.
  const { open } = mailSession(userId);
  const setOpen = (next: boolean) => {
    if (next) {
      mailSession(userId).open = true;
    } else {
      closeMailSession(userId);
    }
    setChanged((count) => count + 1);
  };
  return (
    <>
      <Pressable style={styles.entry} onPress={() => setOpen(true)} accessibilityRole="button">
        <Icon name="mail" size={18} color={colors.successText} />
        <Text style={styles.entryLabel}>Tu correo</Text>
        <Icon name="chevron-right" size={18} color={colors.textSecondary} />
      </Pressable>
      {open ? <MailSheet key={userId} userId={userId} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

// With the flag off this reads no context and asks the server nothing.
export default function MailEntry() {
  return ASSISTANT_MAIL_ENABLED ? <Entry /> : null;
}
