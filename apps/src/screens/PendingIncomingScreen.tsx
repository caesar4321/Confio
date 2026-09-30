/**
 * Money waiting for Confío Face (docs/plans/infinia-payin-face-hold.md).
 *
 * A bank transfer to a personal account lands in the person's Infinia account
 * and reaches their Confío balance only after they confirm with their face.
 * Unconfirmed after 24h it goes back to the payer. One confirmation receives
 * everything waiting.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, RefreshControl, SafeAreaView, ScrollView, StatusBar, Text, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { formatRampMoney } from '../utils/rampFormat';
import {
  fetchPendingIncoming,
  isAwaiting,
  PendingIncomingPayin,
  releasePendingIncoming,
  timeLeft,
} from '../services/pendingIncoming';

type Nav = NativeStackNavigationProp<MainStackParamList, 'PendingIncoming'>;

const RETURN_WINDOW_MS = 24 * 3600 * 1000;

/** Sum per currency: a person can hold pay-ins in more than one. */
const totals = (items: PendingIncomingPayin[]) => {
  const byAsset = new Map<string, number>();
  for (const item of items) byAsset.set(item.asset, (byAsset.get(item.asset) || 0) + Number(item.amount || 0));
  return [...byAsset.entries()].map(([asset, amount]) => formatRampMoney(amount, asset)).join(' + ');
};

export default function PendingIncomingScreen() {
  const navigation = useNavigation<Nav>();
  const [items, setItems] = useState<PendingIncomingPayin[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [now, setNow] = useState(Date.now());

  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    const { items: next } = await fetchPendingIncoming();
    // A failed load keeps what was shown: hiding money that is on a 24h clock
    // would be worse than showing it a minute stale.
    setLoadFailed(next === null);
    if (next !== null) setItems(next);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // The countdown is the point of this screen: keep it honest.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const waiting = useMemo(() => (items || []).filter(isAwaiting), [items]);
  const inFlight = useMemo(
    () => (items || []).filter(i => i.state === 'releasing' || i.state === 'returning' || i.state === 'review'),
    [items],
  );
  const returned = useMemo(() => (items || []).filter(i => i.state === 'returned' || i.state === 'return_failed'), [items]);

  const receive = async () => {
    setReleasing(true);
    const outcome = await releasePendingIncoming();
    setReleasing(false);
    if (outcome.kind === 'declined') return;
    if (outcome.kind === 'error') {
      Alert.alert('No pudimos recibir tu dinero', outcome.message);
      await load();
      return;
    }
    const firstJourney = outcome.released.find(r => r.journeyId)?.journeyId;
    if (outcome.released.length === 1 && firstJourney) {
      navigation.replace('LocalTransferStatus', { journeyId: firstJourney });
      return;
    }
    await load();
    Alert.alert('¡Listo!', 'Estamos pasando tu dinero a tu saldo Confío. Te avisaremos cuando llegue.');
  };

  const heroTitle = waiting.length ? totals(waiting) : 'Nada por recibir';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
          setRefreshing(true); await load(); setRefreshing(false);
        }} />}
      >
        <RampHero
          eyebrow="Por recibir"
          title={heroTitle}
          subtitle={waiting.length
            ? 'Confírmalo con tu rostro para recibirlo en tu saldo Confío.'
            : 'Cuando te envíen dinero por transferencia bancaria, aparecerá aquí.'}
          onBack={() => navigation.goBack()}
        />

        {items === null && !loadFailed ? (
          <View style={styles.loadingCard}><Text style={styles.loadingText}>Cargando…</Text></View>
        ) : null}
        {loadFailed ? (
          <View style={styles.warningCard}>
            <Text style={styles.warningTitle}>No pudimos actualizar</Text>
            <Text style={styles.warningText}>Revisa tu conexión y desliza hacia abajo para reintentar.</Text>
          </View>
        ) : null}

        {waiting.map(item => {
          const remaining = Math.max(0, Date.parse(item.returnsAt) - now);
          const share = Math.min(1, remaining / RETURN_WINDOW_MS);
          return (
            <View key={item.id} style={styles.reviewCard}>
              <View style={styles.reviewRow}>
                <Text style={styles.reviewLabel}>{item.payerName ? `De ${item.payerName}` : 'Transferencia bancaria'}</Text>
                <Text style={styles.reviewValueHighlight}>{formatRampMoney(item.amount, item.asset)}</Text>
              </View>
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, { width: `${share * 100}%` }]} />
              </View>
              <Text style={styles.detailMeta}>
                Si no lo confirmas, se devuelve al remitente en {timeLeft(item.returnsAt, now)}.
              </Text>
            </View>
          );
        })}

        {inFlight.map(item => (
          <TouchableOpacity
            key={item.id}
            style={styles.reviewCard}
            disabled={!item.journeyId}
            activeOpacity={0.8}
            onPress={() => item.journeyId && navigation.navigate('LocalTransferStatus', { journeyId: item.journeyId })}
          >
            <View style={styles.reviewRow}>
              <Text style={styles.reviewLabel}>
                {item.state === 'releasing' ? 'Pasando a tu saldo'
                  : item.state === 'returning' ? 'Devolviendo al remitente'
                    : 'Lo estamos revisando'}
              </Text>
              <Text style={styles.reviewValue}>{formatRampMoney(item.amount, item.asset)}</Text>
            </View>
          </TouchableOpacity>
        ))}

        {waiting.length > 0 && (
          <View style={styles.bannerCard}>
            <View style={styles.bannerIconWrap}><Icon name="shield" size={18} color={colors.primaryDark} /></View>
            <View style={styles.bannerCopy}>
              <Text style={styles.bannerTitle}>Solo tú recibes tu dinero</Text>
              <Text style={styles.bannerText}>
                El dinero que te envían por transferencia llega a tu saldo cuando confirmas con tu
                rostro que eres tú. Una sola confirmación recibe todo lo pendiente. Si no lo
                confirmas en 24 horas, lo devolvemos automáticamente a quien lo envió.
              </Text>
            </View>
          </View>
        )}

        {returned.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.reviewTitle}>Devoluciones</Text>
            {returned.map(item => (
              <View key={item.id} style={styles.reviewCard}>
                <View style={styles.reviewRow}>
                  <Text style={styles.reviewLabel}>
                    {item.state === 'return_failed' ? 'Devolución pendiente'
                      : item.payerName ? `Devuelto a ${item.payerName}` : 'Devuelto al remitente'}
                  </Text>
                  <Text style={styles.reviewValue}>
                    {formatRampMoney(item.returnAmount ?? item.amount, item.asset)}
                  </Text>
                </View>
                {item.state === 'return_failed' ? (
                  <Text style={styles.detailMeta}>No pudimos completar la devolución. Lo estamos resolviendo.</Text>
                ) : Number(item.returnDeduction || 0) > 0 ? (
                  <Text style={styles.detailMeta}>
                    Recibido {formatRampMoney(item.amount, item.asset)}; se descontaron{' '}
                    {formatRampMoney(item.returnDeduction, item.asset)} de costos de devolución.
                  </Text>
                ) : null}
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      {waiting.length > 0 && (
        <RampActionBar
          primaryLabel="Confirmar con mi rostro"
          primaryIconName="smile"
          primaryLoading={releasing}
          primaryDisabled={releasing}
          onPrimaryPress={receive}
        />
      )}
    </SafeAreaView>
  );
}
