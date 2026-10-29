import React, { useMemo } from 'react';
import { Alert } from 'react-native';
import { RouteSheet, RouteOption } from './RouteSheet';
import { KOYWE_ROUTING_COUNTRIES, isRampBlockedCountry } from '../config/env';
import { countryName } from '../config/localRails';

/**
 * "Recargar desde …": the countries whose banks Recargar/Retirar can use,
 * the user's own (railCountries: picked, residence, documents) first. The
 * pick is saved server-side and leads from then on (useRampCountry).
 */
export const RampCountrySheet = ({
  visible,
  current,
  railCountries,
  onPick,
  onClose,
  title = '¿Desde qué país vas a recargar?',
}: {
  visible: boolean;
  current: string | null;
  railCountries: string[];
  onPick: (iso: string) => Promise<void>;
  onClose: () => void;
  title?: string;
}) => {
  const options: RouteOption[] = useMemo(() => {
    const available = KOYWE_ROUTING_COUNTRIES.map(code => code.toUpperCase());
    // The user's own countries first, Koywe's or not: one Koywe doesn't
    // cover opens Guardarian (card or international transfer).
    const mine = railCountries.filter(code => available.includes(code) || !isRampBlockedCountry(code));
    const ordered = [...mine, ...available.filter(code => !mine.includes(code))];
    return ordered.map(code => ({
      id: code,
      country: code,
      icon: 'globe',
      title: countryName(code),
      subtitle: code === current ? 'Elegido ahora'
        : available.includes(code) ? 'Bancos y billeteras de este país' : 'Tarjeta o transferencia internacional',
      onPress: () => {
        onClose();
        onPick(code).catch((error: any) => {
          Alert.alert('No pudimos cambiar el país', error?.message || 'Intenta nuevamente.');
        });
      },
    }));
  }, [current, onClose, onPick, railCountries]);

  return (
    <RouteSheet visible={visible} title={title} options={options} onClose={onClose} />
  );
};
