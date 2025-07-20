import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useQuery } from '@apollo/client';
import { GET_ME } from '../apollo/queries';
import { Country, countries, getCountryByIso } from '../utils/countries';

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
  const { data: userData, loading } = useQuery(GET_ME);
  const [userCountry, setUserCountry] = useState<Country | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null);

  // Determine user's country from their phone country (ISO code)
  useEffect(() => {
    if (userData?.me?.phoneCountry) {
      const country = getCountryByIso(userData.me.phoneCountry);
      
      if (country) {
        setUserCountry(country);
        setSelectedCountry(country);
      } else {
        // Fallback to Venezuela if phone country not found
        const venezuelaCountry = countries.find(c => c[0] === 'Venezuela') || null;
        setUserCountry(venezuelaCountry);
        setSelectedCountry(venezuelaCountry);
      }
    } else {
      // Fallback to Venezuela if no phone country
      const venezuelaCountry = countries.find(c => c[0] === 'Venezuela') || null;
      setUserCountry(venezuelaCountry);
      setSelectedCountry(venezuelaCountry);
    }
  }, [userData?.me?.phoneCountry]);

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