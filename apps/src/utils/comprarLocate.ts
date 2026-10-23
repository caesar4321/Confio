import { Alert, Linking } from 'react-native';
import type { LocateOutcome } from '../hooks/useComprarLocation';

/**
 * Say what "Usar mi ubicación" ended in. A tap that silently changes nothing
 * reads as a broken button, so every outcome but success gets a line.
 */
export const explainLocateOutcome = (outcome: LocateOutcome, onPickCity: () => void): void => {
  if (outcome === 'found' || outcome === 'stale') return;
  if (outcome === 'denied') {
    Alert.alert(
      'Ubicación desactivada',
      'Para usar tu ubicación, permite que Confío acceda a ella en los ajustes del teléfono. También puedes elegir tu ciudad.',
      [
        { text: 'Elegir ciudad', onPress: onPickCity },
        { text: 'Abrir ajustes', onPress: () => { void Linking.openSettings(); } },
      ],
    );
    return;
  }
  if (outcome === 'no_city') {
    Alert.alert(
      'Aún no estamos en tu ciudad',
      'Comprar todavía no tiene tu ciudad. Elige una ciudad cercana para ver sus tiendas.',
      [{ text: 'Elegir ciudad', onPress: onPickCity }],
    );
    return;
  }
  Alert.alert(
    'No pudimos obtener tu ubicación',
    'Revisa que la ubicación del teléfono esté activada e inténtalo de nuevo, o elige tu ciudad.',
    [{ text: 'Elegir ciudad', onPress: onPickCity }, { text: 'Cerrar', style: 'cancel' }],
  );
};
