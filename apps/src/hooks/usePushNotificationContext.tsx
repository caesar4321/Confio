import React, { createContext, useContext, ReactNode } from 'react';
import { usePushNotificationPrompt } from './usePushNotificationPrompt';

interface PushNotificationContextType {
  checkAndShowPrompt: () => Promise<void>;
}

const PushNotificationContext = createContext<PushNotificationContextType | undefined>(undefined);

export const PushNotificationProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { checkAndShowPrompt } = usePushNotificationPrompt();
  
  return (
    <PushNotificationContext.Provider value={{ checkAndShowPrompt }}>
      {children}
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