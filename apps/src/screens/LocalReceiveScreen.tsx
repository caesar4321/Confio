import React, { useCallback, useEffect, useRef, useState } from 'react';
import LocalAccountApplicationScreen from './LocalAccountApplicationScreen';
import VePagoMovilReceiveScreen from './VePagoMovilReceiveScreen';
import BoliviaQrReceiveScreen from './BoliviaQrReceiveScreen';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  Share,
  StatusBar,
  StyleSheet,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import { Text } from '../components/common/AppText';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import QRCode from 'react-native-qrcode-svg';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { countryName } from '../config/localRails';
import { FlagLabel } from '../components/CountryFlag';
import { useBrebLocationPass } from '../components/breb/BrebLocationGate';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { formatRampMoney, USD_UNIT } from '../utils/rampFormat';
import {
  currencyName,
  LOCAL_MONEY_LIMITS,
  LOCAL_MONEY_METHODS,
  LOCAL_RECEIVE_ACCOUNT,
  LocalLimits,
  LocalMethod,
  LocalReceiveAccount,
} from '../services/localMoney';

type Nav = NativeStackNavigationProp<MainStackParamList, 'LocalReceive'>;
type Route = RouteProp<MainStackParamList, 'LocalReceive'>;

// "Tu propia/tu propio", never "a tu nombre" as a titling promise — see the
// copy rule on RECEIVE_RAILS in config/localRails.ts.
const COPY: Record<string, { hero: string; label: string; rail: string }> = {
  co_breb_receive: { hero: 'Tu propia llave Bre-B', label: 'Tu llave Bre-B', rail: 'Bre-B' },
  br_pix_receive: { hero: 'Tu cuenta Pix', label: 'Tus datos Pix', rail: 'Pix' },
  mx_clabe_receive: { hero: 'Tu propia CLABE', label: 'Tu CLABE', rail: 'SPEI' },
  ar_cvu_receive: { hero: 'Tu propio CVU', label: 'Tu CVU', rail: 'transferencia' },
};


export default function LocalReceiveScreen() {
  const { methodId } = useRoute<Route>().params;
  // Cobre's Bre-B key lives on its application screen.
  if (methodId === 'cobre_co_breb_receive') return <LocalAccountApplicationScreen />;
  // Venezuela: a per-order Pago Móvil top-up, not a standing account.
  if (methodId === 've_pagomovil_receive') return <VePagoMovilReceiveScreen />;
  if (methodId === 'bo_qr_receive') return <BoliviaQrReceiveScreen />;
  return <InfiniaLocalReceiveScreen />;
}

function InfiniaLocalReceiveScreen() {
  const navigation = useNavigation<Nav>();
  const { methodId } = useRoute<Route>().params;
  const { width } = useWindowDimensions();
  const isCompact = width < 380;

  const accountQuery = useQuery(LOCAL_RECEIVE_ACCOUNT, {
    variables: { methodId }, fetchPolicy: 'network-only', errorPolicy: 'all',
  });
  const account: LocalReceiveAccount | undefined = accountQuery.data?.localReceiveAccount;
  const isPixQr = methodId === 'br_pix_receive' && account?.instructionKind === 'qr';
  const copy = isPixQr
    ? { hero: 'Tu código Pix', label: 'Tu código Pix Copia e Cola', rail: 'Pix' }
    : methodId === 'br_pix_receive' && account?.instructionKind === 'pix_key' && account?.value
      ? { hero: 'Tu propia chave Pix', label: 'Tu chave Pix', rail: 'Pix' }
    : COPY[methodId] || COPY.mx_clabe_receive;
  // A Bre-B key shows only while this account's location pass lasts, also
  // when the screen stays open past it (the server withholds it on reload).
  const brebKeyScreen = methodId === 'co_breb_receive';
  const passOk = useBrebLocationPass(brebKeyScreen);
  // A verification may finish after this screen has already regained focus.
  // Reload the server-withheld key when that pass arrives, without another tab change.
  const accountRefetch = useRef(accountQuery.refetch);
  accountRefetch.current = accountQuery.refetch;
  useEffect(() => {
    if (brebKeyScreen && passOk) accountRefetch.current().catch(() => {});
  }, [brebKeyScreen, passOk]);
  const accountValue = account && (!brebKeyScreen || passOk) ? account.value : '';
  const [accountRetrying, setAccountRetrying] = useState(false);
  // The server withholds a Bre-B key without a recent location check; the
  // check screen renews it and the key loads on return.
  const revealKey = () => navigation.navigate('BrebLocationCheck');
  const methodsQuery = useQuery(LOCAL_MONEY_METHODS, {
    variables: { direction: 'receive' }, fetchPolicy: 'cache-and-network', errorPolicy: 'all',
  });
  const receiveMethod: LocalMethod | undefined = (methodsQuery.data?.localMoneyMethods || [])
    .find((row: LocalMethod) => row.id === methodId);
  const active = account?.status === 'active' && Boolean(account.value);
  const limitsQuery = useQuery(LOCAL_MONEY_LIMITS, { fetchPolicy: 'network-only', errorPolicy: 'all', skip: !active });
  const limits: LocalLimits | undefined = limitsQuery.data?.localMoneyLimits;

  // Back from another screen (a document verified, a conversion made): the
  // account and rails may have changed. A ref keeps the focus effect
  // from depending on query objects.
  const refreshOnFocus = useRef(() => {});
  refreshOnFocus.current = () => {
    accountQuery.refetch().catch(() => {});
    methodsQuery.refetch().catch(() => {});
    if (active) limitsQuery.refetch().catch(() => {}); // e.g. back from an approved limit increase
  };
  useFocusEffect(useCallback(() => { refreshOnFocus.current(); }, []));

  const aliveRef = useRef(true);
  useEffect(() => () => { aliveRef.current = false; }, []);

  const place = account ? countryName(account.country) : '';
  const currency = account ? currencyName(account.asset) : 'moneda local';


  const shareMessage = account
    ? [`${copy.label}: ${accountValue}`, account.holderName ? `Titular: ${account.holderName}` : '',
      account.institution ? `Banco: ${account.institution}` : ''].filter(Boolean).join('\n')
    : '';

  const capabilityLine = account?.receiveThirdParty === 'enabled'
    ? 'Puedes recibir de cualquier persona o empresa.'
    : account?.receiveSameName === 'enabled'
      ? 'Por ahora recibe solo desde cuentas a tu nombre.'
      : 'Los depósitos aún no están disponibles en esta cuenta. Contacta a soporte antes de recibir un pago.';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFieldDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
          <RampHero
            eyebrow="Recibir"
            title={copy.hero}
            subtitle={`Recibe ${currency} por ${copy.rail}. Los ingresos aprobados se convierten automáticamente a dólares.`}
            onBack={() => navigation.goBack()}
            onHistory={() => navigation.navigate('RampHistory', { initialFilter: 'on_ramp' })}
            historyLabel="Ver historial de ingresos"
            compact={isCompact}
          />
        </RampReveal>

        {!account && (accountQuery.loading || accountRetrying) ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : !account ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>No pudimos cargar tu cuenta local.</Text>
            <TouchableOpacity onPress={() => {
              setAccountRetrying(true);
              accountQuery.refetch().catch(() => {}).finally(() => {
                if (aliveRef.current) setAccountRetrying(false);
              });
            }}>
              <Text style={styles.warningLink}>Intentar de nuevo</Text>
            </TouchableOpacity>
          </View>
        ) : !active && receiveMethod?.status === 'needs_document' ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="file-text" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Necesitamos otro documento</Text>
            <Text style={styles.emptyStateText}>
              Para abrir {copy.label.replace('Tu ', 'tu ')} en {place} necesitamos un documento distinto al que ya
              verificaste. Tu verificación actual no cambia.
            </Text>
            <TouchableOpacity style={styles.primaryActionButton} onPress={() => navigation.navigate('AdditionalDocument', {
              idCountry: receiveMethod.documentCountry, documentTypes: receiveMethod.documentTypes,
              reason: `Para recibir en ${place} necesitamos un documento distinto al que ya verificaste.`,
            })}>
              <Text style={styles.primaryActionButtonText}>Verificar documento</Text>
            </TouchableOpacity>
          </View>
        ) : account.status === 'active' && !accountValue && brebKeyScreen ? (
          <View style={styles.emptyStateCard}>
            <View style={styles.emptyStateIconWrap}>
              <Icon name="map-pin" size={22} color={colors.primaryDark} />
            </View>
            <Text style={styles.emptyStateTitle}>Confirma tu ubicación</Text>
            <Text style={styles.emptyStateText}>Para ver tu llave Bre-B confirmamos que está disponible donde estás.</Text>
            <TouchableOpacity style={styles.primaryActionButton} onPress={revealKey}>
              <Text style={styles.primaryActionButtonText}>Confirmar y ver mi llave</Text>
            </TouchableOpacity>
          </View>
        ) : !active ? (
          <RampReveal delay={80}>
            <View style={styles.section}>
              <Text style={styles.savedTitle}>{`Activa ${copy.label.replace('Tu ', 'tu ')}`}</Text>
              <FlagLabel iso={account.country} style={flagStyles.detailMetaRow} textStyle={[styles.detailMeta, flagStyles.flush]}>
                {`${place} · ${account.asset}`}
              </FlagLabel>
              <View style={styles.inputCard}>
                {account.status === 'provisioning' ? (
                  <View style={styles.emptyQuote}>
                    <ActivityIndicator color={colors.primary} />
                    <Text style={styles.emptyText}>
                      Estamos creando {copy.label.replace('Tu ', 'tu ')}. Normalmente tarda unos minutos. Puedes volver aquí para continuar.
                    </Text>
                  </View>
                ) : (
                  <>
                    {[
                      ['repeat', 'Siempre la misma', 'Compártela las veces que quieras.'],
                      ['zap', `Llega por ${copy.rail}`, 'Desde cualquier banco o billetera, normalmente en minutos.'],
                      ['dollar-sign', 'Conversión automática', 'Los depósitos aprobados se convierten y se envían a tu billetera automáticamente. Abre Confío para completar la conversión a Confío Dollar.'],
                    ].map(([icon, title, body]) => (
                      <View key={title} style={[styles.reviewRow, { alignItems: 'center' }]}>
                        <View style={styles.methodIcon}>
                          <Icon name={icon} size={18} color={colors.primary} />
                        </View>
                        <View style={styles.methodCopy}>
                          <Text style={styles.methodTitle}>{title}</Text>
                          <Text style={styles.methodText}>{body}</Text>
                        </View>
                      </View>
                    ))}
                  </>
                )}
              </View>
            </View>
            {account.status === 'none' || account.status === 'provisioning' || account.status === 'awaiting_payment' ? (
              <RampActionBar
                primaryLabel={account.status === 'awaiting_payment' ? 'Completar apertura'
                  : account.status === 'provisioning' ? 'Ver el estado de la apertura'
                    : `Solicitar ${copy.label.replace('Tu ', 'mi ')}`}
                onPrimaryPress={() => navigation.navigate('LocalAccountApplication', { methodId })}
                primaryIconName="chevron-right"
              />
            ) : (
              <Text style={[styles.errorText, { marginHorizontal: 22 }]}>
                Tu cuenta local no está disponible. Escríbenos a soporte.
              </Text>
            )}
          </RampReveal>
        ) : (
          <>
            {/* Receiving details */}
            <RampReveal delay={80}>
              <View style={styles.section}>
                <Text style={styles.savedTitle}>Tus datos para recibir</Text>
                <FlagLabel iso={account.country} style={flagStyles.detailMetaRow} textStyle={[styles.detailMeta, flagStyles.flush]}>
                  {`${place} · ${account.asset}`}
                </FlagLabel>
                <View style={styles.inputCard}>
                  <Text style={styles.inputLabel}>{copy.label}</Text>
                  {isPixQr ? (
                    <View style={{ alignItems: 'center', padding: 16, backgroundColor: '#fff' }}>
                      <QRCode value={accountValue} size={Math.min(220, width - 112)} />
                      <Text style={[styles.detailMeta, { marginTop: 12 }]}>
                        Escanea este QR o pega el código en Pix Copia e Cola en tu banco o billetera.
                      </Text>
                    </View>
                  ) : null}
                  {methodId === 'co_breb_receive' && account.qrValue ? (
                    <View style={{ alignItems: 'center', padding: 16, backgroundColor: '#fff' }}>
                      <QRCode value={account.qrValue} size={Math.min(220, width - 112)} />
                      <Text style={[styles.detailMeta, { marginTop: 12 }]}>Escanea este QR para pagar a tu llave Bre-B.</Text>
                      <TouchableOpacity style={styles.smallGhost}
                        onPress={() => Share.share({message: account.qrValue!})}>
                        <Text style={styles.smallGhostText}>Compartir código QR</Text>
                      </TouchableOpacity>
                    </View>
                  ) : null}
                  <Text style={styles.detailValue} selectable>{accountValue}</Text>
                  {account.holderName ? <Text style={styles.detailMeta}>Titular: {account.holderName}</Text> : null}
                  {account.institution ? <Text style={styles.detailMeta}>Banco: {account.institution}</Text> : null}
                  <View style={styles.buttonRow}>
                    <TouchableOpacity style={styles.smallPrimary} onPress={() => {
                      Clipboard.setString(accountValue);
                      Alert.alert('Copiado', isPixQr ? 'Tu código Pix se copió. Pégalo en Pix Copia e Cola.'
                        : `${copy.label} se copió. Compártela con quien te va a pagar.`);
                    }}>
                      <Icon name="copy" size={16} color={colors.white} />
                      <Text style={styles.smallPrimaryText}>Copiar</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.smallGhost} onPress={() => Share.share({ message: shareMessage })}>
                      <Icon name="share-2" size={16} color={colors.successText} />
                      <Text style={styles.smallGhostText}>Compartir</Text>
                    </TouchableOpacity>
                  </View>
                  <View style={[styles.reviewRow, { marginTop: 8 }]}>
                    <Icon name="user-check" size={16} color={colors.textSecondary} />
                    <Text style={[styles.limitText, { marginTop: 0, flex: 1 }]}>{capabilityLine}</Text>
                  </View>
                  {limits?.known && limits.limit && limits.used ? (
                    <>
                      <Text style={styles.limitText}>
                        Este mes: {formatRampMoney(limits.used, USD_UNIT)} de {formatRampMoney(limits.limit, USD_UNIT)}
                      </Text>
                      <View style={styles.progressTrack}>
                        <View style={[styles.progressFill, {
                          width: `${Math.min(100, (Number(limits.used) / Math.max(Number(limits.limit), 1)) * 100)}%`,
                        }]} />
                      </View>
                      {limits.nearLimit ? (
                        <TouchableOpacity onPress={() => navigation.navigate('LocalLimitIncrease')}>
                          <Text style={[styles.historyPillText, { marginTop: 10 }]}>Aumentar mi límite mensual</Text>
                        </TouchableOpacity>
                      ) : null}
                    </>
                  ) : null}
                </View>
              </View>
            </RampReveal>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// detailMeta's top margin moves to the flag row so the flag centers on the text.
const flagStyles = StyleSheet.create({
  detailMetaRow: { marginTop: 6 },
  flush: { marginTop: 0 },
});
