import React, { useCallback } from 'react';
import { BackHandler } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { EmergencyExitScreen } from './EmergencyExitScreen';

// Recovery is the only root route while locked: it has no previous screen.
// Its own Confío header owns the UI; closing returns to the still-locked app.
export const emergencyRecoveryOptions = { headerShown: false, gestureEnabled: false };

export function EmergencyRecoveryScreen({ onClose }: { onClose: () => void }) {
  useFocusEffect(useCallback(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      onClose();
      return true;
    });
    return () => subscription.remove();
  }, [onClose]));
  return <EmergencyExitScreen onClose={onClose} />;
}
