// The card a stock or ETF is bought or sold from, right in the conversation.
//
// It shows what the person asked for (the server read it from their own
// words), about how much they get and the fee, and an Approve button. The
// trade itself is the stock screens' own: the same binding quote, the same
// 1% price guard, the wallet's own signature (services/ondoStocks). Nothing
// is sent before the tap.
//
// A card trades once. The request it signs is handed out by the server, one
// at a time per card (assistant/trades.py): a second open copy of the chat,
// or another phone, gets none while one is out or once a trade is on record.
// After a send whose end this phone did not see, the server's record says
// how it ended; the card never guesses.
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import { STOCKS_TRADING_UI_ENABLED } from '../config/features';
import { useGmComplexProducts, useGmMarket } from '../hooks/useGmMarket';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { useStockFeePolicy } from '../hooks/useStockFeePolicy';
import { navigationRef } from '../navigation/RootNavigation';
import { requestActivityShare } from '../services/communityShare';
import { isOutcomeUnknown } from '../services/evmWallet';
import {
  buyStockWithSavings, friendlyTradeError, getSoftStockQuote, isComplexProductAckRequired, sellStockToSavings,
  SELL_NET_MIN_WEI,
} from '../services/ondoStocks';
import { feePercent, sellFee } from '../services/stockFeeMath';
import { formatDecimal, parseAmountInput, toAmountInput } from '../utils/numberLocale';
import { CLAIM_STOCK_TRADE, GET_MESSAGE_STOCK_TRADE, RELEASE_STOCK_TRADE, type TradeAction } from './stockTrade';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';
const MIN_BUY_USD = 1.01;   // as BuyStockScreen
const MIN_SELL_USD = 1;     // as SellStockScreen
// A request the server handed out stays out for 11 minutes at most.
const WATCH_MS = 12 * 60 * 1000;
const WATCH_EVERY_MS = 6000;

const usd = (value: number) => `US$${formatDecimal(value, { decimals: 2 })}`;

type Stage =
  | { key: 'review' }
  | { key: 'working' }
  | { key: 'done'; line: string; txHash: string }
  | { key: 'unknown' }      // sent, and the phone did not see how it ended
  | { key: 'dismissed' };

export function StockTradeCard({ messageId, action, onLeave }: {
  messageId: string;
  action: TradeAction;
  /** In the floating box: closes it before a screen or the share sheet opens. */
  onLeave?: () => void;
}) {
  const buy = action.side === 'buy';
  const client = useApolloClient();
  const { savings, stocks, refetch, loading: portfolioLoading } = useSavingsPortfolio();
  const { byTicker, tradabilityFor, loading: marketLoading } = useGmMarket(stocks.enabled);
  const complex = useGmComplexProducts(stocks.enabled);
  const feePolicy = useStockFeePolicy();
  const stock = byTicker(action.ticker);
  const position = stocks.positions.find((p) => p.ticker === action.ticker);

  const [stage, setStage] = useState<Stage>({ key: 'review' });
  const stageRef = useRef(stage);
  stageRef.current = stage;
  const [error, setError] = useState('');             // why the last try sent nothing
  const [quoteError, setQuoteError] = useState('');   // the price could not be read
  const [softWei, setSoftWei] = useState(0n);         // buy: tokens; sell: net dollars
  const [quoting, setQuoting] = useState(false);
  const [quoteRound, setQuoteRound] = useState(0);
  const [watchOver, setWatchOver] = useState(false);
  const approving = useRef(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  // Where this card stands on the server (after a reload, in the other open
  // copy of the chat, on another phone).
  const { data, error: statusError, refetch: recheck } = useQuery(GET_MESSAGE_STOCK_TRADE, {
    variables: { messageId },
    fetchPolicy: 'network-only',
  });
  const served: string | undefined = data?.assistantStockTrade?.status;
  const servedTx: string = data?.assistantStockTrade?.txHash || '';

  // A trade on its way is watched until the server says how it ended.
  const watching = (stage.key === 'unknown' || served === 'pending') && stage.key !== 'done';
  const recheckRef = useRef(recheck);
  recheckRef.current = recheck;
  useEffect(() => {
    if (!watching) {
      return undefined;
    }
    setWatchOver(false);
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started > WATCH_MS) {
        clearInterval(timer);
        if (alive.current) setWatchOver(true);
        return;
      }
      recheckRef.current().then((fresh) => {
        // The request this phone sent left no trace and can no longer run.
        if (alive.current && stageRef.current.key === 'unknown' && fresh.data?.assistantStockTrade?.status === 'none') {
          setStage({ key: 'review' });
          setError('No se envió nada. Puedes intentarlo de nuevo.');
          setQuoteRound((n) => n + 1);
        }
      }).catch(() => undefined);
    }, WATCH_EVERY_MS);
    return () => clearInterval(timer);
  }, [watching]);

  // What is sold when they said "all of it": the position as the screen's MAX writes it.
  const held = position?.valueUsd ?? 0;
  const sellAll = !buy && action.amountUsd === null;
  const amount = sellAll ? parseAmountInput(toAmountInput(held)) || 0 : action.amountUsd ?? 0;
  const available = buy ? savings.balanceUsd : held;

  const enabled = STOCKS_TRADING_UI_ENABLED && stocks.enabled && (buy ? stocks.buyEnabled : stocks.tradingEnabled);
  const tradability = stock ? tradabilityFor(stock) : 'closed';
  const needsRiskRead = buy && complex.factorFor(action.ticker) !== undefined && !complex.acknowledged;
  const openForReview = stage.key === 'review' && served === 'none' && enabled && !!stock && !needsRiskRead;
  const tooSmall = amount < (buy ? MIN_BUY_USD : MIN_SELL_USD);
  const tooMuch = amount > available;

  // The quote depends on plain values only (the symbol, the fee), never on
  // an object's identity: a hook handing back a new object must not re-ask.
  const symbol = stock?.symbol;
  const feeKey = feePolicy ? `${feePolicy.mode}:${feePolicy.feeBps}` : '';
  const policyRef = useRef(feePolicy);
  policyRef.current = feePolicy;
  useEffect(() => {
    let cancelled = false;
    const policy = policyRef.current;
    setSoftWei(0n);
    setQuoteError('');
    if (!openForReview || !policy || !symbol || tooSmall || tooMuch || tradability === 'closed') {
      setQuoting(false);
      return undefined;
    }
    setQuoting(true);
    getSoftStockQuote(symbol, action.side, amount)
      .then((q) => {
        if (cancelled) return;
        if (buy) {
          setSoftWei(BigInt(q.tokenAmount));
        } else {
          const gross = (BigInt(q.tokenAmount) * BigInt(q.price)) / 10n ** 18n;
          setSoftWei(gross - sellFee(gross, policy));
        }
      })
      .catch((e) => { if (!cancelled) setQuoteError(e instanceof Error ? e.message : 'No pude leer el precio ahora.'); })
      .finally(() => { if (!cancelled) setQuoting(false); });
    return () => { cancelled = true; };
    // quoteRound: asked again after a price that moved, or on "Actualizar precio".
  }, [openForReview, feeKey, symbol, tooSmall, tooMuch, tradability, action.side, amount, buy, quoteRound]);

  // Right after a trade the share sheet opens by itself, as on the stock
  // screens (Comunidad, WhatsApp, Instagram). Not in the floating chat: iOS
  // shows one modal at a time, so there it is the card's button.
  const offerShare = (txHash: string) => {
    if (!onLeave && txHash) {
      requestActivityShare({ group: 'stock', reference: txHash });
    }
  };

  const approve = async () => {
    if (approving.current || !stock || !feePolicy || softWei <= 0n) {
      return;
    }
    approving.current = true;
    setError('');
    setStage({ key: 'working' });
    let requestId = '';
    try {
      // The one request this card may sign now; none if it already traded,
      // expired, or another copy of it is at work.
      const claimed = await client.mutate({ mutation: CLAIM_STOCK_TRADE, variables: { messageId }, fetchPolicy: 'no-cache' });
      requestId = claimed.data?.claimAssistantStockTrade?.requestId || '';
      if (!requestId) {
        await recheck().catch(() => undefined);
        if (alive.current) setStage({ key: 'review' });
        return;
      }
      if (buy) {
        const result = await buyStockWithSavings({
          symbol: stock.symbol, grossAmountUsd: amount, minTokenAmountWei: (softWei * 99n) / 100n,
          expectedFeeBps: feePolicy.feeBps, requestId,
        });
        const tokens = formatDecimal(Number(result.tokenAmountWei) / 1e18, { decimals: 4, minDecimals: 0 });
        if (alive.current) setStage({ key: 'done', line: `Listo: compraste ≈ ${tokens} ${stock.ticker}`, txHash: result.txHash });
        offerShare(result.txHash);
      } else {
        const result = await sellStockToSavings({
          symbol: stock.symbol, grossAmountUsd: amount, sellAll, minExpectedNetWei: (softWei * 99n) / 100n,
          expectedFeeBps: feePolicy.feeBps, requestId,
        });
        if (alive.current) {
          setStage({ key: 'done', line: `Listo: ${usd(Number(result.expectedNetWei) / 1e18)} en tu Confío Dollar+`, txHash: result.txHash });
        }
        offerShare(result.txHash);
      }
      void refetch().catch(() => undefined);
    } catch (e) {
      if (!alive.current) {
        return;
      }
      if (!requestId) {
        setStage({ key: 'review' });
        setError('Sin conexión. Inténtalo de nuevo.');
        return;
      }
      if (isOutcomeUnknown(e)) {
        // It was sent: the server's record says how it ended.
        setStage({ key: 'unknown' });
        return;
      }
      // An error is not proof that nothing was sent (a receipt that could
      // not be read, a revert): the server says. It gives the request back
      // only when no trade of it is on record.
      let after = 'pending';
      try {
        const released = await client.mutate({
          mutation: RELEASE_STOCK_TRADE, variables: { messageId, requestId }, fetchPolicy: 'no-cache',
        });
        after = released.data?.releaseAssistantStockTrade?.status || 'pending';
      } catch (_e) {
        after = 'pending';
      }
      await recheck().catch(() => undefined);
      if (!alive.current) {
        return;
      }
      if (after !== 'none') {
        setStage(after === 'pending' ? { key: 'unknown' } : { key: 'review' });
        return;
      }
      setStage({ key: 'review' });
      setError(isComplexProductAckRequired(e)
        ? 'Este fondo pide leer sus riesgos antes de la primera compra. Ábrelo en su pantalla.'
        : friendlyTradeError(e, action.side));
      setQuoteRound((n) => n + 1);
    } finally {
      approving.current = false;
    }
  };

  const leaveThen = (run: () => void) => {
    onLeave?.();
    setTimeout(run, onLeave ? 250 : 0);
  };
  const openStock = () => leaveThen(() => {
    if (navigationRef.isReady()) {
      (navigationRef as any).navigate('StockDetail', { ticker: action.ticker });
    }
  });
  // The same sheet again from the card: for whoever closed it, or comes back later.
  const share = (txHash: string) => leaveThen(() => requestActivityShare({ group: 'stock', reference: txHash,
    again: true }));

  const settled = (icon: string, line: string, tone: 'good' | 'plain' = 'plain', txHash = '') => (
    <View style={styles.card}>
      <View style={styles.settled} accessible accessibilityLabel={line}>
        <Icon name={icon} size={18} color={tone === 'good' ? EMERALD : MUTED} />
        <Text style={[styles.settledText, tone === 'good' && styles.settledGood]}>{line}</Text>
      </View>
      {txHash ? (
        <Pressable onPress={() => share(txHash)} style={({ pressed }) => [styles.share, pressed && styles.sharePressed]}
          accessibilityRole="button" accessibilityLabel="Compartir">
          <Icon name="share-2" size={16} color={EMERALD} />
          <Text style={styles.shareText}>Compartir</Text>
        </Pressable>
      ) : null}
    </View>
  );

  if (stage.key === 'done') return settled('check-circle', stage.line, 'good', stage.txHash);
  if (stage.key === 'dismissed') return settled('x', buy ? 'No se compró nada.' : 'No se vendió nada.');
  if (served === 'done') {
    return settled('check-circle', buy ? 'Listo: esta compra ya se hizo.' : 'Listo: esta venta ya se hizo.', 'good', servedTx);
  }
  if (served === 'failed') {
    return settled('alert-circle', `No se hizo ${buy ? 'la compra' : 'la venta'}. Pídemelo de nuevo si quieres intentarlo.`);
  }
  if (served === 'expired') return settled('clock', 'Esta tarjeta venció. Pídemelo de nuevo.');
  if (served === 'gone') return settled('slash', 'Esta tarjeta ya no está disponible.');
  if (served === 'pending' || stage.key === 'unknown') {
    if (watchOver) {
      return settled('alert-circle',
        `No pude confirmar si ${buy ? 'la compra' : 'la venta'} se hizo. Mira Mis acciones antes de pedirlo de nuevo.`);
    }
    return (
      <View style={[styles.card, styles.settled]} accessible accessibilityLabel="En curso">
        <ActivityIndicator size="small" color={EMERALD} />
        <Text style={styles.settledText}>
          {buy ? 'Tu compra está en curso.' : 'Tu venta está en curso.'} Lo confirmo aquí en un momento.
        </Text>
      </View>
    );
  }
  if (served !== 'none') {
    // Not known yet where this card stands: nothing to approve.
    return statusError
      ? settled('wifi-off', 'No pude comprobar esta tarjeta. Revisa tu conexión y vuelve a abrir el chat.')
      : (
        <View style={[styles.card, styles.settled]}>
          <ActivityIndicator size="small" color={EMERALD} />
          <Text style={styles.settledText}>Preparando…</Text>
        </View>
      );
  }

  // Why it cannot be approved right now, in the person's words ('' = it can).
  const blocked = portfolioLoading || (marketLoading && !stock) ? 'Preparando…'
    : !enabled || !stock ? 'Esta acción no se puede operar desde aquí ahora.'
    : needsRiskRead ? 'Este fondo es apalancado o inverso: antes de la primera compra hay que leer sus riesgos.'
    : tradability === 'closed' ? 'El mercado está cerrado ahora. Pídemelo de nuevo cuando abra.'
    : !buy && !position ? `No tienes ${stock.ticker} para vender.`
    : tooSmall ? `El mínimo es ${usd(buy ? MIN_BUY_USD : MIN_SELL_USD)}.`
    : tooMuch ? (buy ? `No alcanza: tienes ${usd(available)} en tu Confío Dollar+.` : `Tienes ${usd(available)} de ${stock.ticker}.`)
    : !buy && !sellAll && softWei > 0n && softWei < SELL_NET_MIN_WEI ? 'Lo que recibes debe ser al menos US$1,00. Prueba con un monto mayor.'
    : '';
  const feePct = feePolicy ? feePercent(feePolicy) : 0;
  const ready = !blocked && !quoting && softWei > 0n && !!feePolicy;
  const working = stage.key === 'working';

  return (
    <View style={styles.card}>
      <Text style={styles.title}>{action.label}</Text>
      {/* Under the title, what it does not already say: the ticker, or the full name. */}
      {stock ? (
        <Text style={styles.name} numberOfLines={1}>
          {stock.name && !action.label.includes(stock.name) ? stock.name : stock.ticker}
        </Text>
      ) : null}
      {blocked ? <Text style={styles.blocked}>{blocked}</Text> : (
        <View style={styles.rows}>
          <Row label={buy ? 'Pagas' : 'Vendes'} value={usd(amount)} />
          <Row
            label="Recibes aprox."
            value={softWei <= 0n ? '…'
              : buy ? `≈ ${formatDecimal(Number(softWei) / 1e18, { decimals: 4, minDecimals: 0 })} ${stock?.ticker ?? ''}`
              : usd(Number(softWei) / 1e18)}
          />
          <Row
            label="Comisión de Confío"
            value={feePolicy ? `${usd(amount * (feePct / 100))} (${formatDecimal(feePct, { decimals: 2, minDecimals: 0 })}%)` : '…'}
          />
          <Row label={buy ? 'Sale de' : 'Vuelve a'} value="Confío Dollar+" />
          {tradability === 'reduced'
            ? <Text style={styles.hint}>Fuera del horario principal el precio puede ser menos favorable.</Text> : null}
        </View>
      )}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {!blocked && quoteError ? <Text style={styles.error}>{quoteError}</Text> : null}
      {needsRiskRead ? (
        <Pressable onPress={openStock} style={styles.second} accessibilityRole="button" accessibilityLabel={`Abrir ${action.ticker}`}>
          <Text style={styles.secondText}>Abrir {action.ticker}</Text>
        </Pressable>
      ) : null}
      {blocked ? null : (
        <>
          {quoteError && !quoting ? (
            <Pressable onPress={() => setQuoteRound((n) => n + 1)} style={styles.second} accessibilityRole="button"
              accessibilityLabel="Actualizar precio">
              <Text style={[styles.secondText, styles.retryText]}>Actualizar precio</Text>
            </Pressable>
          ) : null}
          <Pressable
            onPress={() => void approve()}
            disabled={!ready || working}
            style={({ pressed }) => [styles.approve, (!ready || working) && styles.approveOff, pressed && styles.approvePressed]}
            accessibilityRole="button"
            accessibilityState={{ disabled: !ready || working, busy: working }}
            accessibilityLabel={buy ? 'Aprobar compra' : 'Aprobar venta'}
          >
            {working ? <ActivityIndicator size="small" color="#FFFFFF" />
              : <Text style={styles.approveText}>{buy ? 'Aprobar compra' : 'Aprobar venta'}</Text>}
          </Pressable>
          {working ? null : (
            <Pressable onPress={() => setStage({ key: 'dismissed' })} style={styles.second} accessibilityRole="button"
              accessibilityLabel={buy ? 'No comprar' : 'No vender'}>
              <Text style={styles.secondText}>{buy ? 'No comprar' : 'No vender'}</Text>
            </Pressable>
          )}
        </>
      )}
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  title: { fontSize: 16, fontWeight: '700', color: INK },
  name: { fontSize: 13, color: MUTED, marginTop: 2 },
  rows: { marginTop: 10, gap: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 },
  rowLabel: { fontSize: 14, color: MUTED },
  rowValue: { flexShrink: 1, fontSize: 15, fontWeight: '600', color: INK, textAlign: 'right' },
  hint: { fontSize: 13, lineHeight: 18, color: MUTED },
  blocked: { fontSize: 14, lineHeight: 20, color: INK, marginTop: 10 },
  error: { fontSize: 13, lineHeight: 18, color: '#B91C1C', marginTop: 10 },
  approve: { marginTop: 14, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD },
  approveOff: { backgroundColor: '#9CA3AF' },
  approvePressed: { backgroundColor: '#065F46' },
  approveText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  second: { marginTop: 6, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondText: { fontSize: 15, fontWeight: '600', color: MUTED },
  retryText: { color: EMERALD },
  settled: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  settledText: { flex: 1, fontSize: 15, lineHeight: 20, color: INK },
  settledGood: { fontWeight: '600', color: EMERALD },
  share: {
    marginTop: 12, height: 44, borderRadius: 12, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: '#A7F3D0',
  },
  sharePressed: { backgroundColor: '#ECFDF5' },
  shareText: { fontSize: 15, fontWeight: '700', color: EMERALD },
});
