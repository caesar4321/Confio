// The Home eye toggle ("ocultar saldo") for the Cuenta inteligente heroes:
// read on mount and on every return to the screen, exactly the saved choice
// Inicio uses. Unreadable reads as visible, as on Home.
import { useEffect, useState } from 'react';
import { useNavigation } from '@react-navigation/native';
import { isBalanceHidden } from '../../utils/balanceVisibility';

export const HIDDEN_AMOUNT = '••••••';

export function useBalanceHidden(): boolean {
  const navigation = useNavigation<any>();
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    let live = true;
    const read = () => {
      void isBalanceHidden().then((h) => { if (live) { setHidden(h); } });
    };
    read();
    const unsubscribe = navigation?.addListener?.('focus', read);
    return () => {
      live = false;
      if (typeof unsubscribe === 'function') {
        unsubscribe();
      }
    };
  }, [navigation]);
  return hidden;
}
