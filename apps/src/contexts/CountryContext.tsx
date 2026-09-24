import React, { createContext, useContext, useState, useEffect, ReactNode, useRef } from 'react';
import { useQuery } from '@apollo/client';
import { GET_ME } from '../apollo/queries';
import { Country, getCountryByIso } from '../utils/countries';
import { useAuth } from './AuthContext';

interface CountryContextType {
  userCountry: Country | null;
  selectedCountry: Country | null;
  setSelectedCountry: (country: Country | null) => void;
  isLoading: boolean;
}

const CountryContext = createContext<CountryContextType | undefined>(undefined);

interface CountryProviderProps {
  children: ReactNode;
}

export const CountryProvider: React.FC<CountryProviderProps> = ({ children }) => {
  const { userProfile, isAuthenticated } = useAuth();
  const { data: userData, loading } = useQuery(GET_ME, {skip: !isAuthenticated});
  const resolveCountry = (iso?: string) => iso ? getCountryByIso(iso.trim().toUpperCase()) || null : null;
  // Auth owns the current profile. Ignore a cached query belonging to another user.
  const queryMatchesUser = !!userProfile?.id && userProfile.id === userData?.me?.id;
  const userCountry = isAuthenticated
    ? resolveCountry(userProfile?.phoneCountry)
      || (queryMatchesUser ? resolveCountry(userData?.me?.phoneCountry) : null)
    : null;
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null);
  const previousUserCountryIsoRef = useRef<string | null>(null);
  const userId = isAuthenticated ? userProfile?.id || null : null;
  const previousUserIdRef = useRef(userId);

  // Determine user's country from their phone country (ISO code)
  useEffect(() => {
    const nextUserCountry = userCountry;
    const nextUserCountryIso = nextUserCountry?.[2] || null;
    const previousUserCountryIso = previousUserCountryIsoRef.current;
    const userChanged = previousUserIdRef.current !== userId;

    setSelectedCountry(prev => {
      if (!prev || userChanged) {
        return nextUserCountry;
      }

      if (prev?.[2] === previousUserCountryIso) {
        return nextUserCountry;
      }

      return prev;
    });

    previousUserCountryIsoRef.current = nextUserCountryIso;
    previousUserIdRef.current = userId;
  }, [userCountry, userId]);

  const value: CountryContextType = {
    userCountry,
    selectedCountry,
    setSelectedCountry,
    isLoading: loading,
  };

  return (
    <CountryContext.Provider value={value}>
      {children}
    </CountryContext.Provider>
  );
};

export const useCountry = (): CountryContextType => {
  const context = useContext(CountryContext);
  if (context === undefined) {
    throw new Error('useCountry must be used within a CountryProvider');
  }
  return context;
};
