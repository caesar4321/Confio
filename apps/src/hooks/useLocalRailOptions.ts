import { useCallback, useMemo, useRef } from 'react';
import { Alert } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { useQuery } from '@apollo/client';
import { useFocusEffect, useNavigation } from '@react-navigation/native';

import type { RouteOption } from '../components/RouteSheet';
import {
  countryFlag,
  countryName,
  COMING_SOON_NOTE,
  getReceiveRails,
  getSendRails,
  toIso2,
  type LocalRail,
} from '../config/localRails';
import { AnalyticsService } from '../services/analyticsService';
import { isIdentityBlocked, showIdentityBlockedInterest, LOCAL_MONEY_METHODS, type LocalMethod } from '../services/localMoney';
import { useLocalPaymentAccounts } from './useLocalPaymentAccounts';
import { useRampCountry } from './useRampCountry';

/**
 * The local-rail rows (banks and fintech wallets) for both directions, as
 * RouteOptions. Shared by the sheets on Transferir and by the Recibir screen,
 * which lists the same rows inline.
 *
 * `onOptionSelected` runs before any row acts — callers that show the rows
 * in a sheet close it there; an inline list passes nothing.
 */
export const useLocalRailOptions = (onOptionSelected?: () => void) => {
  const navigation = useNavigation<any>();
  const onOptionSelectedRef = useRef(onOptionSelected);
  onOptionSelectedRef.current = onOptionSelected;
  const onSelect = useCallback(() => onOptionSelectedRef.current?.(), []);

  // ---------------------------------------------------------------------
  // Local rails (bancos y billeteras) — Bre-B, CLABE, alias/CVU, Pix, QR.
  //
  // These sit ABOVE the crypto address rows on purpose: sending to a bank or
  // to Nequi/Yape/Mercado Pago is what almost everyone came here to do, while
  // sending to a chain address is an advanced move most users never make.
  // "billetera" here means a fintech wallet (the LATAM meaning); a blockchain
  // destination is always "dirección", never "wallet".
  // ---------------------------------------------------------------------
  // Server-evaluated rails: feature flags + verified KYC + eligibility policy.
  // Fails soft — an older server or a network error leaves the demand probes,
  // never an error banner. (The bridge plumbing row that
  // used to sit here exposed an implementation leg as a user choice.)
  const { data: sendMethodsData, refetch: refetchSendMethods } = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'send' }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const { data: receiveMethodsData, refetch: refetchReceiveMethods } = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'receive' }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  // Re-read the rails on every focus, so a document
  // verified elsewhere (Verificación, AdditionalDocument) shows up at once.
  useFocusEffect(
    useCallback(() => {
      refetchSendMethods().catch(() => {});
      refetchReceiveMethods().catch(() => {});
    }, [refetchSendMethods, refetchReceiveMethods]),
  );
  // Phone country is an ORDERING hint only — it puts the user's own rail
  // first and decides nothing else. `isBlocked` from this hook is deliberately
  // NOT consulted: it encodes where Koywe/Guardarian operate, and the local
  // rails are a different network entirely. Venezuelans resident in Colombia
  // are an explicitly ALLOWED Cobre cohort, so reusing the ramp block would
  // shut out the exact cohort the seeded policy was written for.
  const { countryCode: phoneCountryHint } = useRampCountry();
  const { receivable: receivableLocalAccounts } = useLocalPaymentAccounts();

  const localSendRails = useMemo(
    () => getSendRails(phoneCountryHint),
    [phoneCountryHint],
  );
  const localReceiveRails = useMemo(
    () => getReceiveRails(phoneCountryHint),
    [phoneCountryHint],
  );

  // A usable rail is live, or one identity check away. Same ordering rule as
  // the probes: phone country hoists, it never decides.
  const usableMethods = useCallback((data: any): LocalMethod[] => {
    const rows = ((data?.localMoneyMethods || []) as LocalMethod[]).filter(
      // A rail this person's identity blocks stays listed: saying so plainly
      // beats hiding it behind a "próximamente" probe that is not the truth.
      method => method.status === 'live' || method.status === 'needs_verification'
        || method.status === 'needs_document' || isIdentityBlocked(method),
    );
    const mine = toIso2(phoneCountryHint);
    return [...rows.filter(m => m.country === mine), ...rows.filter(m => m.country !== mine)];
  }, [phoneCountryHint]);
  // One slot per country. A QR rail is an input mode of the country's main
  // rail (Argentina: CVU/CBU typed or QR scanned on the same screen).
  const liveSendMethods = useMemo(() => {
    const rows = usableMethods(sendMethodsData);
    const isQr = (m: LocalMethod) => m.id.endsWith('_qr');
    return rows
      .filter(m => !(isQr(m) && rows.some(o => o.country === m.country && !isQr(o))))
      .map(m => (!isQr(m) && rows.some(q => q.country === m.country && isQr(q) && q.status === 'live')
        ? { ...m, title: `${m.title.replace(' o ', ', ')} o QR` }
        : m));
  }, [usableMethods, sendMethodsData]);
  const liveReceiveMethods = useMemo(() => usableMethods(receiveMethodsData), [usableMethods, receiveMethodsData]);

  // The rail exists, but the provider refuses this person's nationality.
  // Saying so plainly, and counting who asks to be
  // told when it opens, is the demand estimate for that corridor. The server
  // adds the country of their IP, so "Venezuelans in Colombia" is countable.
  const handleBlockedRailInterest = useCallback((method: LocalMethod) => {
    onSelect();
    const event = {
      rail: method.id, country: method.country, direction: method.direction, reason: method.reason,
    };
    showIdentityBlockedInterest(`${method.title} · ${countryName(method.country)}`, stage => {
      AnalyticsService.logFunnelEvent('local_rail_blocked_interest', { ...event, stage },
        { sourceType: 'rail_interest', channel: method.direction });
    });
  }, [onSelect]);

  const methodToOption = useCallback((method: LocalMethod) => ({
    id: method.id,
    icon: isIdentityBlocked(method) ? 'clock' : method.direction === 'send' ? 'send' : 'download',
    flag: countryFlag(method.country),
    title: method.title,
    subtitle: method.subtitle,
    note: isIdentityBlocked(method)
      ? 'No disponible por ahora para tu nacionalidad'
      : method.status === 'needs_verification'
      ? 'Verifica tu identidad para usarlo'
      : method.status === 'needs_document'
        ? (method.documentTypes?.length === 1 && method.documentTypes[0] === 'P'
          ? 'Verifica tu pasaporte para usarlo'
          : 'Verifica otro documento para usarlo')
        : undefined,
    onPress: () => {
      onSelect();
      if (isIdentityBlocked(method)) {
        handleBlockedRailInterest(method);
        return;
      }
      if (method.status === 'needs_verification') {
        navigation.navigate('Verification');
        return;
      }
      if (method.status === 'needs_document') {
        // A second document for this rail; the primary verification stays.
        navigation.navigate('AdditionalDocument', {
          idCountry: method.documentCountry,
          documentTypes: method.documentTypes,
          reason: `Para ${method.title} en ${countryName(method.country)} necesitamos un documento distinto al que ya verificaste.`,
        });
        return;
      }
      navigation.navigate(method.direction === 'send' ? 'LocalSend' : 'LocalReceive', { methodId: method.id });
    },
  }), [handleBlockedRailInterest, navigation, onSelect]);

  // Same two-stage demand probe the crypto receive sheet uses: a bare tap is
  // curiosity, the confirmation is the real signal. Every corridor is a probe
  // until its provider flag is on server-side, so this is the honest answer
  // rather than a "próximamente" screen that teaches nothing.
  const handleLocalRailInterest = useCallback((rail: LocalRail, direction: 'send' | 'receive') => {
    onSelect();
    AnalyticsService.logFunnelEvent('local_rail_interest', {
      rail: rail.id,
      country: rail.country,
      direction,
      stage: 'tap',
    }, { sourceType: 'rail_interest', channel: direction });
    Alert.alert(
      `${rail.title} · ${countryName(rail.country)}`,
      direction === 'send'
        ? 'Este medio estará disponible próximamente. ¿Quieres que te avisemos cuando puedas enviar por aquí?'
        : 'Este medio estará disponible próximamente. ¿Quieres que te avisemos cuando puedas recibir por aquí?',
      [
        { text: 'Solo miraba', style: 'cancel' },
        {
          text: 'Sí, avísame',
          onPress: () => {
            AnalyticsService.logFunnelEvent('local_rail_interest', {
              rail: rail.id,
              country: rail.country,
              direction,
              stage: 'confirmed',
            }, { sourceType: 'rail_interest', channel: direction });
            Alert.alert(
              '¡Anotado!',
              'Te avisamos apenas esté listo. Si lo necesitas pronto, escríbenos al soporte y te damos prioridad.',
            );
          },
        },
      ],
    );
  }, [onSelect]);

  const railToOption = useCallback(
    (rail: LocalRail, direction: 'send' | 'receive') => ({
      // `id` matters here: six rails share the title "Cuenta bancaria", so
      // without it React would key three of them identically.
      id: rail.id,
      icon: rail.status === 'live' ? (direction === 'send' ? 'send' : 'download') : 'clock',
      flag: countryFlag(rail.country),
      title: rail.title,
      subtitle: rail.subtitle,
      note: rail.status === 'live' ? undefined : COMING_SOON_NOTE,
      onPress: () => handleLocalRailInterest(rail, direction),
    }),
    [handleLocalRailInterest],
  );

  // Copying IS the whole job of a receiving key — you paste it into WhatsApp
  // and someone pays you. Until the dedicated details screen exists (with QR
  // and share), the sheet does the one thing that makes the key useful, so a
  // provisioned account is never stranded behind an unbuilt screen.
  const handleCopyLocalKey = useCallback((value: string, label: string) => {
    onSelect();
    Clipboard.setString(value);
    Alert.alert('Copiado', `Tu ${label} se copió. Compártela con quien te va a pagar.`);
  }, [onSelect]);

  // A user's OWN accounts lead the receive sheet as real, live rows; the
  // corridors we cannot open yet follow as probes. Both providers sit behind
  // server flags that default to False, so this list is empty for everyone
  // today — which is exactly why the probes below it have to carry the sheet.
  const activeLocalReceiveOptions = useMemo(
    () =>
      // Infinia accounts open their own receive screen (details, deposits,
      // conversion) through the server rail rows; only other providers' keys
      // still use copy-on-tap here.
      receivableLocalAccounts.filter(account => account.provider !== 'infinia').flatMap(account =>
        account.fundingInstructions
          // A Bre-B key is listed without its value: it shows only on its own
          // screen, after a current location check (the server may withhold it).
          .filter(instruction => instruction.status === 'active'
            && (instruction.kind === 'breb_key' || !!instruction.displayValue))
          .map(instruction => ({
            id: instruction.internalId,
            icon: 'download',
            flag: countryFlag(account.country),
            title: instruction.kind === 'breb_key' ? 'Tu llave Bre-B' : instruction.displayValue,
            subtitle: instruction.kind === 'breb_key'
              ? 'Toca para verla'
              : instruction.holderDisplayName
                ? `A nombre de ${instruction.holderDisplayName} · toca para copiar`
                : 'Toca para copiar',
            // A Bre-B key opens its own screen (it shows after a location
            // check); other keys still copy on tap.
            onPress: () => {
              if (instruction.kind === 'breb_key') {
                onSelect();
                navigation.navigate('LocalReceive', { methodId: 'cobre_co_breb_receive' });
                return;
              }
              handleCopyLocalKey(instruction.displayValue, 'cuenta');
            },
          })),
      ),
    [receivableLocalAccounts, handleCopyLocalKey, navigation, onSelect],
  );

  // Enviar and Recibir show rails the SAME way: what the user can use now
  // (or unlock with a document) inline; nationality-blocked rails and
  // not-yet-open corridors behind "Más países". Before, Enviar hid every
  // rail behind one row while Recibir listed all of them, probes included.
  const usableNow = (method: LocalMethod) => !isIdentityBlocked(method);

  const sendPrimary: RouteOption[] = useMemo(
    () => liveSendMethods.filter(usableNow).map(methodToOption),
    [liveSendMethods, methodToOption],
  );
  const sendMore: RouteOption[] = useMemo(() => [
    ...liveSendMethods.filter(m => !usableNow(m)).map(methodToOption),
    // A country served by a real rail must not also show as a probe.
    ...localSendRails
      .filter(rail => !liveSendMethods.some(method => method.country === rail.country))
      .map(rail => railToOption(rail, 'send')),
  ], [liveSendMethods, localSendRails, methodToOption, railToOption]);

  const receivePrimary: RouteOption[] = useMemo(() => [
    ...activeLocalReceiveOptions,
    ...liveReceiveMethods.filter(usableNow).map(methodToOption),
  ], [activeLocalReceiveOptions, liveReceiveMethods, methodToOption]);
  const receiveMore: RouteOption[] = useMemo(() => [
    ...liveReceiveMethods.filter(m => !usableNow(m)).map(methodToOption),
    ...localReceiveRails
      // A corridor the user already has an active account for would
      // otherwise appear twice: once as their real key, once as a
      // probe inviting them to ask for what they already own.
      .filter(
        rail =>
          !receivableLocalAccounts.some(
            account => toIso2(account.country) === rail.country,
          )
          && !liveReceiveMethods.some(method => method.country === rail.country),
      )
      .map(rail => railToOption(rail, 'receive')),
  ], [liveReceiveMethods, localReceiveRails, receivableLocalAccounts, methodToOption, railToOption]);

  return { sendPrimary, sendMore, receivePrimary, receiveMore };
};
