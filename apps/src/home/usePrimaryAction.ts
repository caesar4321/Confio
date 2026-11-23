// The one thing every screen of the conversation home does without the
// assistant (docs/designs/ai-assistant-first-redesign.md 7.3, 7.6): Pagar for
// a person, Cobrar for a business; an employee gets what their role allows.
import { useMemo } from 'react';
import { useNavigation } from '@react-navigation/native';
import { useAccount } from '../contexts/AccountContext';

export type PrimaryAction = { kind: 'pay' | 'charge'; onPress: () => void };

export function usePrimaryAction(): PrimaryAction | null {
  const navigation = useNavigation<any>();
  const { activeAccount } = useAccount();
  const type = (activeAccount?.type || 'personal').toLowerCase();
  const isEmployee = !!activeAccount?.isEmployee;
  const canPay = !isEmployee || activeAccount?.employeePermissions?.sendFunds === true;
  const canCharge = !isEmployee || activeAccount?.employeePermissions?.acceptPayments === true;
  return useMemo(() => {
    // Pagar is the stack's scanner (it has a back arrow; there is no Pagar
    // tab here). A business keeps Cobrar as a tab route, which `navigate`
    // reaches from Inicio; from anywhere else it is the same screen pushed.
    // Both show the back arrow.
    const pay: PrimaryAction = { kind: 'pay', onPress: () => navigation.navigate('Scan', { mode: 'pagar' }) };
    const charge: PrimaryAction = { kind: 'charge', onPress: () => navigation.navigate('Charge') };
    if (type === 'smart') {
      return null;
    }
    if (type === 'business') {
      return canCharge ? charge : canPay ? pay : null;
    }
    return canPay ? pay : null;
  }, [navigation, type, canPay, canCharge]);
}
