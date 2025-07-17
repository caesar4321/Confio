import React, { createContext, useContext, useState, ReactNode } from 'react';

type ScanMode = 'cobrar' | 'pagar' | null;

interface ScanContextType {
  scanMode: ScanMode;
  setScanMode: (mode: ScanMode) => void;
  clearScanMode: () => void;
}

const ScanContext = createContext<ScanContextType | undefined>(undefined);

interface ScanProviderProps {
  children: ReactNode;
}

export const ScanProvider: React.FC<ScanProviderProps> = ({ children }) => {
  const [scanMode, setScanMode] = useState<ScanMode>(null);

  const clearScanMode = () => {
    setScanMode(null);
  };

  return (
    <ScanContext.Provider
      value={{
        scanMode,
        setScanMode,
        clearScanMode,
      }}
    >
      {children}
    </ScanContext.Provider>
  );
};

export const useScan = () => {
  const context = useContext(ScanContext);
  if (context === undefined) {
    throw new Error('useScan must be used within a ScanProvider');
  }
  return context;
}; 