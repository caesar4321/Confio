import { Alert } from 'react-native';

import { biometricAuthService } from '../services/biometricAuthService';
import { formatRampMoney } from './rampFormat';

const ACTION_COPY = {
  compra: ['la compra', 'esta compra'],
  retiro: ['el retiro', 'este retiro'],
  'envío': ['el envío', 'este envío'],
  'conversión': ['la conversión', 'esta conversión'],
} as const;

export const requestRampCriticalAuth = async ({
  amount,
  assetUnit,
  assetNote,
  actionLabel,
}: {
  amount: number;
  assetUnit: string;
  // Where the money lands, when the unit alone doesn't say it ("ahorro").
  assetNote?: string;
  actionLabel: 'compra' | 'retiro' | 'envío' | 'conversión';
}) => {
  const [definite, demonstrative] = ACTION_COPY[actionLabel];
  const authMessage = amount > 0
    ? `Autoriza ${definite} de ${formatRampMoney(amount, assetUnit)}${assetNote ? ` (${assetNote})` : ''}`
    : `Autoriza ${demonstrative}`;

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
      `Debes autenticarte para confirmar ${demonstrative}.`,
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

