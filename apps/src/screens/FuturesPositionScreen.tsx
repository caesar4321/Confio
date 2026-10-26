// Una posición — the member's money, live: P&L, how far it is from being
// liquidated, what it has paid or earned in funding, and what to do next.
// A position stopped between steps (money in transit, an order to sign, a
// return to confirm) shows that one next step, so nothing is ever stuck.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, StatusBar, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { SuccessHero } from '../components/common/SuccessHero';
import { ReceiptCard } from '../components/common/ReceiptCard';
import { StockTradeSuccessContent } from '../components/common/StockTradeSuccessContent';
import { AreaChart } from '../components/futures/AreaChart';
import { FuturesProgress, ProgressKind } from '../components/futures/FuturesProgress';
import { LiquidationGauge } from '../components/futures/LiquidationGauge';
import { PerpMarketMark } from '../components/futures/PerpMarketMark';
import { colors } from '../config/theme';
import { usePerpsCandles, usePerpsCapabilities, usePerpsMarkets, usePerpsPositions } from '../hooks/usePerps';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { requestActivityShare } from '../services/communityShare';
import {
  PerpPosition,
  PerpsStep,
  addMargin,
  bringHome,
  closePosition,
  perpsErrorCopy,
  releaseRefund,
  resumePosition,
  setTpSl,
} from '../services/perps';
import { MainStackParamList } from '../types/navigation';
import { confirmDeepClose, confirmImpact, confirmReturnAmount } from '../components/futures/confirmImpact';
import { parseAmountInput, sanitizeAmountInput, toAmountInput } from '../utils/numberLocale';
import {
  DOWN,
  SIDE_COLORS,
  UP,
  formatPctSigned,
  formatPerpPrice,
  formatUsd,
  formatUsdSigned,
  pnlColor,
  sideLabel,
  stepLabel,
  positionValueUsd,
} from '../utils/perpsPresentation';

type Nav = NativeStackNavigationProp<MainStackParamList>;
type R = RouteProp<MainStackParamList, 'FuturesPosition'>;

export const FuturesPositionScreen = () => {
  const navigation = useNavigation<Nav>();
  const { positionId } = useRoute<R>().params;
  const { capabilities } = usePerpsCapabilities();
  const { positions, refetch } = usePerpsPositions(true, { includeDone: true, pollMs: 6_000 });
  const position = (positions ?? []).find((p) => p.id === String(positionId)) ?? null;
  const { byCoin } = usePerpsMarkets(Boolean(capabilities?.enabled));
  const market = position ? byCoin(position.coin) : undefined;
  const { closes } = usePerpsCandles(position?.coin, '1D');
  const { refetch: refetchBalances } = useSavingsPortfolio();
  const [busy, setBusy] = useState<ProgressKind | null>(null);
  const [step, setStep] = useState<PerpsStep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<'margin' | 'tpsl' | null>(null);
  const [finished, setFinished] = useState<PerpPosition | null>(null);

  useFocusEffect(useCallback(() => { refetch().catch(() => {}); }, [refetch]));

  const running = useRef(false);
  const run = async (kind: ProgressKind, work: () => Promise<unknown>) => {
    // A second tap while a flow runs is ignored (state updates are not synchronous).
    if (running.current) return;
    running.current = true;
    setError(null);
    setBusy(kind);
    setStep(null);
    try {
      const result: any = await work();
      await refetch().catch(() => {});
      void refetchBalances?.();
      if (result?.position?.state === 'done') {
        setFinished(result.position);
        if (result.txHash) setTimeout(() => requestActivityShare({ group: 'perps', reference: result.txHash }), 900);
      }
    } catch (e) {
      setError(perpsErrorCopy(e));
      await refetch().catch(() => {});
    } finally {
      running.current = false;
      setBusy(null);
    }
  };

  if (finished) {
    const result = finished.resultUsd;
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title="Ya está en tus dólares"
            amount={formatUsd(finished.returnedUsd)}
            hint={result != null ? `Resultado de la posición: ${formatUsdSigned(result)} con todos los costos.` : undefined}
            icon={<PerpMarketMark ticker={finished.ticker} size={72} />}
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: 'Posición', value: `${finished.ticker} · ${sideLabel(finished.side)} ${finished.leverage}x` },
              { label: 'Pusiste', value: formatUsd(finished.putInUsd ?? finished.marginUsd) },
              { label: 'Volvió a tus dólares', value: formatUsd(finished.returnedUsd), color: colors.primaryDark },
              { label: 'Resultado', value: formatUsdSigned(result), color: pnlColor(result) },
              { label: 'Estado', value: 'Cerrada', color: colors.success, icon: 'check-circle' },
            ]}
          />
          <Pressable style={styles.successCta} onPress={() => navigation.goBack()}>
            <Text style={styles.successCtaText}>Listo</Text>
          </Pressable>
        </StockTradeSuccessContent>
      </View>
    );
  }

  if (!position) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.muted}>{positions === null ? 'Cargando tu posición…' : 'No encontramos esta posición.'}</Text>
      </View>
    );
  }

  const side = SIDE_COLORS[position.side];
  const pnl = position.unrealizedPnlUsd;
  const roe = position.returnOnEquity != null ? position.returnOnEquity * 100 : null;
  const pending = stepLabel(position.nextAction, position.state);
  const isOpen = position.state === 'open';
  const done = position.state === 'done';
  const markPx = position.markPx ?? market?.markPx ?? null;
  const chartUp = closes.length >= 2 ? closes[closes.length - 1] >= closes[0] : true;

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title={`${position.ticker} · ${sideLabel(position.side)} ${position.leverage}x`}
        subtitle={position.name}
        titleAccessory={<PerpMarketMark ticker={position.ticker} size={28} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
      />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <View style={[styles.hero, { borderColor: side.solid }]}>
          <View style={styles.heroTop}>
            <View style={[styles.sideTag, { backgroundColor: side.soft }]}>
              <Icon name={position.side === 'long' ? 'trending-up' : 'trending-down'} size={14} color={side.text} />
              <Text style={[styles.sideTagText, { color: side.text }]}>{sideLabel(position.side)} {position.leverage}x</Text>
            </View>
            <Text style={styles.heroState}>{done ? 'Cerrada' : isOpen ? 'Abierta' : 'En proceso'}</Text>
          </View>
          {isOpen ? (
            <>
              <Text style={[styles.heroPnl, { color: pnlColor(pnl) }]}>{formatUsdSigned(pnl)}</Text>
              <Text style={[styles.heroRoe, { color: pnlColor(roe) }]}>{formatPctSigned(roe)} sobre tu margen</Text>
            </>
          ) : done ? (
            <>
              <Text style={[styles.heroPnl, { color: pnlColor(position.resultUsd) }]}>{formatUsdSigned(position.resultUsd)}</Text>
              <Text style={styles.heroRoe}>Resultado con todos los costos</Text>
            </>
          ) : (
            <Text style={styles.heroPending}>{pending || 'Procesando…'}</Text>
          )}
          {isOpen && (
            <View style={styles.chart}>
              <AreaChart values={closes} height={110} color={chartUp ? UP : DOWN} emptyText="Cargando gráfico…"
                guides={[
                  ...(position.entryPx ? [{ value: position.entryPx, color: '#64748B', label: 'Entrada', dashed: true }] : []),
                  ...(position.liquidationPx ? [{ value: position.liquidationPx, color: DOWN, label: 'Liquidación', dashed: true }] : []),
                ]} />
            </View>
          )}
        </View>

        {pending && !done && (
          <NextStepCard position={position} label={pending} disabled={Boolean(busy)}
            onContinue={() => run(position.nextAction === 'return' || position.nextAction === 'enter'
              || position.nextAction === 'wait_return' ? 'close' : position.nextAction === 'finish_margin' ? 'margin' : 'resume',
            () => (['return', 'enter', 'wait_return'].includes(position.nextAction)
              ? bringHome(position.id, setStep, confirmReturnAmount, positionValueUsd(position), position.coin)
              : resumePosition(position, setStep, confirmImpact, confirmReturnAmount)))}
            onRelease={position.nextAction === 'retry_bridge' ? () => Alert.alert(
              'Volver a tus dólares',
              'Tus USDT vuelven a tu saldo. Se aplica el 0,9% de entrada, como en cualquier regreso.',
              [{ text: 'Cancelar', style: 'cancel' },
                { text: 'Volver a dólares', onPress: () => run('resume', () => releaseRefund(position.id)) }],
            ) : position.nextAction === 'open_order' ? () => Alert.alert(
              'Traer tu dinero de vuelta',
              'Tu margen vuelve de Hyperliquid a tus dólares sin abrir la posición. Se aplican el costo de la transferencia y el 0,9% de entrada.',
              [{ text: 'Cancelar', style: 'cancel' },
                { text: 'Traer de vuelta', onPress: () => run('close', () => bringHome(position.id, setStep, confirmReturnAmount, positionValueUsd(position), position.coin)) }],
            ) : undefined}
          />
        )}

        {isOpen && (
          <View style={styles.card}>
            <LiquidationGauge side={position.side} entryPx={position.entryPx} markPx={markPx}
              liquidationPx={position.liquidationPx} />
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Detalles</Text>
          <Row label="Precio de entrada" value={formatPerpPrice(position.entryPx)} />
          <Row label="Precio actual" value={formatPerpPrice(markPx)} />
          {isOpen && <Row label="Tamaño" value={`${position.size != null ? Math.abs(position.size) : '—'} ${position.ticker}`} />}
          {isOpen && <Row label="Valor de la posición" value={formatUsd(position.positionValueUsd)} />}
          <Row label="Tu margen" value={formatUsd(isOpen ? position.marginUsedUsd : position.marginUsd)} />
          <Row label="Financiamiento" value={formatUsdSigned(position.fundingUsd)} color={pnlColor(position.fundingUsd)} />
          {position.venueFeesUsd != null && <Row label="Comisiones de Hyperliquid" value={formatUsd(position.venueFeesUsd)} />}
          {position.liquidation ? <Row label="Liquidación" value="Hyperliquid cerró la posición" color="#B91C1C" /> : null}
          {done && <Row label="Volvió a tus dólares" value={formatUsd(position.returnedUsd)} />}
        </View>

        {error && <Text style={styles.error}>{error}</Text>}

        {isOpen && (
          <>
            <Pressable style={[styles.primary, { backgroundColor: '#0F172A' }]} disabled={Boolean(busy)}
              onPress={() => Alert.alert(
                `Cerrar ${position.ticker}`,
                `Cierras al mejor precio del momento y el dinero vuelve a tus dólares (0,9% al entrar). Resultado ahora: ${formatUsdSigned(pnl)}.`,
                [{ text: 'Cancelar', style: 'cancel' },
                  { text: 'Cerrar posición', style: 'destructive', onPress: () => run('close', () => closePosition(position.id, setStep, confirmReturnAmount, positionValueUsd(position), position.coin, confirmDeepClose)) }],
              )}
              testID="perps-close">
              <Text style={styles.primaryText}>Cerrar y traer a mis dólares</Text>
            </Pressable>
            <View style={styles.secondaryRow}>
              <Pressable style={styles.secondary} onPress={() => setSheet('margin')} disabled={Boolean(busy) || !capabilities?.openEnabled}>
                <Icon name="plus-circle" size={18} color={colors.primaryDark} />
                <Text style={styles.secondaryText}>Agregar margen</Text>
              </Pressable>
              <Pressable style={styles.secondary} onPress={() => setSheet('tpsl')} disabled={Boolean(busy)}>
                <Icon name="shield" size={18} color={colors.primaryDark} />
                <Text style={styles.secondaryText}>Proteger</Text>
              </Pressable>
            </View>
          </>
        )}
        <Text style={styles.disclaimer}>
          Tu posición vive en Hyperliquid, en una cuenta a tu nombre. Confío no puede moverla sin tu firma.
        </Text>
      </ScrollView>

      <MarginSheet visible={sheet === 'margin'} onClose={() => setSheet(null)}
        liquidationPx={position.liquidationPx}
        onConfirm={(amount) => { setSheet(null); void run('margin', () => addMargin(position.id, amount, setStep, capabilities?.fundingDollar, position.coin)); }} />
      <TpSlSheet visible={sheet === 'tpsl'} onClose={() => setSheet(null)} position={position} markPx={markPx}
        onConfirm={(tp, sl) => { setSheet(null); void run('resume', () => setTpSl(position.id, tp, sl, position.coin)); }} />
      <FuturesProgress visible={busy !== null} kind={busy ?? 'resume'} current={step}
        title={busy === 'close' ? `Cerrando ${position.ticker}` : busy === 'margin' ? 'Agregando margen' : 'Continuando'} />
    </View>
  );
};

function NextStepCard({ position, label, onContinue, onRelease, disabled }: {
  position: PerpPosition; label: string; onContinue: () => void; onRelease?: () => void; disabled: boolean;
}) {
  const waiting = position.nextAction === 'wait_bridge' || position.nextAction === 'wait_return';
  const cta = {
    retry_bridge: 'Reintentar la transferencia',
    open_order: 'Abrir la posición',
    finish_margin: 'Sumar el margen',
    return: 'Traer a mis dólares',
    enter: 'Confirmar entrada a mis dólares',
  }[position.nextAction as string];
  return (
    <View style={styles.nextCard}>
      <View style={styles.nextHead}>
        <Icon name={waiting ? 'clock' : 'alert-circle'} size={18} color="#92400E" />
        <Text style={styles.nextLabel}>{label}</Text>
      </View>
      <Text style={styles.nextHint}>
        {waiting ? 'Normalmente tarda segundos. Puedes salir: te avisamos cuando termine.'
          : 'Tu dinero está seguro en una cuenta a tu nombre. Falta un paso con tu firma.'}
      </Text>
      {cta && (
        <Pressable style={styles.nextBtn} onPress={onContinue} disabled={disabled}>
          <Text style={styles.nextBtnText}>{cta}</Text>
        </Pressable>
      )}
      {onRelease && (
        <Pressable style={styles.nextLink} onPress={onRelease} disabled={disabled}>
          <Text style={styles.nextLinkText}>
            {position.nextAction === 'open_order' ? 'Prefiero traer mi dinero de vuelta' : 'Prefiero volver a mis dólares'}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

function MarginSheet({ visible, onClose, onConfirm, liquidationPx }: {
  visible: boolean; onClose: () => void; onConfirm: (amount: string) => void; liquidationPx: number | null;
}) {
  const [raw, setRaw] = useState('');
  useEffect(() => { if (!visible) setRaw(''); }, [visible]);
  const amount = parseAmountInput(raw);
  const ok = Number.isFinite(amount) && amount >= 2;
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.grabber} />
        <Text style={styles.sheetTitle}>Agregar margen</Text>
        <Text style={styles.sheetSub}>
          Más margen aleja tu precio de liquidación{liquidationPx ? ` (hoy ${formatPerpPrice(liquidationPx)})` : ''}. Sale de tus dólares con el 0,9% de siempre.
        </Text>
        <View style={styles.sheetAmount}>
          <Text style={styles.currency}>$</Text>
          <TextInput style={styles.sheetInput} value={raw} keyboardType="decimal-pad" placeholder="0.00"
            placeholderTextColor={colors.text.light} autoFocus
            onChangeText={(v) => setRaw((prev) => sanitizeAmountInput(v, 2, undefined, prev))} />
        </View>
        <Pressable style={[styles.primary, !ok && styles.disabled]} disabled={!ok} onPress={() => onConfirm(amount.toFixed(2))}>
          <Text style={styles.primaryText}>Agregar {ok ? formatUsd(amount) : ''}</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

function TpSlSheet({ visible, onClose, onConfirm, position, markPx }: {
  visible: boolean; onClose: () => void; onConfirm: (tp: string | null, sl: string | null) => void;
  position: PerpPosition; markPx: number | null;
}) {
  // Opens on the live protection (saving replaces it); typed in the viewer's own decimal format.
  const shown = (n: number | null) => (n != null && n > 0 ? toAmountInput(n, 8) : '');
  const [tp, setTp] = useState('');
  const [sl, setSl] = useState('');
  // Filled from KNOWN protection before saving is possible: a stop that was
  // unreadable when the sheet opened is never replaced by an empty field.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!visible) { setReady(false); return; }
    if (position.protectionKnown === true && !ready) {
      setTp(shown(position.takeProfitPx));
      setSl(shown(position.stopLossPx));
      setReady(true);
    }
  }, [visible, position.protectionKnown]); // eslint-disable-line react-hooks/exhaustive-deps
  const long = position.side === 'long';
  const entry = position.entryPx ?? markPx ?? 0;
  const presets = useMemo(() => [5, 10, 25].map((pct) => ({
    pct,
    tp: entry * (1 + (long ? pct : -pct) / 100),
    sl: entry * (1 - (long ? pct : -pct) / 100),
  })), [entry, long]);
  const tpN = parseAmountInput(tp);
  const slN = parseAmountInput(sl);
  const fix = (n: number) => toAmountInput(Number(n >= 1 ? n.toFixed(2) : n.toPrecision(5)), 8);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.grabber} />
        <Text style={styles.sheetTitle}>Proteger tu posición</Text>
        <Text style={styles.sheetSub}>
          Hyperliquid cierra sola tu posición si el precio llega a uno de estos niveles, aunque no tengas la app abierta.
        </Text>
        <Text style={styles.fieldLabel}>Tomar ganancia en</Text>
        <TextInput style={styles.field} value={tp} onChangeText={(v) => setTp((prev) => sanitizeAmountInput(v, 8, undefined, prev))} keyboardType="decimal-pad"
          placeholder={long ? 'Precio mayor a la entrada' : 'Precio menor a la entrada'} placeholderTextColor={colors.text.light} />
        <View style={styles.presetRow}>
          {presets.map((p) => (
            <Pressable key={`tp${p.pct}`} style={styles.preset} onPress={() => setTp(fix(p.tp))}>
              <Text style={[styles.presetText, { color: '#047857' }]}>+{p.pct}%</Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.fieldLabel}>Limitar pérdida en</Text>
        <TextInput style={styles.field} value={sl} onChangeText={(v) => setSl((prev) => sanitizeAmountInput(v, 8, undefined, prev))} keyboardType="decimal-pad"
          placeholder={long ? 'Precio menor a la entrada' : 'Precio mayor a la entrada'} placeholderTextColor={colors.text.light} />
        <View style={styles.presetRow}>
          {presets.map((p) => (
            <Pressable key={`sl${p.pct}`} style={styles.preset} onPress={() => setSl(fix(p.sl))}>
              <Text style={[styles.presetText, { color: '#B91C1C' }]}>−{p.pct}%</Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.sheetSub}>Entrada: {formatPerpPrice(position.entryPx)} · Liquidación: {formatPerpPrice(position.liquidationPx)}</Text>
        {/* Saving replaces the live protection: only once it is known (never over an unseen stop). */}
        {!ready && (
          <Text style={[styles.sheetSub, { color: '#B45309' }]}>
            No pudimos leer tu protección actual en Hyperliquid. Cierra y vuelve a abrir en un momento.
          </Text>
        )}
        <Pressable style={[styles.primary, (!(Number.isFinite(tpN) || Number.isFinite(slN)) || !ready
          || position.protectionKnown !== true) && styles.disabled]}
          disabled={!(Number.isFinite(tpN) || Number.isFinite(slN)) || !ready || position.protectionKnown !== true}
          onPress={() => onConfirm(Number.isFinite(tpN) ? String(tpN) : null, Number.isFinite(slN) ? String(slN) : null)}>
          <Text style={styles.primaryText}>Guardar protección</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  // A success screen centers its column: the CTA carries its own width, like the Oro y Bitcoin twin.
  successCta: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 15, paddingHorizontal: 40, marginTop: 32 },
  successCtaText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  container: { flex: 1, backgroundColor: colors.neutral },
  center: { alignItems: 'center', justifyContent: 'center', padding: 32 },
  muted: { color: colors.text.secondary, textAlign: 'center' },
  scroll: { padding: 16, paddingBottom: 40 },
  hero: { backgroundColor: '#FFFFFF', borderRadius: 22, padding: 18, marginBottom: 14, borderWidth: 1.5 },
  heroTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sideTag: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  sideTagText: { fontSize: 12, fontWeight: '800' },
  heroState: { fontSize: 12, fontWeight: '700', color: colors.text.light },
  heroPnl: { fontSize: 36, fontWeight: '800', marginTop: 12 },
  heroRoe: { fontSize: 14, fontWeight: '700', color: colors.text.secondary, marginTop: 2 },
  heroPending: { fontSize: 18, fontWeight: '800', color: colors.text.primary, marginTop: 12 },
  chart: { marginTop: 12 },
  nextCard: { backgroundColor: '#FFFBEB', borderRadius: 18, padding: 16, marginBottom: 14, borderWidth: 1, borderColor: '#FDE68A' },
  nextHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  nextLabel: { flex: 1, fontSize: 15, fontWeight: '800', color: '#78350F' },
  nextHint: { fontSize: 13, lineHeight: 18, color: '#92400E', marginTop: 6 },
  nextBtn: { backgroundColor: '#0F172A', borderRadius: 14, paddingVertical: 14, alignItems: 'center', marginTop: 12 },
  nextBtnText: { color: '#FFFFFF', fontSize: 15, fontWeight: '800' },
  nextLink: { alignItems: 'center', paddingVertical: 12 },
  nextLinkText: { fontSize: 13, fontWeight: '700', color: '#92400E' },
  card: { backgroundColor: '#FFFFFF', borderRadius: 20, padding: 16, marginBottom: 14 },
  sectionLabel: { fontSize: 13, fontWeight: '800', color: colors.text.secondary, marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 7, gap: 12 },
  rowLabel: { fontSize: 13, color: colors.text.secondary },
  rowValue: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  error: { fontSize: 13, color: '#DC2626', marginBottom: 12, marginHorizontal: 4, lineHeight: 18 },
  primary: { borderRadius: 16, paddingVertical: 16, alignItems: 'center', backgroundColor: colors.primary, marginTop: 4 },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  disabled: { opacity: 0.45 },
  secondaryRow: { flexDirection: 'row', gap: 10, marginTop: 10, marginBottom: 14 },
  secondary: { flex: 1, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF',
    borderRadius: 14, paddingVertical: 14, borderWidth: 1.5, borderColor: colors.primaryDark },
  secondaryText: { fontSize: 14, fontWeight: '800', color: colors.primaryDark },
  disclaimer: { fontSize: 11, lineHeight: 16, color: colors.text.light, textAlign: 'center', marginTop: 6 },
  backdrop: { flex: 1, backgroundColor: 'rgba(15,23,42,0.45)' },
  sheet: { backgroundColor: '#FFFFFF', borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: 20, paddingBottom: 34 },
  grabber: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: '#E5E7EB', marginBottom: 14 },
  sheetTitle: { fontSize: 20, fontWeight: '800', color: colors.text.primary },
  sheetSub: { fontSize: 13, lineHeight: 18, color: colors.text.secondary, marginTop: 6, marginBottom: 12 },
  sheetAmount: { flexDirection: 'row', alignItems: 'center', marginBottom: 16 },
  currency: { fontSize: 30, fontWeight: '700', color: colors.text.primary, marginRight: 4 },
  sheetInput: { flex: 1, fontSize: 34, fontWeight: '800', color: colors.text.primary, padding: 0 },
  fieldLabel: { fontSize: 13, fontWeight: '800', color: colors.text.secondary, marginTop: 4 },
  field: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 16, color: colors.text.primary, marginTop: 6 },
  presetRow: { flexDirection: 'row', gap: 8, marginTop: 8, marginBottom: 10 },
  preset: { paddingHorizontal: 12, minHeight: 32, justifyContent: 'center', borderRadius: 16, backgroundColor: '#F3F4F6' },
  presetText: { fontSize: 13, fontWeight: '800' },
});
