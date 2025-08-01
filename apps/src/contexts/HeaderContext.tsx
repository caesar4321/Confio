import React, { createContext, useContext, useState, ReactNode, useEffect } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useProfileMenu } from '../hooks/useProfileMenu';
import { useQuery } from '@apollo/client';
import { GET_UNREAD_NOTIFICATION_COUNT } from '../apollo/queries';

interface HeaderContextType {
  unreadNotifications: number;
  currentAccountAvatar: string;
  setUnreadNotifications: (count: number) => void;
  setCurrentAccountAvatar: (avatar: string) => void;
  profileMenu: ReturnType<typeof useProfileMenu>;
}

const HeaderContext = createContext<HeaderContextType | undefined>(undefined);

interface HeaderProviderProps {
  children: ReactNode;
}

export const HeaderProvider: React.FC<HeaderProviderProps> = ({ children }) => {
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [currentAccountAvatar, setCurrentAccountAvatar] = useState('');
  const profileMenu = useProfileMenu();
  
  // Query for unread notification count
  const { data: unreadCountData, refetch: refetchUnreadCount } = useQuery(GET_UNREAD_NOTIFICATION_COUNT, {
    fetchPolicy: 'cache-and-network',
    pollInterval: 30000, // Poll every 30 seconds
    notifyOnNetworkStatusChange: true,
  });
  
  // Update unread count when query data changes
  useEffect(() => {
    if (unreadCountData?.unreadNotificationCount !== undefined) {
      setUnreadNotifications(unreadCountData.unreadNotificationCount);
    }
  }, [unreadCountData]);
  
  // Refetch notification count when app comes to foreground
  useEffect(() => {
    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      if (nextAppState === 'active') {
        console.log('[HeaderContext] App became active, refetching notification count...');
        refetchUnreadCount();
      }
    };
    
    const subscription = AppState.addEventListener('change', handleAppStateChange);
    
    return () => {
      subscription.remove();
    };
  }, [refetchUnreadCount]);

  return (
    <HeaderContext.Provider
      value={{
        unreadNotifications,
        currentAccountAvatar,
        setUnreadNotifications,
        setCurrentAccountAvatar,
        profileMenu,
      }}
    >
      {children}
    </HeaderContext.Provider>
  );
};

export const useHeader = () => {
  const context = useContext(HeaderContext);
  if (context === undefined) {
    throw new Error('useHeader must be used within a HeaderProvider');
  }
  return context;
}; 