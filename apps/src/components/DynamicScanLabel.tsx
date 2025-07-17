import React from 'react';
import { Text } from 'react-native';
import { useAccountManager } from '../hooks/useAccountManager';
import { useScan } from '../contexts/ScanContext';

interface DynamicScanLabelProps {
  color: string;
}

export function DynamicScanLabel({ color }: DynamicScanLabelProps) {
  const { activeAccount } = useAccountManager();
  const { scanMode } = useScan();
  const isBusiness = activeAccount?.type?.toLowerCase() === 'business';
  
  // Get the appropriate scan label
  const getScanLabel = () => {
    if (isBusiness) {
      if (scanMode === 'cobrar') return 'Cobrar';
      if (scanMode === 'pagar') return 'Pagar';
      return 'Cobrar'; // Default for business accounts
    }
    return 'Escanear';
  };
  
  console.log('🔍 DynamicScanLabel - Rendering:', {
    accountId: activeAccount?.id,
    accountType: activeAccount?.type,
    isBusiness,
    scanMode,
    label: getScanLabel()
  });

  return (
    <Text style={{ color, fontSize: 12 }}>
      {getScanLabel()}
    </Text>
  );
} 