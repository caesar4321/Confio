import { useState } from 'react';
import { useCountry } from '../contexts/CountryContext';
import { Country } from '../utils/countries';

export const useCountrySelection = () => {
  const { selectedCountry, setSelectedCountry, userCountry } = useCountry();
  const [showCountryModal, setShowCountryModal] = useState(false);

  const selectCountry = (country: Country | null) => {
    setSelectedCountry(country);
    setShowCountryModal(false);
  };

  const openCountryModal = () => {
    setShowCountryModal(true);
  };

  const closeCountryModal = () => {
    setShowCountryModal(false);
  };

  return {
    selectedCountry,
    userCountry,
    showCountryModal,
    selectCountry,
    openCountryModal,
    closeCountryModal,
    setSelectedCountry,
  };
};