import React, { createContext, useContext, ReactNode } from 'react';
import { usePushNotificationPrompt } from './usePushNotificationPrompt';
import { PushNotificationModal } from '../components/PushNotificationModal';

interface PushNotificationContextType {
  checkAndShowPrompt: () => Promise<void>;
}

const PushNotificationContext = createContext<PushNotificationContextType | undefined>(undefined);

export const PushNotificationProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { showModal, handleAllow, handleDeny, checkAndShowPrompt, needsSettings } = usePushNotificationPrompt();
  
  return (
    <PushNotificationContext.Provider value={{ checkAndShowPrompt }}>
      {children}
      <PushNotificationModal
        visible={showModal}
        onAllow={handleAllow}
        onDeny={handleDeny}
        needsSettings={needsSettings}
      />
    </PushNotificationContext.Provider>
  );
};

export const usePushNotificationContext = () => {
  const context = useContext(PushNotificationContext);
  if (!context) {
    throw new Error('usePushNotificationContext must be used within PushNotificationProvider');
  }
  return context;
};
