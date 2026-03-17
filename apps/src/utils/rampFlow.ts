import { Alert } from 'react-native';

import { biometricAuthService } from '../services/biometricAuthService';

export const requestRampCriticalAuth = async ({
  amount,
  assetLabel,
  actionLabel,
}: {
  amount: number;
  assetLabel: string;
  actionLabel: 'compra' | 'retiro';
}) => {
  const authMessage = amount > 0
    ? `Autoriza ${actionLabel === 'compra' ? 'la compra' : 'el retiro'} de ${amount.toFixed(2)} ${assetLabel}`
    : `Autoriza ${actionLabel === 'compra' ? 'esta compra' : 'este retiro'}`;

  let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
  if (authenticated) {
    return true;
  }

  if (biometricAuthService.isLockout()) {
    Alert.alert(
      'Biometría bloqueada',
      'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
      [{ text: 'OK', style: 'default' }],
    );
    return false;
  }

  const shouldRetry = await new Promise<boolean>((resolve) => {
    Alert.alert(
      'Autenticación requerida',
      `Debes autenticarte para confirmar ${actionLabel === 'compra' ? 'esta compra' : 'este retiro'}.`,
      [
        { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
        { text: 'Reintentar', onPress: () => resolve(true) },
      ],
    );
  });

  if (!shouldRetry) {
    return false;
  }

  authenticated = await biometricAuthService.authenticate(authMessage, true, true);
  if (!authenticated) {
    Alert.alert('No autenticado', 'No pudimos validar tu identidad. Intenta de nuevo en unos segundos.');
    return false;
  }

  return true;
};

