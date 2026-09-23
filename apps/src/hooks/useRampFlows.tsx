import React, { useCallback, useRef, useState } from 'react';

import { RouteSheet, RouteOption } from '../components/RouteSheet';
import { useRampCountry } from './useRampCountry';
import { useSavingsPortfolio } from './useSavingsPortfolio';

const formatFixedFloor = (value: number, decimals = 2) => {
  const m = 10 ** decimals;
  return (Math.floor(value * m) / m).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

/**
 * Recargar and Retirar as flows, not as Home buttons.
 *
 * They used to live inline in HomeScreen as two of five quick actions. In the
 * two-verb IA they are rows inside Recibir ("Recargar ahora") and Enviar
 * ("A mi propia cuenta") — the same money movement, filed under the verb it
 * actually is. Both screens need the identical world pickers, so the logic
 * lives here and each caller renders `sheets` once.
 *
 * `legacyCusdBalance` is the Algorand cUSD from GET_MY_BALANCES; the caller
 * owns that query because its fetch policy and auth gating differ per screen.
 */
export const useRampFlows = ({ legacyCusdBalance }: { legacyCusdBalance: number }) => {
  const savingsPortfolio = useSavingsPortfolio();
  // Recargar/Retirar run through ramp providers (Koywe/Guardarian). Where
  // neither operates (VE, NI, PA, CU, ...), the shared hook blocks up front
  // and points to the cash directory instead of failing deep inside the
  // provider flow.
  const { navigateToRampOrEfectivo, isBlocked } = useRampCountry();

  // World pickers: Recargar/Retirar route money between the two settlement
  // worlds — spend (cUSD · Algorand) vs grow (cUSD+ · savings chain). Two
  // doors teach the split; more doors teach confusion.
  const [rechargeSheetVisible, setRechargeSheetVisible] = useState(false);
  const [withdrawSheetVisible, setWithdrawSheetVisible] = useState(false);

  // cUSD phase-out (cusdDepositsPaused, server-flipped): the promoted door
  // for EVERYONE is the USDT-BSC rail. Eligibility only decides what the
  // delivered USDT becomes (silent mint to cUSD+ vs raw "Confío Dollar"),
  // so the copy varies but the destination doesn't.
  const savingsRechargeOption: RouteOption = {
    icon: 'trending-up',
    title: savingsPortfolio.savings.enabled
      ? 'Para ahorrar e invertir'
      : 'Recargar dólares',
    subtitle: savingsPortfolio.savings.enabled
      ? 'Gana rendimiento mientras decides · cUSD+'
      : 'Se acreditan en tu Confío Dollar',
    onPress: () => {
      navigateToRampOrEfectivo('TopUp', { destination: 'cusd_plus' });
    },
  };
  const cusdRechargeOption: RouteOption = {
    icon: 'dollar-sign',
    // While paused this door exists to UNBLOCK A DRAIN, not to sell cUSD:
    // an off-ramp has a per-method minimum, so a leftover balance below it
    // is stranded unless the user can top it back up to the threshold.
    title: savingsPortfolio.savings.cusdDepositsPaused
      ? 'Al antiguo Confío Dollar'
      : 'Para usar día a día',
    subtitle: savingsPortfolio.savings.cusdDepositsPaused
      ? 'Completa el mínimo para poder retirarlo · cUSD'
      : 'Enviar, pagar y comprar CONFIO · cUSD',
    onPress: () => {
      navigateToRampOrEfectivo('TopUp');
    },
  };
  // The cUSD door follows the SAME rule as Home's legacy wallet row
  // (`!paused || cUSDBalance > 0`): hidden from people with nothing to
  // drain, kept for holders — otherwise a balance under the off-ramp
  // minimum can never be withdrawn at all.
  const showLegacyCusdDoor =
    !savingsPortfolio.savings.cusdDepositsPaused || legacyCusdBalance > 0;
  const rechargeOptions: RouteOption[] = showLegacyCusdDoor
    ? [savingsRechargeOption, cusdRechargeOption]
    : [savingsRechargeOption];

  // What the BSC withdrawal rail can actually move in ONE operation: BOTH
  // legs. The funding batch redeems the shortfall out of the vault and pays
  // from the combined balance in a single transaction. SUM, matching the
  // sell screens (audit 2026-08-03 [P2] #13).
  const bscWithdrawableUsd =
    savingsPortfolio.savings.balanceUsd + savingsPortfolio.cusdBalanceUsd;

  // Both options land in the user's bank — the differentiator is where the
  // money sits NOW, so subtitles show live balances instead of destinations.
  // The legacy cUSD row is OMITTED (not merely disabled) once drained.
  const withdrawOptions: RouteOption[] = [
    ...(showLegacyCusdDoor
      ? [{
        icon: 'dollar-sign',
        title: 'Desde mi cUSD',
        subtitle: `$${formatFixedFloor(legacyCusdBalance, 2)} disponibles`,
        disabled: legacyCusdBalance <= 0,
        onPress: () => {
          navigateToRampOrEfectivo('Sell');
        },
      } as RouteOption]
      : []),
    {
      icon: 'trending-up',
      title: 'Desde mis ahorros',
      // Stocks stay excluded: they can't exit through here, so totalUsd
      // would overstate what's withdrawable.
      subtitle: bscWithdrawableUsd > 0
        ? `$${formatFixedFloor(bscWithdrawableUsd, 2)} en ${savingsPortfolio.savings.enabled ? 'Confío Dollar+' : 'Confío Dollar'}`
        : 'Aún no tienes ahorros',
      disabled: bscWithdrawableUsd <= 0,
      onPress: () => {
        // Savings sells ride Guardarian everywhere (SellScreen routes on
        // `destination`, not on the country).
        navigateToRampOrEfectivo('Sell', { destination: 'cusd_plus' });
      },
    },
  ];

  // A one-option sheet is pure friction: go straight to the flow. Read via
  // refs so the returned callbacks stay referentially stable for callers
  // that memoize on them.
  const rechargeOptionsRef = useRef(rechargeOptions);
  rechargeOptionsRef.current = rechargeOptions;
  const openRechargeFlow = useCallback(() => {
    const opts = rechargeOptionsRef.current;
    if (opts.length === 1) {
      opts[0].onPress();
      return;
    }
    setRechargeSheetVisible(true);
  }, []);

  const withdrawOptionsRef = useRef(withdrawOptions);
  withdrawOptionsRef.current = withdrawOptions;
  const openWithdrawFlow = useCallback(() => {
    // Skip the sheet only when exactly one door is actually USABLE: a
    // withdraw row can be disabled, and onPress() would still fire —
    // dropping the user into an empty Sell screen.
    const usable = withdrawOptionsRef.current.filter((o) => !o.disabled);
    if (usable.length === 1) {
      usable[0].onPress();
      return;
    }
    setWithdrawSheetVisible(true);
  }, []);

  const sheets = (
    <>
      <RouteSheet
        visible={rechargeSheetVisible}
        title="¿Para qué es esta recarga?"
        options={rechargeOptions}
        onClose={() => setRechargeSheetVisible(false)}
      />
      <RouteSheet
        visible={withdrawSheetVisible}
        title="¿Desde dónde quieres retirar?"
        options={withdrawOptions}
        onClose={() => setWithdrawSheetVisible(false)}
      />
    </>
  );

  return {
    openRechargeFlow,
    openWithdrawFlow,
    sheets,
    isRampBlocked: isBlocked,
    bscWithdrawableUsd,
  };
};
