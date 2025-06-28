import { useState, useCallback } from 'react';

export const useProfileMenu = () => {
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  const openProfileMenu = useCallback(() => {
    console.log('useProfileMenu: Opening profile menu');
    setShowProfileMenu(true);
  }, []);

  const closeProfileMenu = useCallback(() => {
    console.log('useProfileMenu: Closing profile menu');
    setShowProfileMenu(false);
  }, []);

  return {
    showProfileMenu,
    openProfileMenu,
    closeProfileMenu,
  };
}; 