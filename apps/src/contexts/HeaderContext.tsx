import React, { createContext, useContext, useState, ReactNode } from 'react';
import { useProfileMenu } from '../hooks/useProfileMenu';

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
  const [unreadNotifications, setUnreadNotifications] = useState(3);
  const [currentAccountAvatar, setCurrentAccountAvatar] = useState('J');
  const profileMenu = useProfileMenu();

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