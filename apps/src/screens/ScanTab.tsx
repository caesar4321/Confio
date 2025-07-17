import React from 'react';
import { useAccountManager } from '../hooks/useAccountManager';
import { ScanScreen } from './ScanScreen';

export default function ScanTab(props: any) {
  const { activeAccount } = useAccountManager();
  const isBusiness = activeAccount?.type?.toLowerCase() === 'business';

  return <ScanScreen {...props} isBusiness={isBusiness} />;
} 