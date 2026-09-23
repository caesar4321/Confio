import { useCallback, useMemo, useRef } from 'react';
import { Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';

import type { RouteOption } from '../components/RouteSheet';
import { COMING_SOON_NOTE } from '../config/localRails';
import { AnalyticsService } from '../services/analyticsService';
import { useSavingsPortfolio } from './useSavingsPortfolio';
import cUSDLogo from '../assets/png/cUSD.png';
import USDTLogo from '../assets/png/USDT.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

/**
 * "Recibir con dirección": which tokens and networks the user's crypto
 * address accepts, plus the demand probes for networks we do not support.
 * Shared by the Transferir sheet and the Recibir screen's Avanzado section.
 */
export const useCryptoReceiveOptions = (onOptionSelected?: () => void): RouteOption[] => {
  const navigation = useNavigation<any>();
  const onOptionSelectedRef = useRef(onOptionSelected);
  onOptionSelectedRef.current = onOptionSelected;
  const onSelect = useCallback(() => onOptionSelectedRef.current?.(), []);

  // Geo-eligibility (Ondo) + phase-out (2026-07-30): since the deposit
  // pause, EVERYONE can receive USDT-BSC — the server routes eligible users
  // into cUSD+ and ineligible users into cUSD, so the receive option shows
  // for all; copy varies by what the money becomes.
  const { savings: savingsInfo } = useSavingsPortfolio();
  const cusdDepositsPaused = savingsInfo.cusdDepositsPaused;
  const savingsEntryAllowed = savingsInfo.enabled || cusdDepositsPaused;

  // Demand probe (Julian, 2026-07-04): rails we do NOT support yet stay
  // visible in the sheet. Two-stage signal (2026-07-06): a bare tap is
  // cheap curiosity, so real demand is the CONFIRMED stage — the user
  // explicitly asks to be notified. Same whitelisted event, `stage`
  // property separates the funnel levels; tap→confirm ratio comes free.
  const handleReceiveRailInterest = useCallback((rail: string, label: string) => {
    onSelect();
    // House funnel (FunnelEvent table, admin-visible) + Firebase dual-emit.
    AnalyticsService.logFunnelEvent('receive_rail_interest', { rail, stage: 'tap' }, { sourceType: 'rail_interest', channel: 'receive' });
    Alert.alert(
      label,
      'Esta red estará disponible próximamente. ¿Quieres que te avisemos cuando puedas recibir por aquí?',
      [
        { text: 'Solo miraba', style: 'cancel' },
        {
          text: 'Sí, avísame',
          onPress: () => {
            AnalyticsService.logFunnelEvent('receive_rail_interest', {
              rail,
              stage: 'confirmed',
            }, { sourceType: 'rail_interest', channel: 'receive' });
            Alert.alert(
              '¡Anotado!',
              'Te avisamos apenas esté listo. Si lo necesitas pronto, ' +
                'escríbenos al soporte y te damos prioridad.',
            );
          },
        },
      ],
    );
  }, [onSelect]);

  return useMemo((): RouteOption[] => [
    // Algorand deposit UI hides with the phase-out (server-flippable
    // via cusdDepositsPaused); DepositScreen stays registered for
    // support deep links and pending deposits.
    ...(!cusdDepositsPaused ? [
    {
      icon: 'dollar-sign',
      image: cUSDLogo,
      title: 'cUSD · USDC · CONFIO',
      subtitle: 'Red Algorand · tu dirección de siempre',
      onPress: () => {
        onSelect();
        navigation.navigate('USDCDeposit', {});
      },
    }] : []),
    ...(savingsEntryAllowed ? [
    {
      icon: 'download',
      image: USDTLogo,
      title: 'Tether · USDT',
      subtitle: savingsInfo.enabled
        ? 'Red BNB Smart Chain (BEP-20) · directo a tu ahorro (Confío Dollar+)'
        : 'Red BNB Smart Chain (BEP-20) · directo a tu Confío Dollar',
      onPress: () => {
        onSelect();
        navigation.navigate('ReceiveSavings', {
          destination: savingsInfo.enabled ? 'cusd_plus' : 'usdt',
        });
      },
    }] : []),
    // CONFIO shares the very same BSC address as the dollar rails —
    // one BEP-20 address holds every token — so this row exists purely
    // to say "yes, you can receive CONFIO here" with CONFIO's own
    // network warning. Without it the sheet implied USDT was the only
    // thing this address accepts.
    {
      icon: 'zap',
      image: CONFIOLogo,
      title: 'Confío · $CONFIO',
      subtitle: 'Red BNB Smart Chain (BEP-20) · moneda de gobernanza y utilidad',
      onPress: () => {
        onSelect();
        navigation.navigate('ReceiveSavings', { destination: 'confio' });
      },
    },
    // Demand probes stay VISIBLE everywhere: they measure rail-level
    // demand, destination-neutral. When a rail ships it offers the
    // two-world choice (usar → cUSD / ahorrar → cUSD+) mirroring
    // Recargar; only the savings destination is geo-gated then.
    {
      // Takenos/Meru migration corridor hypothesis (2026-07-06):
      // Meru balances live on Polygon, so this probe sizes the
      // "move your USD account to Confío" demand specifically.
      icon: 'clock',
      title: 'USDC · USDT (Polygon)',
      subtitle: 'Red Polygon',
      note: COMING_SOON_NOTE,
      onPress: () =>
        handleReceiveRailInterest('polygon', 'USDC / USDT (Polygon)'),
    },
    {
      icon: 'clock',
      title: 'USDC · USDT (Ethereum)',
      subtitle: 'Red Ethereum (ERC-20)',
      note: COMING_SOON_NOTE,
      onPress: () =>
        handleReceiveRailInterest('eth_erc20', 'USDC / USDT (Ethereum)'),
    },
    {
      icon: 'clock',
      title: 'USDT (Tron)',
      subtitle: 'Red Tron (TRC-20)',
      note: COMING_SOON_NOTE,
      onPress: () => handleReceiveRailInterest('usdt_tron', 'USDT (Tron)'),
    },
  ], [cusdDepositsPaused, savingsEntryAllowed, savingsInfo.enabled, navigation, onSelect, handleReceiveRailInterest]);
};
