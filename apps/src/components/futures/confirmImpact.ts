import { Alert } from 'react-native';

import type { AmountPrompt, ImpactPrompt } from '../../services/perps';
import { formatUsd } from '../../utils/perpsPresentation';

/** The second confirmation for an open that moves the price past the
 *  warning level (the server refuses anything past the maximum). */
export const confirmImpact: ImpactPrompt = ({ impactBps }) => new Promise((resolve) => {
  const pct = (impactBps / 100).toFixed(2).replace('.', ',');
  Alert.alert(
    'El precio se mueve al ejecutar',
    `Con la liquidez de este momento, tu orden se ejecutaría cerca de un ${pct}% peor que el precio de mercado. ¿La abrimos igual?`,
    [
      { text: 'No abrir', style: 'cancel', onPress: () => resolve(false) },
      { text: 'Abrir igual', onPress: () => resolve(true) },
    ],
    { cancelable: false },
  );
});

/** Hyperliquid holds more than the position showed (a refund, funding, an
 *  unapplied top-up): the member confirms the amount before it is signed. */
export const confirmReturnAmount: AmountPrompt = (usd) => new Promise((resolve) => {
  Alert.alert(
    'Traer tu dinero',
    `En tu cuenta de Hyperliquid hay ${formatUsd(usd)}, más de lo que mostraba tu posición. ¿Lo traemos todo a tus dólares?`,
    [
      { text: 'Ahora no', style: 'cancel', onPress: () => resolve(false) },
      { text: 'Traer todo', onPress: () => resolve(true) },
    ],
    { cancelable: false },
  );
});

/** A thin book: the close may fill well away from the market price. Staying
 *  open is a risk too, so the member decides. */
export const confirmDeepClose: ImpactPrompt = ({ impactBps }) => new Promise((resolve) => {
  const pct = (impactBps / 100).toFixed(1).replace('.', ',');
  Alert.alert(
    'Cerrar con poca liquidez',
    `Ahora hay poca liquidez: para cerrar todo, la orden podría ejecutarse hasta un ${pct}% lejos del precio de mercado. ¿Cerramos igual?`,
    [
      { text: 'Mantener abierta', style: 'cancel', onPress: () => resolve(false) },
      { text: 'Cerrar igual', style: 'destructive', onPress: () => resolve(true) },
    ],
    { cancelable: false },
  );
});
