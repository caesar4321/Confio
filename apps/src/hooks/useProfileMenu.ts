import { useState, useCallback, useMemo } from 'react';

export const useProfileMenu = () => {
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  const openProfileMenu = useCallback(() => {
    setShowProfileMenu(true);
  }, []);

  const closeProfileMenu = useCallback(() => {
    setShowProfileMenu(false);
  }, []);

  return useMemo(() => ({
    showProfileMenu,
    openProfileMenu,
    closeProfileMenu,
  }), [showProfileMenu, openProfileMenu, closeProfileMenu]);
}; 
